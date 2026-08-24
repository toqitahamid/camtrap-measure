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

from . import calibration, dialogs, inference, measure, report, store
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
    # `live` over `state`: which models hold VRAM changes during a run, and the batch size is not known
    # until SpeciesNet has been loaded once — neither is settled at warmup any more.
    return {"signed_in": s is not None, "email": s["email"] if s else None, **store.summary(),
            "inference": {**inference.state, **inference.live()}}


def _remember(sess: dict) -> None:
    store.save_session({"refresh_token": sess["refresh_token"], "email": sess["user"]["email"]})


class Email(BaseModel):
    email: str


class Login(BaseModel):
    email: str
    code: str


@app.post("/api/login/code")
def login_code(body: Email):
    """Step one: Supabase emails a one-time code to an existing FlagLabel account."""
    try:
        sb.request_code(body.email)
    except sb.AuthError as e:
        raise HTTPException(401, str(e))
    except sb.Offline:
        raise HTTPException(503, "FlagLabel cloud not reachable — check the internet connection")
    return {"ok": True}


@app.post("/api/login")
def login(body: Login):
    """Step two: the code from the email becomes the remembered session."""
    try:
        sess = sb.verify_code(body.email, body.code)
    except sb.AuthError as e:
        raise HTTPException(401, str(e))
    except sb.Offline:
        raise HTTPException(503, "FlagLabel cloud not reachable — check the internet connection")
    _remember(sess)
    return {"ok": True}


@app.post("/api/logout")
def logout():
    store.save_session(None)
    return {"ok": True}


def _fit_changed(annotations: list[dict], token: str) -> list[dict]:
    """Fit every annotation that is new, relabeled, or still unusable since the last sync (EXIF read from storage)."""
    known = store.calibration_versions()  # usable rows only: the others are re-checked every sync (re-uploads, labels)
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
    return {"ok": True, "last_sync": last_sync, "annotations": len(annotations), "sites": len(sites)}


@app.get("/api/cameras")
def cameras():
    """Every camera with its flag photos (usable ones carry ok=True) — what the Measure card offers."""
    return calibration.cameras(store.sites(), store.calibrations())


@app.post("/api/folder/pick")
def pick_folder():
    """Browse…: the desktop window's own folder chooser. folder=null with a reason (no native window, or the
    user cancelled) — the page then keeps the typed path."""
    folder, reason = dialogs.pick_folder()
    return {"folder": folder, "reason": reason}


@app.get("/api/folder")
def folder_listing(path: str, site: str = "", flag: str = "", method: str = inference.DEFAULT_METHOD):
    """Every JPEG in the folder with the answer stored for this flag photo and method — what the photo list
    and the table render, before and after a run."""
    try:
        return report.folder(path, site, flag, method)
    except ValueError as e:
        raise HTTPException(400, str(e))


class RunRequest(BaseModel):
    folder: str
    site: str
    flag: str  # image_name of the flag photo to measure against
    method: str = inference.DEFAULT_METHOD
    rerun: bool = False  # replace current answers too; default measures only what has none yet
    photos: list[str] | None = None  # the picked subset of the folder; None measures the whole folder


@app.post("/api/run")
def start_run(body: RunRequest):
    """Measure a folder — or the photos picked out of it — against one camera's flag photo. Progress via GET /api/run."""
    if inference.state["status"] != "ready":
        raise HTTPException(503, inference.state["error"] or "Models are still loading — try again in a moment.")
    try:
        return measure.start(body.folder, body.site, body.flag, body.method, body.rerun, body.photos)
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
def summary(site: str | None = None, date_from: date | None = None, date_to: date | None = None,
            all_species: bool = False, folder: str | None = None):
    """Counts, deer-distance histogram, per-camera stats for the chosen site / capture-date range (YYYY-MM-DD,
    inclusive). `folder` narrows it to the photos measured out of that one folder."""
    return report.summary(site, _iso(date_from), _iso(date_to), all_species, folder)


SIZES = {"thumb": 320, "full": 1600}  # list icon / the viewer; the originals are 20-MP and never reach the page whole


def _shrunk(path: Path, px: int) -> Response:
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.draft("RGB", (px, px))  # JPEG decodes at reduced size: a 20-MP frame never lands in memory whole
            im = im.convert("RGB")
            im.thumbnail((px, px))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
    except (OSError, ValueError):
        raise HTTPException(404, "Photo unreadable or moved")
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"cache-control": "max-age=86400"})


@app.get("/api/photo")
def photo(path: str, size: str = "full"):
    """A photo, shrunk: one a run has recorded, or a JPEG in a folder this engine has listed. Nothing else."""
    if not (store.photo_known(path) or report.listed(path)):
        raise HTTPException(404, "Not a measured photo, and not in a folder this window has opened")
    return _shrunk(Path(path), SIZES.get(size, SIZES["full"]))


@app.get("/api/flag")
def flag_photo(site: str, image: str, size: str = "full"):
    """The flag photo a camera's numbers were measured against — the reference the reviewer compares to."""
    ref = store.ref_path(site, image)
    if not any(c["site"] == site and c["image_name"] == image for c in store.calibrations()) or not ref.exists():
        raise HTTPException(404, "Not a synced flag photo")
    return _shrunk(ref, SIZES.get(size, SIZES["full"]))


@app.get("/api/export.csv")
def export(site: str | None = None, date_from: date | None = None, date_to: date | None = None,
           all_species: bool = False, include_suspicious: bool = False, folder: str | None = None):
    """The documented CSV. Suspicious rows stay out unless include_suspicious is set — never silently."""
    name = f"camtrap-measure_{site or 'all'}_{date_from or 'start'}_{date_to or 'end'}.csv"
    return Response(report.export_csv(site, _iso(date_from), _iso(date_to), all_species, include_suspicious, folder),
                    media_type="text/csv; charset=utf-8", headers={"content-disposition": f'attachment; filename="{name}"'})


# Built React page (frontend/ → npm run build). Mounted last so /api/* wins.
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
