"""Shared fixtures: the Supabase wrapper faked at its seam, plus synthetic annotations and EXIF JPEGs.

The suite needs no network and no GPU, and must stay that way on a developer's machine that has both:
`HF_HUB_OFFLINE` keeps a cached Hugging Face login from quietly pulling the 7 GB weights (seen on the
Windows workstation, 2026-08-21), and `hermetic` below keeps the real models out of every test but the
GPU smoke test, which opts back in.
"""

import os

os.environ["HF_HUB_OFFLINE"] = "1"  # read by huggingface_hub at import time: must precede the app imports

import time  # noqa: E402
from io import BytesIO  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from camtrap_measure import api, inference, measure, store  # noqa: E402
from camtrap_measure import supabase_ro as sb  # noqa: E402

from tests.calib.synth import projective_photo  # noqa: E402

REAL_MODELS_INSTALLED = inference.models_installed  # the GPU smoke test restores this


@pytest.fixture(autouse=True)
def hermetic(monkeypatch, tmp_path):
    """Every test writes to its own data dir and sees no inference extra, whatever the machine has."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(inference, "models_installed", lambda: False)


def flag_photo_data(site="TON_CAM02", image="IMG_5304.JPG", relabel=None, n=None) -> dict:
    """Schema-v2 annotation JSON rendered from a known synthetic camera.
    relabel={(transect, dist): new_dist} mislabels flags; n keeps only the first n points."""
    ph, _ = projective_photo(noise_px=1.0)
    pts = [{"u": g.u, "v": g.v, "transect": g.transect, "distance": (relabel or {}).get((g.transect, g.dist), g.dist)}
           for g in ph.ground][:n]
    return {"schema_version": 2, "site": site, "image": image, "image_w": 1920, "image_h": 1080,
            "wire_ground_points": pts, "flag_vertical_spans": [], "flag_horizontal_spans": [],
            "flag_to_ground_spans": []}


def jpeg(date: str | None = "2026:03:13 12:37:33", make: str | None = None, model: str | None = None) -> bytes:
    exif = Image.Exif()
    if date:
        exif.get_ifd(0x8769)[0x9003] = date  # DateTimeOriginal
    if make:
        exif[0x010F], exif[0x0110] = make, model
    buf = BytesIO()
    Image.new("RGB", (2, 2)).save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


ANN = {
    "site": "TON_CAM02",
    "image_name": "IMG_5304.JPG",
    "storage_path": "TON_CAM02/IMG_5304.JPG",
    "status": "annotated",
    "labeler": "x@y",
    "updated_at": "2026-06-18T22:05:43+00:00",
    "data": flag_photo_data(),
}


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    """Fake cloud: mutable tables + a switch to go offline."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    state = {"annotations": [ANN], "sites": [{"name": "TON_CAM02"}], "offline": False, "refreshes": 0,
             "photos": {"TON_CAM02/IMG_5304.JPG": jpeg()}, "downloads": [], "codes_sent": []}

    def guard():
        if state["offline"]:
            raise sb.Offline("no route to host")

    def request_code(email):
        guard()
        state["codes_sent"].append(email)

    def verify_code(email, code):
        guard()
        if code != "123456":
            raise sb.AuthError("Token has expired or is invalid")
        return {"access_token": "at", "refresh_token": "rt0", "user": {"email": email}}

    def refresh(token):
        guard()
        if token == "revoked":
            raise sb.AuthError("Refresh token is not valid")
        state["refreshes"] += 1
        return {"access_token": "at", "refresh_token": f"rt{state['refreshes']}", "user": {"email": "tech@dept.gov"}}

    monkeypatch.setattr(api.sb, "request_code", request_code)
    monkeypatch.setattr(api.sb, "verify_code", verify_code)
    monkeypatch.setattr(api.sb, "refresh", refresh)
    monkeypatch.setattr(api.sb, "select_annotations", lambda tok: (guard(), list(state["annotations"]))[1])
    monkeypatch.setattr(api.sb, "select_sites", lambda tok: (guard(), list(state["sites"]))[1])

    def download(tok, path, bucket="photos"):
        guard()
        state["downloads"].append(path)
        got = state["photos"].get(path)  # None: not in storage
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(api.sb, "download_object", download)
    yield state
    for _ in range(250):  # a run started in this test (a sync's catch-up, say) must not write into the next test's store
        if not measure.current or measure.current["status"] != "running":
            break
        time.sleep(0.02)


@pytest.fixture
def synced(cloud):
    c = TestClient(api.app)
    c.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    c.post("/api/sync")
    return c


@pytest.fixture
def client(cloud):
    return TestClient(api.app)