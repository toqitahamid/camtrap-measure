"""Real models end to end on one deer photo, with both methods. Checks wiring, not model quality.

Needs CUDA, the [inference] extra, CAMTRAP_WEIGHTS_DIR (a folder with manifest.json),
CAMTRAP_SMOKE_PHOTO (a JPEG with a deer) and CAMTRAP_SMOKE_FLAG (the same camera's flag photo,
EXIF-dated before the deer photo, with its schema-v2 .json annotation beside it); skipped otherwise.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api

from tests.test_measure import results, run

try:
    import torch
    import megadetector  # noqa: F401
    import speciesnet  # noqa: F401
    HAVE_CUDA = torch.cuda.is_available()
except ImportError:
    HAVE_CUDA = False

PHOTO, FLAG = os.environ.get("CAMTRAP_SMOKE_PHOTO"), os.environ.get("CAMTRAP_SMOKE_FLAG")
pytestmark = pytest.mark.skipif(
    not (HAVE_CUDA and PHOTO and FLAG and os.environ.get("CAMTRAP_WEIGHTS_DIR")),
    reason="GPU smoke: needs CUDA, the [inference] extra, CAMTRAP_WEIGHTS_DIR, CAMTRAP_SMOKE_PHOTO and CAMTRAP_SMOKE_FLAG")


@pytest.fixture(autouse=True)
def real_models(monkeypatch):
    """The one test that wants the real extra: undo conftest's hermetic stub."""
    from camtrap_measure import inference

    from tests.conftest import REAL_MODELS_INSTALLED

    monkeypatch.setattr(inference, "models_installed", REAL_MODELS_INSTALLED)


def test_real_models_measure_a_deer_through_the_api(cloud, tmp_path):
    from camtrap_measure import distance, inference

    flag = Path(FLAG)
    data = json.loads(flag.with_suffix(".json").read_text())
    site = data["site"]
    cloud["sites"] = [{"name": site}]
    cloud["annotations"] = [{"site": site, "image_name": flag.name, "storage_path": f"{site}/{flag.name}",
                             "status": "annotated", "labeler": "x", "updated_at": "2026-01-01T00:00:00+00:00", "data": data}]
    cloud["photos"] = {f"{site}/{flag.name}": flag.read_bytes()}
    with TestClient(api.app) as c:  # lifespan: downloads nothing (pinned dir) but loads all models
        for _ in range(600):
            s = c.get("/api/status").json()["inference"]
            if s["status"] != "loading":
                break
            time.sleep(1)
        assert s["status"] == "ready" and s["backend"] == "real" and s["device"] == "cuda", s
        assert s["batch"] >= 1
        c.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
        c.post("/api/sync")
        cam = {x["site"]: x for x in c.get("/api/cameras").json()}[site]
        assert cam["verdict"] == "green", cam
        d = tmp_path / site
        d.mkdir()
        shutil.copy(PHOTO, d / "deer.JPG")
        st = run(c, d)
        assert st["status"] == "done" and st["held"] == 0, st
        rows = results(c)
        deer = [r for r in rows if r["species"] == "white-tailed deer"]
        assert deer, rows
        r = deer[0]
        assert 0 <= r["x1"] < r["x2"] <= 1 and 0 <= r["y1"] < r["y2"] <= 1 and 0 < r["confidence"] <= 1
        assert r["match_score"] >= distance.MIN_INLIERS, r  # same camera, eight days apart: must align
        assert r["distance_m"] is not None and 0.5 < r["distance_m"] < 40, r
        assert r["q05_m"] < r["distance_m"] < r["q95_m"], r
        assert r["calibration_image"] == flag.name
        assert isinstance(inference.backend, inference.Real) and inference.backend.sam3 is None  # fast method never loads SAM3
        print("SMOKE md", {k: r[k] for k in ("species", "confidence", "distance_m", "q05_m", "q95_m", "match_score")})
        st = run(c, d, method="sam3", timeout=600)  # first precise run loads SAM3 (3.4 GB)
        assert st["status"] == "done" and st["held"] == 0, st
        assert inference.backend.sam3 is not None
        rows = results(c)
        assert {x["method"] for x in rows} == {"md", "sam3"}  # the other method's rows stay
        p = next((x for x in rows if x["method"] == "sam3" and x["species"] == "white-tailed deer"), None)
        assert p, rows
        assert p["distance_m"] is not None and abs(p["distance_m"] - r["distance_m"]) < 3, (p, r)  # same deer, feet vs box bottom
        assert p["q05_m"] < p["distance_m"] < p["q95_m"], p
        print("SMOKE sam3", {k: p[k] for k in ("species", "confidence", "distance_m", "q05_m", "q95_m", "match_score")})
