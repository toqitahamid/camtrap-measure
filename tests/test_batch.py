"""A site folder (ticket 27): camera folders matched to cameras by name, the camera stamp in the photos checked,
each photo given its flag photo by date, duplicates caught, and one queue that measures the ticked cameras.
Supabase is faked at its seam and inference at its boundary, as in test_measure."""

import time
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from camtrap_measure import api, batch, inference, measure, report

from tests.conftest import ANN, flag_photo_data, jpeg
from tests.test_measure import wait

CAMERAS = ["MAS_CAM01", "MAS_CAM02", "MAS_CAM04", "MAS_CAM06", "MAS_CAM07", "MAS_CAM10", "MAS_CAM14"]
# camera -> its flag photos (name, capture time); MAS_CAM06 has none, so it is "not labelled yet"
FLAGS = {
    "MAS_CAM01": [("IMG_0004.JPG", "2025:12:19 10:00:00"), ("IMG_2868.JPG", "2026:04:01 10:00:00")],
    "MAS_CAM02": [("IMG_0001.JPG", "2025:12:20 10:00:00")],
    "MAS_CAM04": [("IMG_0001.JPG", "2025:12:20 11:00:00")],
    "MAS_CAM07": [("IMG_0001.JPG", "2025:12:20 12:00:00")],
    "MAS_CAM10": [("IMG_0001.JPG", "2025:12:20 13:00:00")],
    "MAS_CAM14": [("IMG_0001.JPG", "2025:12:20 14:00:00")],
}


def shot(date: str | None = "2026:01:22 08:40:56", stamp: str | None = None) -> bytes:
    """A camera-trap JPEG with a capture time and, like a Browning, its camera name in EXIF UserComment."""
    exif = Image.Exif()
    ifd = exif.get_ifd(0x8769)
    if date:
        ifd[0x9003] = date
    if stamp:
        ifd[0x9286] = b"\0" * 8 + f"C[P] R0S1 T25F:P0000 {stamp}   M1".encode()  # 8 bytes: undefined character set
    buf = BytesIO()
    Image.new("RGB", (2, 2)).save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


@pytest.fixture
def site_cloud(cloud):
    cloud["sites"] = [{"name": c} for c in CAMERAS]
    cloud["annotations"], cloud["photos"] = [], {}
    for cam, flags in FLAGS.items():
        for image, date in flags:
            cloud["annotations"].append({**ANN, "site": cam, "image_name": image, "storage_path": f"{cam}/{image}",
                                         "data": flag_photo_data(site=cam, image=image)})
            cloud["photos"][f"{cam}/{image}"] = jpeg(date)
    return cloud


@pytest.fixture
def c(site_cloud):
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    assert client.post("/api/sync").json()["ok"]
    batch.SCANS.clear()
    batch.CHOICES.clear()
    yield client
    batch.SCANS.clear()
    batch.CHOICES.clear()


def make(root: Path, folders: dict[str, dict[str, bytes]]) -> Path:
    """A site folder: {"MAS_CAM01": {"IMG_1.JPG": shot(...)}, "notes": {}} (an empty dict is an empty folder)."""
    for rel, photos in folders.items():
        d = root / rel
        d.mkdir(parents=True, exist_ok=True)
        for name, data in photos.items():
            (d / name).write_bytes(data)
    return root


def plan(c, root: Path, **params) -> dict:
    """GET /api/site, polled while the photos are read."""
    for _ in range(400):
        r = c.get("/api/site", params={"path": str(root), **params})
        assert r.status_code == 200, r.text
        if r.json()["status"] != "reading":
            return r.json()
        params.pop("refresh", None)
        time.sleep(0.01)
    raise AssertionError("site folder never finished reading")


def row(p: dict, name: str) -> dict:
    return next(r for r in p["rows"] if r["name"] == name)


# --- names --------------------------------------------------------------------------------------------------

def test_a_folder_name_matches_its_camera_however_it_is_written():
    for name, want in [("MAS_CAM07_filtered", "MAS_CAM07"), ("mas cam 2", "MAS_CAM02"), ("MAS_CAM2", "MAS_CAM02"),
                       ("mas_cam02", "MAS_CAM02"), ("2026_MAS_CAM07", "MAS_CAM07"), ("MAS_CAM07 deer only", "MAS_CAM07"),
                       ("MASCAM-007", "MAS_CAM07")]:
        assert batch.matches(name, CAMERAS) == [want], name


