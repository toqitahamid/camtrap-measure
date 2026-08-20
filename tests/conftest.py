"""Shared fixtures: the Supabase wrapper faked at its seam, plus synthetic annotations and EXIF JPEGs."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from camtrap_measure import api, store
from camtrap_measure import supabase_ro as sb

from tests.calib.synth import projective_photo


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
             "photos": {"TON_CAM02/IMG_5304.JPG": jpeg()}, "downloads": []}

    def guard():
        if state["offline"]:
            raise sb.Offline("no route to host")

    def sign_in(email, password):
        guard()
        if password != "pw":
            raise sb.AuthError("Invalid login credentials")
        return {"access_token": "at", "refresh_token": "rt0", "user": {"email": email}}

    def refresh(token):
        guard()
        if token == "revoked":
            raise sb.AuthError("Refresh token is not valid")
        state["refreshes"] += 1
        return {"access_token": "at", "refresh_token": f"rt{state['refreshes']}", "user": {"email": "tech@dept.gov"}}

    monkeypatch.setattr(api.sb, "sign_in", sign_in)
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
    return state


@pytest.fixture
def synced(cloud):
    c = TestClient(api.app)
    c.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    c.post("/api/sync")
    return c


@pytest.fixture
def client(cloud):
    return TestClient(api.app)