"""Login + Sync + calibration verdicts through the API, with the Supabase wrapper faked at its seam."""

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


def jpeg(date: str | None = "2026:03:13 12:37:33") -> bytes:
    exif = Image.Exif()
    if date:
        exif.get_ifd(0x8769)[0x9003] = date  # DateTimeOriginal
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
        return state["photos"].get(path)  # None: not in storage

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


def test_fresh_install_is_signed_out_and_never_synced(client):
    s = client.get("/api/status").json()
    assert s == {"signed_in": False, "email": None, "last_sync": None, "annotations": 0, "sites": 0}


def test_login_rejects_bad_password_with_server_message(client):
    r = client.post("/api/login", json={"email": "tech@dept.gov", "password": "nope"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid login credentials"
    assert client.get("/api/status").json()["signed_in"] is False


def test_login_persists_session_across_engine_restarts(client):
    assert client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"}).status_code == 200
    fresh = TestClient(api.app)  # new process would read the same cached session file
    s = fresh.get("/api/status").json()
    assert s["signed_in"] is True and s["email"] == "tech@dept.gov"


def test_sync_requires_login(client):
    assert client.post("/api/sync").status_code == 401


def test_sync_pulls_annotations_and_sites_into_sqlite(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    r = client.post("/api/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["annotations"] == 1 and body["sites"] == 1
    assert body["last_sync"]
    assert store.annotations()[0]["data"]["schema_version"] == 2
    assert store.sites() == ["TON_CAM02"]
    assert client.get("/api/status").json()["last_sync"] == body["last_sync"]


def test_resync_picks_up_new_and_relabeled_annotations(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    client.post("/api/sync")
    relabeled = {**ANN, "data": flag_photo_data(n=0), "updated_at": "2026-07-01T00:00:00+00:00"}
    new = {**ANN, "site": "SRF_CAM08", "image_name": "IMG_3792.JPG", "storage_path": "SRF_CAM08/IMG_3792.JPG"}
    cloud["annotations"] = [relabeled, new]
    cloud["sites"].append({"name": "SRF_CAM08"})
    cloud["photos"]["SRF_CAM08/IMG_3792.JPG"] = jpeg()
    body = client.post("/api/sync").json()
    assert body["annotations"] == 2 and body["sites"] == 2
    rows = {(a["site"], a["image_name"]): a for a in store.annotations()}
    assert len(rows) == 2
    assert rows[("TON_CAM02", "IMG_5304.JPG")]["data"]["wire_ground_points"] == []


def test_offline_sync_reports_last_sync_instead_of_error(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    first = client.post("/api/sync").json()
    cloud["offline"] = True
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "offline": True, "last_sync": first["last_sync"]}
    assert len(store.annotations()) == 1  # local data untouched


def test_offline_before_any_sync_has_no_date(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    cloud["offline"] = True
    assert client.post("/api/sync").json() == {"ok": False, "offline": True, "last_sync": None}


def test_sync_rotates_refresh_token(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    client.post("/api/sync")
    client.post("/api/sync")
    assert store.session()["refresh_token"] == "rt2"


def test_revoked_session_signs_out(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    store.save_session({"refresh_token": "revoked", "email": "tech@dept.gov"})
    r = client.post("/api/sync")
    assert r.status_code == 401
    assert client.get("/api/status").json()["signed_in"] is False


def test_logout_clears_session_keeps_local_data(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    client.post("/api/sync")
    client.post("/api/logout")
    s = client.get("/api/status").json()
    assert s["signed_in"] is False and s["annotations"] == 1 and s["last_sync"]


# --- calibration verdicts ------------------------------------------------------

def cameras(c):
    return {cam["site"]: cam for cam in c.get("/api/cameras").json()}


def test_sync_fits_calibration_and_camera_is_green(synced):
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "green" and cam["reason"] is None
    assert cam["calibrations"] == [
        {"image_name": "IMG_5304.JPG", "captured_at": "2026-03-13T12:37:33", "window_end": None, "ok": True, "reason": None}
    ]


def test_camera_without_flag_photo_is_red(cloud, synced):
    cloud["sites"].append({"name": "MAS_CAM01"})
    synced.post("/api/sync")
    cam = cameras(synced)["MAS_CAM01"]
    assert cam["verdict"] == "red" and cam["calibrations"] == []
    assert "no flag photo" in cam["reason"].lower() and "FlagLabel" in cam["reason"]


def test_unlabeled_flag_photo_is_red_and_names_it(cloud, synced):
    cloud["annotations"] = [{**ANN, "status": "empty", "data": None, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "red"
    assert "IMG_5304.JPG" in cam["reason"] and "not labeled" in cam["reason"]


def test_too_few_flags_is_red_and_says_how_many(cloud, synced):
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(n=4), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    reason = cameras(synced)["TON_CAM02"]["reason"]
    assert "IMG_5304.JPG" in reason and "4 ground marks" in reason and "label more flags" in reason


def test_mislabeled_flag_is_red_and_names_the_flag(cloud, synced):
    # the 4 m flag on the centre transect was typed in as 30 m
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(relabel={("C", 4.0): 30}), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "red"
    assert "IMG_5304.JPG" in cam["reason"] and "30 m flag" in cam["reason"] and "centre" in cam["reason"]
    assert "check its distance label" in cam["reason"]


def test_missing_exif_date_is_red(cloud, synced):
    cloud["photos"]["TON_CAM02/IMG_5304.JPG"] = jpeg(date=None)
    cloud["annotations"] = [{**ANN, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "red" and cam["calibrations"][0]["captured_at"] is None
    assert "capture date" in cam["reason"] and "IMG_5304.JPG" in cam["reason"]


def test_photo_missing_from_storage_is_red_not_a_crash(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_9999.JPG", "storage_path": "TON_CAM02/IMG_9999.JPG"})
    assert synced.post("/api/sync").status_code == 200
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "red" and "IMG_9999.JPG" in cam["reason"] and "storage" in cam["reason"]


def test_reflagging_opens_a_new_window_and_closes_the_old(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "data": flag_photo_data(image="IMG_7000.JPG")})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "green"
    assert [(c["image_name"], c["captured_at"], c["window_end"]) for c in cam["calibrations"]] == [
        ("IMG_5304.JPG", "2026-03-13T12:37:33", "2026-07-04T09:00:00"),
        ("IMG_7000.JPG", "2026-07-04T09:00:00", None),
    ]


def test_resync_refits_only_new_or_changed_annotations(cloud, synced):
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"]
    synced.post("/api/sync")
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"]  # unchanged: no download, no refit
    cloud["annotations"] = [{**ANN, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"] * 2


def test_deleted_annotation_drops_its_calibration(cloud, synced):
    cloud["annotations"] = []
    synced.post("/api/sync")
    cam = cameras(synced)["TON_CAM02"]
    assert cam["verdict"] == "red" and cam["calibrations"] == []


def test_offline_sync_keeps_verdicts(cloud, synced):
    cloud["offline"] = True
    synced.post("/api/sync")
    assert cameras(synced)["TON_CAM02"]["verdict"] == "green"