def test_a_number_is_matched_whole_so_cam1_is_never_found_in_cam14():
    assert batch.matches("MAS_CAM14", ["MAS_CAM1", "MAS_CAM14"]) == ["MAS_CAM14"]
    assert batch.matches("MAS_CAM14_filtered", ["MAS_CAM1"]) == []
    assert batch.matches("XMAS_CAM01", ["MAS_CAM01"]) == []  # nor a word inside a longer word
    assert batch.matches("card 3", CAMERAS) == []


def test_site_folder_rows_match_by_name_and_say_how(c, tmp_path):
    root = make(tmp_path / "MAS_2026", {"MAS_CAM01": {"IMG_1.JPG": shot()}, "mas cam 2": {"IMG_1.JPG": shot()},
                                         "MAS_CAM07_filtered": {"IMG_9.JPG": shot()}, "notes": {}})
    p = plan(c, root)
    assert p["status"] == "ready" and p["folder"] == str(root)
    assert row(p, "MAS_CAM01")["camera"] == "MAS_CAM01" and row(p, "MAS_CAM01")["note"] is None
    assert row(p, "mas cam 2")["camera"] == "MAS_CAM02" and row(p, "mas cam 2")["note"] == 'Matched "mas cam 2" to MAS_CAM02'
    assert row(p, "MAS_CAM07_filtered")["camera"] == "MAS_CAM07"
    assert all(r["group"] == "ready" and r["ticked"] for r in p["rows"])
    assert p["skipped"] == [{"name": "notes", "why": "no photos inside"}]
    assert p["counts"] == {"check": 0, "cannot": 0, "ready": 3, "skipped": 1}
    assert p["ticked"] == {"cameras": 3, "photos": 3, "measured": 0} and p["pace_s"] == batch.DEFAULT_PACE_S


def test_photos_in_a_nested_folder_take_the_camera_of_the_nearest_folder_named_after_one(c, tmp_path):
    root = make(tmp_path / "site", {"MAS_CAM07/filtered": {"IMG_1.JPG": shot()}, "MAS_CAM10/2026/jan": {"IMG_2.JPG": shot()}})
    p = plan(c, root)
    nested = row(p, str(Path("MAS_CAM07") / "filtered"))
    assert nested["camera"] == "MAS_CAM07" and nested["note"] is None and nested["ticked"]
    assert row(p, str(Path("MAS_CAM10") / "2026" / "jan"))["camera"] == "MAS_CAM10"


def test_a_folder_with_photos_in_it_is_one_camera_not_a_site(c, tmp_path):
    d = make(tmp_path / "MAS_CAM01", {".": {"IMG_1.JPG": shot()}, "sub": {"IMG_2.JPG": shot()}})
    assert plan(c, d) == {"status": "single"}
    assert plan(c, make(tmp_path / "nothing", {"a": {}}))["status"] == "single"
    assert c.get("/api/site", params={"path": str(tmp_path / "gone")}).status_code == 400


def test_a_name_that_fits_two_cameras_waits_for_the_user_to_choose(c, tmp_path):
    root = make(tmp_path / "site", {"MAS_CAM01 and MAS_CAM10": {"IMG_1.JPG": shot()}})
    r = plan(c, root)["rows"][0]
    assert r["state"] == "ambiguous" and r["camera"] is None and r["candidates"] == ["MAS_CAM01", "MAS_CAM10"]
    assert r["group"] == "attention" and not r["tickable"] and not r["ticked"]
    assert r["warnings"] == ["The name fits MAS_CAM01 and MAS_CAM10. Choose the camera."]
    after = c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "camera": "MAS_CAM10"}).json()
    assert after["rows"][0]["camera"] == "MAS_CAM10" and after["rows"][0]["group"] == "ready" and after["rows"][0]["ticked"]


