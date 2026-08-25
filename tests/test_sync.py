"""Login + Sync + the flag photos each camera offers, through the API, with the Supabase wrapper faked at its seam."""

from fastapi.testclient import TestClient

from camtrap_measure import api, store

from tests.conftest import ANN, flag_photo_data, jpeg


def test_fresh_install_is_signed_out_and_never_synced(client):
    s = client.get("/api/status").json()
    assert {k: s[k] for k in ("signed_in", "email", "last_sync", "annotations", "sites")} == {
        "signed_in": False, "email": None, "last_sync": None, "annotations": 0, "sites": 0}


def test_login_rejects_bad_code_with_server_message(client):
    r = client.post("/api/login", json={"email": "tech@dept.gov", "code": "000000"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Token has expired or is invalid"
    assert client.get("/api/status").json()["signed_in"] is False


def test_code_request_goes_to_the_cloud_and_offline_is_a_503(client, cloud):
    assert client.post("/api/login/code", json={"email": "tech@dept.gov"}).status_code == 200
    assert cloud["codes_sent"] == ["tech@dept.gov"]
    cloud["offline"] = True
    r = client.post("/api/login/code", json={"email": "tech@dept.gov"})
    assert r.status_code == 503 and "not reachable" in r.json()["detail"]
    r = client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    assert r.status_code == 503 and client.get("/api/status").json()["signed_in"] is False


def test_login_persists_session_across_engine_restarts(client):
    assert client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"}).status_code == 200
    fresh = TestClient(api.app)  # new process would read the same cached session file
    s = fresh.get("/api/status").json()
    assert s["signed_in"] is True and s["email"] == "tech@dept.gov"


def test_sync_requires_login(client):
    assert client.post("/api/sync").status_code == 401


def test_sync_pulls_annotations_and_sites_into_sqlite(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    r = client.post("/api/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["annotations"] == 1 and body["sites"] == 1
    assert body["last_sync"]
    assert store.annotations()[0]["data"]["schema_version"] == 2
    assert store.sites() == ["TON_CAM02"]
    assert client.get("/api/status").json()["last_sync"] == body["last_sync"]


def test_resync_picks_up_new_and_relabeled_annotations(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
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
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    first = client.post("/api/sync").json()
    cloud["offline"] = True
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "offline": True, "last_sync": first["last_sync"]}
    assert len(store.annotations()) == 1  # local data untouched


def test_offline_before_any_sync_has_no_date(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    cloud["offline"] = True
    assert client.post("/api/sync").json() == {"ok": False, "offline": True, "last_sync": None}


def test_sync_rotates_refresh_token(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    client.post("/api/sync")
    client.post("/api/sync")
    assert store.session()["refresh_token"] == "rt2"


def test_revoked_session_signs_out(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    store.save_session({"refresh_token": "revoked", "email": "tech@dept.gov"})
    r = client.post("/api/sync")
    assert r.status_code == 401
    assert client.get("/api/status").json()["signed_in"] is False


def test_logout_clears_session_keeps_local_data(client, cloud):
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    client.post("/api/sync")
    client.post("/api/logout")
    s = client.get("/api/status").json()
    assert s["signed_in"] is False and s["annotations"] == 1 and s["last_sync"]


# --- the flag photos each camera offers ------------------------------------------------

def cameras(c):
    return {cam["site"]: cam for cam in c.get("/api/cameras").json()}


def flags(c, site="TON_CAM02"):
    return cameras(c)[site]["flags"]


def test_sync_fits_the_flag_photo_and_lists_it_as_usable(synced):
    assert flags(synced) == [{"image_name": "IMG_5304.JPG", "captured_at": "2026-03-13T12:37:33", "ok": True, "reason": None}]


def test_camera_without_flag_photo_lists_nothing(cloud, synced):
    cloud["sites"].append({"name": "MAS_CAM01"})
    synced.post("/api/sync")
    assert flags(synced, "MAS_CAM01") == []


def test_unlabeled_flag_photo_is_unusable_and_names_it(cloud, synced):
    cloud["annotations"] = [{**ANN, "status": "empty", "data": None, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    [f] = flags(synced)
    assert f["ok"] is False and "IMG_5304.JPG" in f["reason"] and "not labeled" in f["reason"]


def test_too_few_flags_is_unusable_and_says_how_many(cloud, synced):
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(n=4), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    [f] = flags(synced)
    assert f["ok"] is False and "IMG_5304.JPG" in f["reason"] and "4 ground marks" in f["reason"] and "label more flags" in f["reason"]


def test_a_mislabeled_flag_still_fits_the_user_chooses(cloud, synced):
    # ticket 15: no quality verdict — the dept confirmed its labels and wants no warnings; a labeled photo is usable
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(relabel={("C", 4.0): 30}), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    assert flags(synced)[0]["ok"] is True


def test_missing_exif_date_is_still_usable(cloud, synced):
    cloud["photos"]["TON_CAM02/IMG_5304.JPG"] = jpeg(date=None)
    cloud["annotations"] = [{**ANN, "updated_at": "2026-07-01T00:00:00+00:00"},
                            {**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG", "data": flag_photo_data(image="IMG_7000.JPG")}]
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    assert [(f["image_name"], f["captured_at"], f["ok"]) for f in flags(synced)] == [
        ("IMG_5304.JPG", None, True), ("IMG_7000.JPG", "2026-07-04T09:00:00", True)]


def test_photo_missing_from_storage_is_unusable_not_a_crash(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_9999.JPG", "storage_path": "TON_CAM02/IMG_9999.JPG"})
    assert synced.post("/api/sync").status_code == 200
    f = {x["image_name"]: x for x in flags(synced)}["IMG_9999.JPG"]
    assert f["ok"] is False and "storage" in f["reason"]


def test_flag_photos_are_listed_by_name_ascending(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "data": flag_photo_data(image="IMG_7000.JPG")})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    assert [(f["image_name"], f["captured_at"]) for f in flags(synced)] == [
        ("IMG_5304.JPG", "2026-03-13T12:37:33"), ("IMG_7000.JPG", "2026-07-04T09:00:00")]


def test_flag_photos_sort_naturally_not_lexically(cloud, synced):
    # a plain string sort would put IMG_0010 before IMG_0004 ("0010" < "0004" is false, but "00104" < "0004..."
    # style traps are the point here): IMG_0004 < IMG_0010 < IMG_1999 must hold under natural, numeric order.
    cloud["annotations"] = [
        {**ANN, "image_name": "IMG_1999.JPG", "storage_path": "TON_CAM02/IMG_1999.JPG", "data": flag_photo_data(image="IMG_1999.JPG")},
        {**ANN, "image_name": "IMG_0004.JPG", "storage_path": "TON_CAM02/IMG_0004.JPG", "data": flag_photo_data(image="IMG_0004.JPG")},
        {**ANN, "image_name": "IMG_0010.JPG", "storage_path": "TON_CAM02/IMG_0010.JPG", "data": flag_photo_data(image="IMG_0010.JPG")},
    ]
    for name in ("IMG_1999.JPG", "IMG_0004.JPG", "IMG_0010.JPG"):
        cloud["photos"][f"TON_CAM02/{name}"] = jpeg()
    synced.post("/api/sync")
    assert [f["image_name"] for f in flags(synced)] == ["IMG_0004.JPG", "IMG_0010.JPG", "IMG_1999.JPG"]


def test_resync_refits_only_new_or_changed_annotations(cloud, synced):
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"]
    synced.post("/api/sync")
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"]  # unchanged: no download, no refit
    cloud["annotations"] = [{**ANN, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    assert cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"] * 2


def test_deleted_annotation_drops_its_flag_photo(cloud, synced):
    cloud["annotations"] = []
    synced.post("/api/sync")
    assert flags(synced) == []


def test_offline_sync_keeps_the_list(cloud, synced):
    cloud["offline"] = True
    synced.post("/api/sync")
    assert flags(synced)[0]["ok"] is True


def test_an_unlabeled_newer_flag_photo_leaves_the_older_one_usable(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "status": "empty", "data": None})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    assert [(f["image_name"], f["ok"]) for f in flags(synced)] == [("IMG_5304.JPG", True), ("IMG_7000.JPG", False)]


def test_malformed_annotation_is_unusable_not_a_failed_sync(cloud, synced):
    broken = {k: v for k, v in flag_photo_data().items() if k != "image_w"}  # KeyError inside the fit
    cloud["annotations"] = [{**ANN, "data": broken, "updated_at": "2026-07-01T00:00:00+00:00"}]
    r = synced.post("/api/sync")
    assert r.status_code == 200 and r.json()["ok"] is True
    [f] = flags(synced)
    assert f["ok"] is False and "IMG_5304.JPG" in f["reason"] and "could not" in f["reason"]


def test_storage_error_on_one_photo_does_not_fail_sync(cloud, synced):
    cloud["photos"]["TON_CAM02/IMG_5304.JPG"] = RuntimeError("503 from storage")
    cloud["annotations"] = [{**ANN, "updated_at": "2026-07-01T00:00:00+00:00"}]
    assert synced.post("/api/sync").status_code == 200
    assert flags(synced)[0]["ok"] is False


def test_unusable_photo_is_rechecked_next_sync_without_a_relabel(cloud, synced):
    cloud["annotations"].append({**ANN, "image_name": "IMG_9999.JPG", "storage_path": "TON_CAM02/IMG_9999.JPG"})
    synced.post("/api/sync")
    assert "storage" in {x["image_name"]: x for x in flags(synced)}["IMG_9999.JPG"]["reason"]
    cloud["photos"]["TON_CAM02/IMG_9999.JPG"] = jpeg("2026:07:04 09:00:00")  # tech re-uploaded it
    synced.post("/api/sync")
    assert {x["image_name"]: x["ok"] for x in flags(synced)} == {"IMG_9999.JPG": True, "IMG_5304.JPG": True}


def test_sync_caches_the_flag_photo_for_alignment(cloud, synced):
    p = store.ref_path("TON_CAM02", "IMG_5304.JPG")
    assert p.read_bytes() == cloud["photos"]["TON_CAM02/IMG_5304.JPG"]
    p.unlink()
    synced.post("/api/sync")  # usable row, unchanged annotation — still refetched because the file is gone
    assert p.exists() and cloud["downloads"] == ["TON_CAM02/IMG_5304.JPG"] * 2
