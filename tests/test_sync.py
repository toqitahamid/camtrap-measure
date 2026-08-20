"""Login + Sync through the API, with the Supabase wrapper faked at its seam."""

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api, store
from camtrap_measure import supabase_ro as sb

ANN = {
    "site": "TON_CAM02",
    "image_name": "IMG_5304.JPG",
    "storage_path": "TON_CAM02/IMG_5304.JPG",
    "status": "annotated",
    "labeler": "x@y",
    "updated_at": "2026-06-18T22:05:43+00:00",
    "data": {"schema_version": 2, "wire_ground_points": [{"u": 1, "v": 2, "distance": 4}]},
}


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    """Fake cloud: mutable tables + a switch to go offline."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    state = {"annotations": [ANN], "sites": [{"name": "TON_CAM02"}], "offline": False, "refreshes": 0}

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
    return state


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
    relabeled = {**ANN, "data": {"schema_version": 2, "wire_ground_points": []}, "updated_at": "2026-07-01T00:00:00+00:00"}
    new = {**ANN, "site": "SRF_CAM08", "image_name": "IMG_3792.JPG", "storage_path": "SRF_CAM08/IMG_3792.JPG"}
    cloud["annotations"] = [relabeled, new]
    cloud["sites"].append({"name": "SRF_CAM08"})
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