def test_unknown_and_unlabelled_cameras_cannot_be_ticked_and_point_to_flaglabel(c, tmp_path):
    root = make(tmp_path / "site", {"card 3": {"IMG_1.JPG": shot()}, "MAS_CAM06": {"IMG_1.JPG": shot()}})
    p = plan(c, root)
    unknown, unlabelled = row(p, "card 3"), row(p, "MAS_CAM06")
    assert unknown["state"] == "unknown" and unknown["camera"] is None
    assert unlabelled["state"] == "unlabelled" and unlabelled["camera"] == "MAS_CAM06"
    for r in (unknown, unlabelled):
        assert r["group"] == "attention" and not r["tickable"] and not r["ticked"] and r["actions"] == ["flaglabel"]
    assert p["counts"]["cannot"] == 2 and p["ticked"]["cameras"] == 0
    # ticking it anyway changes nothing
    assert not row(c.post("/api/site/choose", json={"path": str(root), "folder": unknown["folder"], "tick": True}).json(),
                   "card 3")["ticked"]


def test_open_flaglabel_opens_that_one_address(c, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert c.post("/api/flaglabel/open").json() == {"ok": True}
    assert opened == ["https://flaglabel.vercel.app/"]


def test_mac_twin_files_are_not_counted_by_the_site_scan(c, tmp_path):
    root = make(tmp_path / "site", {"MAS_CAM01": {"IMG_1.JPG": shot(), "._IMG_1.JPG": b"\x00\x05\x16\x07" + b"\x00" * 60}})
    p = plan(c, root)
    assert p["rows"][0]["photos"] == 1 and p["ticked"]["photos"] == 1


# --- the camera stamp ---------------------------------------------------------------------------------------

def test_a_browning_stamp_is_read_and_parsed(tmp_path):
    (tmp_path / "a.JPG").write_bytes(shot(stamp="MAS01"))
    text = batch.read_stamp(tmp_path / "a.JPG")
    assert text == "C[P] R0S1 T25F:P0000 MAS01 M1"
    assert batch.parse_stamp(text, {"MAS", "MOR"}) == ("MAS", 1, "MAS01")
    assert batch.parse_stamp("C[P] R0S1 T25F:P0000 MAS14   M7", {"MAS"})[:2] == ("MAS", 14)
    assert batch.parse_stamp("Taken by a Reconyx HC600", {"MAS"}) is None  # other brands: no check
    (tmp_path / "b.JPG").write_bytes(shot())
    assert batch.read_stamp(tmp_path / "b.JPG") is None
    assert batch.stamp_camera(("MAS", 14, "MAS14"), CAMERAS) == "MAS_CAM14"


def test_photos_stamped_with_another_camera_wait_for_the_user(c, tmp_path):
    """The real mistake on the dev store: MAS_CAM14's photos, stamped MAS14, filed as MAS_CAM04."""
    root = make(tmp_path / "site", {"MAS_CAM04": {f"IMG_{i}.JPG": shot(stamp="MAS14") for i in range(7)},
                                     "MAS_CAM01": {"IMG_1.JPG": shot(stamp="MAS01")}})
    p = plan(c, root)
    r = row(p, "MAS_CAM04")
    assert r["group"] == "attention" and r["tickable"] and not r["ticked"]
    assert r["warnings"] == ["The photos say they are from MAS_CAM14"] and r["actions"] == ["compare", "use", "keep"]
    assert r["stamp"] == {"text": "MAS14", "camera": "MAS_CAM14", "mismatch": True, "kept": False}
    assert row(p, "MAS_CAM01")["group"] == "ready" and row(p, "MAS_CAM01")["stamp"]["mismatch"] is False
    assert p["counts"]["check"] == 1

    used = c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "camera": "MAS_CAM14"}).json()
    assert row(used, "MAS_CAM04")["camera"] == "MAS_CAM14" and row(used, "MAS_CAM04")["group"] == "ready"
    assert row(used, "MAS_CAM04")["ticked"]

    c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "camera": "MAS_CAM04"})
    assert row(plan(c, root), "MAS_CAM04")["group"] == "attention"  # back to the folder's camera: warned again
    kept = c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "keep": "MAS_CAM04"}).json()
    k = row(kept, "MAS_CAM04")
    assert k["camera"] == "MAS_CAM04" and k["group"] == "ready" and k["ticked"] and k["warnings"] == []
    assert k["note"] == "You kept MAS_CAM04. The photos say MAS_CAM14."


