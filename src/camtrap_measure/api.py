from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

__version__ = version("camtrap-measure")
UI_DIR = Path(__file__).parent / "ui"

app = FastAPI(title="CamTrap Measure")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


# Built React page (frontend/ → npm run build). Mounted last so /api/* wins.
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
