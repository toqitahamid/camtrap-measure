from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store
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


@app.post("/api/sync")
def sync():
    """Pull annotations + sites into the local mirror. Offline is not an error."""
    cached = store.session()
    if cached is None:
        raise HTTPException(401, "Not signed in")
    try:
        sess = sb.refresh(cached["refresh_token"])
        _remember(sess)
        token = sess["access_token"]
        annotations, sites = sb.select_annotations(token), sb.select_sites(token)
    except sb.AuthError as e:
        store.save_session(None)
        raise HTTPException(401, str(e))
    except sb.Offline:
        return {"ok": False, "offline": True, "last_sync": store.summary()["last_sync"]}
    last_sync = store.replace_mirror(annotations, sites)
    return {"ok": True, "last_sync": last_sync, "annotations": len(annotations), "sites": len(sites)}


# Built React page (frontend/ → npm run build). Mounted last so /api/* wins.
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