def test_compare_lines_one_photo_up_against_both_flag_photos(c, tmp_path):
    root = make(tmp_path / "site", {"MAS_CAM04": {f"IMG_{i}.JPG": shot(stamp="MAS14") for i in range(3)}})
    r = plan(c, root)["rows"][0]
    got = c.post("/api/site/compare", json={"path": str(root), "folder": r["folder"]}).json()
    assert got["stamp"] == "MAS14" and Path(got["photo"]).parent == Path(r["folder"])
    assert [(f["site"], f["image_name"]) for f in got["flags"]] == [("MAS_CAM04", "IMG_0001.JPG"), ("MAS_CAM14", "IMG_0001.JPG")]
    for f in got["flags"]:
        assert isinstance(f["score"], int) and f["lines_up"] == (f["score"] >= batch.COMPARE_GOOD)
    assert c.get("/api/photo", params={"path": got["photo"], "size": "thumb"}).status_code == 200


# --- flag photo by date -------------------------------------------------------------------------------------

SETUP = {"site": "X", "image_name": "IMG_0004.JPG", "captured_at": "2025-12-19T10:00:00"}
SERVICE = {"site": "X", "image_name": "IMG_2868.JPG", "captured_at": "2026-04-01T10:00:00"}


def test_each_photo_gets_the_last_flag_photo_taken_before_it():
    got = batch.assign({"jan": "2026-01-10T08:00:00", "apr": "2026-04-05T08:00:00", "at": "2026-04-01T10:00:00",
                        "early": "2025-11-01T08:00:00"}, [SERVICE, SETUP])
    assert {k: c["image_name"] for k, c in got.items()} == {"jan": "IMG_0004.JPG", "apr": "IMG_2868.JPG",
                                                            "at": "IMG_2868.JPG", "early": "IMG_0004.JPG"}


def test_an_undated_photo_takes_the_flag_photo_of_the_first_dated_one():
    got = batch.assign({"may": "2026-05-01T08:00:00", "june": "2026-06-01T08:00:00", "none": None}, [SETUP, SERVICE])
    assert got["none"]["image_name"] == "IMG_2868.JPG"
    assert batch.assign({"none": None}, [SERVICE, SETUP])["none"]["image_name"] == "IMG_0004.JPG"  # nothing dated


def test_a_card_that_runs_past_a_service_visit_is_split_between_its_flag_photos(c, tmp_path):
    photos = {"IMG_1.JPG": shot("2026:01:10 08:00:00"), "IMG_2.JPG": shot("2026:02:10 08:00:00"),
              "IMG_3.JPG": shot("2026:04:05 08:00:00"), "IMG_0.JPG": shot("2025:11:01 08:00:00"), "IMG_9.JPG": shot(None)}
    root = make(tmp_path / "site", {"MAS_CAM01": photos})
    r = plan(c, root)["rows"][0]
    assert [(f["image_name"], f["visit"], f["photos"]) for f in r["flags"]] == \
        [("IMG_0004.JPG", "setup", 4), ("IMG_2868.JPG", "service", 1)]
    assert r["flags"][0]["captured_at"] == "2025-12-19T10:00:00" and r["flag_choice"] == ""
    assert [o["image_name"] for o in r["options"]] == ["IMG_0004.JPG", "IMG_2868.JPG"]
    one = c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "flag": "IMG_2868.JPG"}).json()["rows"][0]
    assert one["flag_choice"] == "IMG_2868.JPG" and [(f["image_name"], f["photos"]) for f in one["flags"]] == [("IMG_2868.JPG", 5)]
    back = c.post("/api/site/choose", json={"path": str(root), "folder": r["folder"], "flag": ""}).json()["rows"][0]
    assert len(back["flags"]) == 2


def test_an_answer_is_current_only_against_its_own_cameras_flag_photo():
    known = {"method": "md", "fidelity": "research", "site": "MAS_CAM04", "calibration_image": "IMG_0001.JPG",
             "calibration_version": "v1"}
    same = {"site": "MAS_CAM04", "image_name": "IMG_0001.JPG", "updated_at": "v1"}
    assert measure.current_answer(known, same, "md", "research")
    assert not measure.current_answer(known, {**same, "site": "MAS_CAM14"}, "md", "research")  # same file name, other camera
    assert not measure.current_answer(known, {**same, "image_name": "IMG_2868.JPG"}, "md", "research")


# --- duplicates ---------------------------------------------------------------------------------------------

