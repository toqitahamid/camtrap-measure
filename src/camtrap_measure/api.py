import io
import subprocess
import threading
from contextlib import asynccontextmanager
from datetime import date
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import calibration, inference, measure, report, store
from . import supabase_ro as sb

__version__ = version("camtrap-measure")
UI_DIR = Path(__file__).parent / "ui"


def _commit() -> str | None:
    """The checkout the app runs from, as `git describe --tags --always` (nearest tag + distance + SHA — the
    word to write into ref.txt to pin it); None outside git. The launcher updates the checkout at every start."""
    # ponytail: asks git about this file's folder, which is the clone because uv installs the project editable;
    # a non-editable install would report the clone's HEAD, not the installed code's. Read from package
    # metadata if that ever changes.
    try:
        return subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, timeout=5, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


COMMIT = _commit()


@asynccontextmanager
async def lifespan(app):
    inference.state["status"] = "loading"  # set before the thread exists, so no request slips through on the fake
    threading.Thread(target=inference.warmup, daemon=True).start()  # weights check + model load; UI polls /api/status
    yield


app = FastAPI(title="CamTrap Measure", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "commit": COMMIT}


@app.get("/api/status")
def status():
    s = store.session()
    return {"signed_in": s is not None, "email": s["email"] if s else None, **store.summary(), "inference": inference.state}


def _remember(sess: dict) -> None:
    store.save_session({"refresh_token": sess["refresh_token"], "email": sess["user"]["email"]})


class Login(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(body: Login):
    try:
        sess = sb.sign_in(body.email, body.password)
    except sb.AuthError as e:
        raise HTTPException(401, str(e))
    _remember(sess)
    return {"ok": True}


@app.post("/api/logout")
def logout():
    store.save_session(None)
    return {"ok": True}


def _fit_changed(annotations: list[dict], token: str) -> list[dict]:
    """Fit every annotation that is new, relabeled, or still red since the last sync (EXIF read from storage)."""
    known = store.calibration_versions()  # green rows only: red ones are re-checked every sync (re-uploads)
    fits = []
    for a in annotations:
        if known.get((a["site"], a["image_name"]), "") == a.get("updated_at"):
            continue
        try:
            jpeg = sb.download_object(token, a["storage_path"]) if a.get("storage_path") else None
        except (sb.Offline, sb.AuthError):
            raise
        except Exception as e:  # storage 5xx/403 on one photo: red row, sync goes on
            fits.append({**calibration.fit(a, None), "reason": f"{a['image_name']} could not be fetched from cloud storage ({e}) — try Sync again later."})
            continue
        if jpeg:
            store.save_ref(a["site"], a["image_name"], jpeg)  # the distance net aligns every photo to this flag photo
        fits.append(calibration.fit(a, jpeg))
    return fits


@app.post("/api/sync")
def sync():
    """Pull annotations + sites into the local mirror and fit new calibrations. Offline is not an error."""
    cached = store.session()
    if cached is None:
        raise HTTPException(401, "Not signed in")
    try:
        sess = sb.refresh(cached["refresh_token"])
        _remember(sess)
        token = sess["access_token"]
        annotations, sites = sb.select_annotations(token), sb.select_sites(token)
        fits = _fit_changed(annotations, token)
    except sb.AuthError as e:
        store.save_session(None)
        raise HTTPException(401, str(e))
    except sb.Offline:
        return {"ok": False, "offline": True, "last_sync": store.summary()["last_sync"]}
    last_sync = store.replace_mirror(annotations, sites, fits)
    remeasure = measure.start_held() if inference.state["status"] == "ready" else None  # held photos whose calibration may have arrived
    return {"ok": True, "last_sync": last_sync, "annotations": len(annotations), "sites": len(sites), "remeasure": remeasure}


@app.get("/api/cameras")
def cameras():
    """Per-camera calibration verdict, reason, and validity windows."""
    return calibration.cameras(store.sites(), store.calibrations())


class RunRequest(BaseModel):
    folder: str
    method: str = inference.DEFAULT_METHOD
    rerun: bool = False  # replace current answers too; default measures only what has none yet


@app.post("/api/run")
def start_run(body: RunRequest):
    """Measure every JPEG in a folder named after a camera. Progress via GET /api/run."""
    if inference.state["status"] != "ready":
        raise HTTPException(503, inference.state["error"] or "Models are still loading — try again in a moment.")
    try:
        return measure.start(body.folder, body.method, body.rerun)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.get("/api/run")
def run_status():
    return measure.status()


@app.post("/api/run/cancel")
def cancel_run():
    """Stop after the photo in flight. Finished photos keep their answers; Measure again continues."""
    return measure.cancel()


@app.get("/api/methods")
def methods():
    return {"default": inference.DEFAULT_METHOD, "methods": inference.METHODS}


@app.get("/api/results")
def results():
    """One row per detection, joined with its photo."""
    return store.detections()


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


@app.get("/api/summary")
def summary(site: str | None = None, date_from: date | None = None, date_to: date | None = None, all_species: bool = False):
    """Counts, deer-distance histogram, per-camera stats for the chosen site / capture-date range (YYYY-MM-DD, inclusive)."""
    return report.summary(site, _iso(date_from), _iso(date_to), all_species)


@app.get("/api/suspicious")
def suspicious(site: str | None = None, date_from: date | None = None, date_to: date | None = None):
    """The photos that need a look, each with its reasons — nothing else requires review."""
    return report.suspicious(site, _iso(date_from), _iso(date_to))


@app.get("/api/photo")
def photo(path: str):
    """A measured photo, shrunk for the gallery. Only paths a run has recorded are served."""
    from PIL import Image

    if not store.photo_known(path):
        raise HTTPException(404, "Not a measured photo")
    try:
        with Image.open(path) as im:
            im.draft("RGB", (640, 640))  # JPEG decodes at reduced size: a 20-MP frame never lands in memory whole
            im = im.convert("RGB")
            im.thumbnail((640, 640))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
    except (OSError, ValueError):
        raise HTTPException(404, "Photo unreadable or moved")
    return Response(buf.getvalue(), media_type="image/jpeg")


@app.get("/api/export.csv")
def export(site: str | None = None, date_from: date | None = None, date_to: date | None = None,
           all_species: bool = False, include_suspicious: bool = False):
    """The documented CSV. Suspicious rows stay out unless include_suspicious is set — never silently."""
    name = f"camtrap-measure_{site or 'all'}_{date_from or 'start'}_{date_to or 'end'}.csv"
    return Response(report.export_csv(site, _iso(date_from), _iso(date_to), all_species, include_suspicious),
                    media_type="text/csv; charset=utf-8", headers={"content-disposition": f'attachment; filename="{name}"'})


# Built React page (frontend/ → npm run build). Mounted last so /api/* wins.
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
