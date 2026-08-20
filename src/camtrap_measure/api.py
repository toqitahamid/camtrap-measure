from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import calibration, store
from . import supabase_ro as sb

__version__ = version("camtrap-measure")
UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="CamTrap Measure")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/status")
def status():
    s = store.session()
    return {"signed_in": s is not None, "email": s["email"] if s else None, **store.summary()}


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
    """Fit every annotation that is new or relabeled since the last sync (EXIF read from storage)."""
    known = store.calibration_versions()
    fits = []
    for a in annotations:
        if known.get((a["site"], a["image_name"]), "") == a.get("updated_at"):
            continue
        jpeg = None
        if a.get("status") == "annotated" and a.get("storage_path"):
            jpeg = sb.download_object(token, a["storage_path"])  # None: gone from storage → red, not a crash
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
    """Per-camera calibration verdict, reason, and validity windows."""
    return calibration.cameras(store.sites(), store.calibrations())


# Built React page (frontend/ → npm run build). Mounted last so /api/* wins.
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