def test_two_folders_with_the_same_photos_are_flagged_and_only_the_smaller_is_ticked(c, tmp_path):
    every = {f"IMG_{i}.JPG": shot(f"2026:01:0{i + 1} 08:00:00") for i in range(4)}
    root = make(tmp_path / "site", {"MAS_CAM07": every, "MAS_CAM07_filtered": dict(list(every.items())[:2]),
                                     "MAS_CAM10": {"IMG_0.JPG": shot("2026:03:01 08:00:00")}})
    p = plan(c, root)
    full, filtered = row(p, "MAS_CAM07"), row(p, "MAS_CAM07_filtered")
    text = "MAS_CAM07_filtered has the same photos as MAS_CAM07. Measure only one."
    assert full["warnings"] == [text] and filtered["warnings"] == [text]
    assert filtered["ticked"] and not full["ticked"] and full["tickable"]
    assert full["group"] == filtered["group"] == "attention" and row(p, "MAS_CAM10")["warnings"] == []


# --- the queue ----------------------------------------------------------------------------------------------

def test_a_site_run_measures_each_camera_against_its_own_flag_photos_and_carries_on(c, tmp_path, monkeypatch):
    calls = []

    def spy(paths, calibration, method, **kw):
        calls.append((calibration["site"], calibration["image_name"], sorted(p.name for p in paths)))
        yield from inference.fake(paths, calibration, method, **kw)

    monkeypatch.setattr(api.inference, "backend", spy)
    root = make(tmp_path / "site", {
        "MAS_CAM01": {"IMG_1.JPG": shot("2026:01:10 08:00:00"), "IMG_2.JPG": shot("2026:04:05 08:00:00")},
        "mas cam 2": {"IMG_1.JPG": shot("2026:01:11 08:00:00")},
        "MAS_CAM04": {"IMG_1.JPG": shot(stamp="MAS14")},
        "card 3": {"IMG_1.JPG": shot()}})
    p = plan(c, root)
    assert p["ticked"] == {"cameras": 2, "photos": 3, "measured": 0}
    r = c.post("/api/site/run", json={"path": str(root), "method": "md"})
    assert r.status_code == 200, r.text
    st = wait(c)
    assert st["status"] == "done" and st["kind"] == "site" and st["folder"] == str(root) and st["total"] == 3
    assert sorted(calls) == [("MAS_CAM01", "IMG_0004.JPG", ["IMG_1.JPG"]), ("MAS_CAM01", "IMG_2868.JPG", ["IMG_2.JPG"]),
                             ("MAS_CAM02", "IMG_0001.JPG", ["IMG_1.JPG"])]  # one call per camera folder and flag photo
    cams = {cam["name"]: cam for cam in st["cameras"]}
    assert cams["MAS_CAM01"]["status"] == "done" and cams["MAS_CAM01"]["photos"] == 2 and cams["MAS_CAM01"]["done"] == 2
    assert cams["MAS_CAM01"]["flags"] == ["IMG_0004.JPG", "IMG_2868.JPG"] and cams["mas cam 2"]["site"] == "MAS_CAM02"
    assert {"deer", "median_m", "needs_look"} <= cams["MAS_CAM01"].keys()
    assert sorted(st["left_out"], key=lambda x: x["name"]) == [{"name": "MAS_CAM04", "why": "check which camera it is"},
                                                               {"name": "card 3", "why": "no camera with this name"}]
    by_photo = {(Path(x["path"]).parent.name, Path(x["path"]).name): (x["site"], x["calibration_image"])
                for x in c.get("/api/results").json()}
    for (folder, name), (cam, flag) in by_photo.items():
        assert (cam, flag) == {("MAS_CAM01", "IMG_1.JPG"): ("MAS_CAM01", "IMG_0004.JPG"),
                               ("MAS_CAM01", "IMG_2.JPG"): ("MAS_CAM01", "IMG_2868.JPG"),
                               ("mas cam 2", "IMG_1.JPG"): ("MAS_CAM02", "IMG_0001.JPG")}[(folder, name)]

    # measured against their own flag photos, so nothing is out of date and choosing the folder again skips them all
    after = plan(c, root)
    assert row(after, "MAS_CAM01")["measured"] == 2 and after["ticked"]["measured"] == 3
    listing = c.get("/api/folder", params={"path": str(root)}).json()
    measured = [x for x in listing["rows"] if x["measured"]]
    assert len(measured) == 3 and not any(x["stale"] for x in listing["rows"])
    calls.clear()
    again = c.post("/api/site/run", json={"path": str(root), "method": "md"})
    assert again.status_code == 200 and wait(c)["skipped"] == 3 and calls == []


