"""Real models end to end on one deer photo. Checks wiring, not model quality.

Needs CUDA, the [inference] extra, CAMTRAP_WEIGHTS_DIR (a folder with manifest.json) and
CAMTRAP_SMOKE_PHOTO (a JPEG with a deer, EXIF-dated after 2025-01-01); skipped otherwise.
"""

import os
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api

from tests.conftest import ANN, jpeg
from tests.test_measure import results, run

try:
    import torch
    import megadetector  # noqa: F401
    import speciesnet  # noqa: F401
    HAVE_CUDA = torch.cuda.is_available()
except ImportError:
    HAVE_CUDA = False

PHOTO = os.environ.get("CAMTRAP_SMOKE_PHOTO")
pytestmark = pytest.mark.skipif(
    not (HAVE_CUDA and PHOTO and os.environ.get("CAMTRAP_WEIGHTS_DIR")),
    reason="GPU smoke: needs CUDA, the [inference] extra, CAMTRAP_WEIGHTS_DIR and CAMTRAP_SMOKE_PHOTO")


def test_real_models_find_a_deer_through_the_api(cloud, tmp_path):
    from camtrap_measure import inference

    cloud["photos"]["TON_CAM02/IMG_5304.JPG"] = jpeg("2025:01:01 00:00:00")  # window opens before the field photo
    cloud["annotations"] = [{**ANN, "updated_at": "2025-01-02T00:00:00+00:00"}]
    with TestClient(api.app) as c:  # lifespan: downloads nothing (pinned dir) but loads both models
        for _ in range(600):
            s = c.get("/api/status").json()["inference"]
            if s["status"] != "loading":
                break
            time.sleep(1)
        assert s["status"] == "ready" and s["backend"] == "real" and s["device"] == "cuda", s
        assert s["batch"] >= 1
        c.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
        c.post("/api/sync")
        d = tmp_path / "TON_CAM02"
        d.mkdir()
        shutil.copy(PHOTO, d / "deer.JPG")
        st = run(c, d)
        assert st["status"] == "done" and st["held"] == 0, st
        rows = results(c)
        assert rows and any(r["species"] == "white-tailed deer" for r in rows), rows
        r = rows[0]
        assert 0 <= r["x1"] < r["x2"] <= 1 and 0 <= r["y1"] < r["y2"] <= 1 and 0 < r["confidence"] <= 1
        assert r["distance_m"] is None  # ticket 07
        assert isinstance(inference.backend, inference.Real)