def test_stop_keeps_what_is_done_and_the_next_run_carries_on(c, tmp_path, monkeypatch):
    import threading

    gate = threading.Semaphore(0)

    def slow(paths, calibration, method, **kw):
        for p in paths:
            assert gate.acquire(timeout=5)
            yield from inference.fake([p], calibration, method)

    monkeypatch.setattr(api.inference, "backend", slow)
    root = make(tmp_path / "site", {"MAS_CAM02": {f"IMG_{i}.JPG": shot() for i in range(3)},
                                     "MAS_CAM10": {f"IMG_{i}.JPG": shot() for i in range(3)}})
    plan(c, root)
    c.post("/api/site/run", json={"path": str(root), "method": "md"})
    gate.release()
    for _ in range(300):
        if c.get("/api/run").json()["done"] >= 1:
            break
        time.sleep(0.01)
    assert c.post("/api/site/run", json={"path": str(root), "method": "md"}).status_code == 409  # one run at a time
    c.post("/api/run/cancel")
    gate.release(5)
    st = wait(c)
    assert st["status"] == "cancelled" and st["cameras"][0]["status"] == "stopped" and st["cameras"][1]["status"] == "waiting"
    finished = st["done"]
    gate.release(10)
    c.post("/api/site/run", json={"path": str(root), "method": "md"})
    st = wait(c)
    assert st["status"] == "done" and st["skipped"] == finished and st["done"] == 6


def test_photos_picked_out_of_a_site_folder_are_measured_against_their_own_flag_photos(c, tmp_path, monkeypatch):
    root = make(tmp_path / "site", {"MAS_CAM01": {"IMG_1.JPG": shot("2026:04:05 08:00:00"), "IMG_2.JPG": shot()}})
    plan(c, root)
    pick = str(root / "MAS_CAM01" / "IMG_1.JPG")
    assert c.post("/api/site/run", json={"path": str(root), "method": "md", "photos": [pick]}).status_code == 200
    st = wait(c)
    assert st["total"] == 1 and st["left_out"] == []
    assert {x["calibration_image"] for x in c.get("/api/results").json()} <= {"IMG_2868.JPG"}
    bad = c.post("/api/site/run", json={"path": str(root), "method": "md", "photos": [str(tmp_path / "x.JPG")]})
    assert bad.status_code == 400


def test_nothing_ticked_is_refused(c, tmp_path):
    root = make(tmp_path / "site", {"card 3": {"IMG_1.JPG": shot()}})
    plan(c, root)
    r = c.post("/api/site/run", json={"path": str(root), "method": "md"})
    assert r.status_code == 400 and "Tick at least one camera" in r.json()["detail"]


# --- results and table over a site folder -------------------------------------------------------------------

def test_results_and_the_table_for_a_site_folder_include_its_camera_folders(c, tmp_path):
    root = make(tmp_path / "site", {"MAS_CAM01": {"IMG_1.JPG": shot()}, "MAS_CAM02/filtered": {"IMG_1.JPG": shot()}})
    plan(c, root)
    c.post("/api/site/run", json={"path": str(root), "method": "md"})
    assert wait(c)["status"] == "done"
    assert c.get("/api/summary", params={"folder": str(root)}).json()["photos"] == 2
    assert c.get("/api/summary", params={"folder": str(root / "MAS_CAM02")}).json()["photos"] == 1  # below it too
    assert c.get("/api/summary", params={"folder": str(root / "MAS_CAM01")}).json()["photos"] == 1
    listing = c.get("/api/folder", params={"path": str(root)}).json()
    assert [x["name"] for x in listing["rows"]] == [str(Path("MAS_CAM01") / "IMG_1.JPG"),
                                                    str(Path("MAS_CAM02") / "filtered" / "IMG_1.JPG")]
    assert all(x["measured"] and x["flag_site"] for x in listing["rows"])
    for x in listing["rows"]:
        assert c.get("/api/photo", params={"path": x["path"], "size": "thumb"}).status_code == 200
    assert report._in_folder(str(root / "a" / "b.JPG"), str(root)) and not report._in_folder(str(tmp_path / "b.JPG"), str(root))
