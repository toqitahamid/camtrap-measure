"""Measurement runs through the API (every JPEG in a folder against the flag photo the user picked), with
inference faked at its boundary and Supabase faked at its seam."""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api, inference

from tests.conftest import ANN, flag_photo_data, jpeg

IN_WINDOW = "2026:05:01 08:00:00"  # a plausible capture date; nothing depends on it any more (ticket 15)


def folder(tmp_path: Path, site="TON_CAM02", photos: dict[str, bytes] | None = None) -> Path:
    d = tmp_path / "photos" / site
    d.mkdir(parents=True)
    for name, data in (photos or {"IMG_0005.JPG": jpeg(IN_WINDOW, "Browning", "BTC-7E")}).items():
        (d / name).write_bytes(data)
    return d


SITE, FLAG = "TON_CAM02", "IMG_5304.JPG"


def run(c: TestClient, d: Path, method: str | None = "md", timeout=4.0, rerun=False, site=SITE, flag=FLAG) -> dict:
    """Start a run against one flag photo (method=None: let the API pick its default) and poll until it ends."""
    r = c.post("/api/run", json={"folder": str(d), "site": site, "flag": flag, "rerun": rerun, **({"method": method} if method else {})})
    assert r.status_code == 200, r.text
    return wait(c, timeout)


def wait(c: TestClient, timeout=4.0) -> dict:
    """Poll the current run until it ends."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = c.get("/api/run").json()
        if st["status"] != "running":
            return st
        time.sleep(min(1.0, timeout / 200))
    raise AssertionError("run did not finish")


def spying():
    """A fake backend that also records which photos it was asked for → (backend, seen)."""
    seen: list[Path] = []

    def spy(paths, calibration, method):
        seen.extend(paths)
        yield from inference.fake(paths, calibration, method)
    return spy, seen


def results(c: TestClient) -> list[dict]:
    return c.get("/api/results").json()


def expected_detections(names: list[str]) -> int:
    return sum(len(r.detections) for r in inference.fake([Path(n) for n in names], {}, "md"))


# --- folder validation ----------------------------------------------------------

def test_unknown_camera_is_refused(synced, tmp_path):
    r = synced.post("/api/run", json={"folder": str(folder(tmp_path)), "site": "TON_CAM99", "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and "TON_CAM99" in r.json()["detail"] and "not a camera" in r.json()["detail"]


def test_unknown_flag_photo_is_refused(synced, tmp_path):
    r = synced.post("/api/run", json={"folder": str(folder(tmp_path)), "site": SITE, "flag": "IMG_0000.JPG", "method": "md"})
    assert r.status_code == 400 and "IMG_0000.JPG" in r.json()["detail"] and "Sync" in r.json()["detail"]


def test_unusable_flag_photo_is_refused_with_its_reason(cloud, synced, tmp_path):
    cloud["annotations"] = [{**ANN, "status": "empty", "data": None, "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    r = synced.post("/api/run", json={"folder": str(folder(tmp_path)), "site": SITE, "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and "not labeled" in r.json()["detail"]


def test_flag_photo_missing_from_disk_asks_for_sync(synced, tmp_path):
    from camtrap_measure import store
    store.ref_path(SITE, FLAG).unlink()
    r = synced.post("/api/run", json={"folder": str(folder(tmp_path)), "site": SITE, "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and FLAG in r.json()["detail"] and "Sync" in r.json()["detail"]
    synced.post("/api/sync")  # refetches it
    assert run(synced, folder(tmp_path / "again"))["status"] == "done"


def test_folder_name_does_not_matter(synced, tmp_path):
    st = run(synced, folder(tmp_path, site="anything"))
    assert st["status"] == "done" and st["site"] == SITE and st["flag"] == FLAG and results(synced)[0]["site"] == SITE


def test_missing_folder_is_refused(synced, tmp_path):
    r = synced.post("/api/run", json={"folder": str(tmp_path / "nope"), "site": SITE, "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and "not found" in r.json()["detail"]


def test_folder_without_jpegs_is_refused(synced, tmp_path):
    d = folder(tmp_path, photos={"notes.txt": b"x"})
    r = synced.post("/api/run", json={"folder": str(d), "site": SITE, "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and "no jpeg" in r.json()["detail"].lower()


def test_before_first_sync_asks_for_sync(client, tmp_path):
    r = client.post("/api/run", json={"folder": str(folder(tmp_path)), "site": SITE, "flag": FLAG, "method": "md"})
    assert r.status_code == 400 and "Sync" in r.json()["detail"]


# --- a run ----------------------------------------------------------------------

def test_run_writes_one_row_per_detection_with_exif_make_model(synced, tmp_path):
    names = ["IMG_0001.JPG", "IMG_0002.jpg", "IMG_0003.JPEG"]
    d = folder(tmp_path, photos={n: jpeg(IN_WINDOW, "Browning", "BTC-7E") for n in names})
    st = run(synced, d)
    assert st["status"] == "done" and st["total"] == 3 and st["done"] == 3 and st["unreadable"] == 0
    rows = results(synced)
    assert len(rows) == st["detections"] == expected_detections(names) > 0
    r = rows[0]
    assert r["site"] == "TON_CAM02" and r["method"] == "md" and r["captured_at"] == "2026-05-01T08:00:00"
    assert r["make"] == "Browning" and r["model"] == "BTC-7E" and r["calibration_image"] == "IMG_5304.JPG"
    assert {"species", "confidence", "distance_m", "q05_m", "q95_m", "match_score", "x1", "y1", "x2", "y2"} <= r.keys()
    assert r["q05_m"] <= r["distance_m"] <= r["q95_m"]
    assert isinstance(r["match_score"], int)  # per photo: homography inliers against the flag photo


def test_progress_reports_counts_and_time_estimate(synced, tmp_path, monkeypatch):
    gate = threading.Event()

    def slow(paths, calibration, method):
        for p in paths:
            gate.wait(5)
            yield from inference.fake([p], calibration, method)

    monkeypatch.setattr(api.inference, "backend", slow)
    d = folder(tmp_path, photos={f"IMG_{i}.JPG": jpeg(IN_WINDOW) for i in range(4)})
    synced.post("/api/run", json={"folder": str(d), "site": SITE, "flag": FLAG, "method": "md"})
    st = synced.get("/api/run").json()
    assert st["status"] == "running" and st["total"] == 4 and st["done"] == 0 and st["eta_s"] is None
    assert synced.post("/api/run", json={"folder": str(d), "site": SITE, "flag": FLAG, "method": "md"}).status_code == 409
    gate.set()
    for _ in range(200):
        st = synced.get("/api/run").json()
        if st["status"] == "done":
            break
        time.sleep(0.02)
    assert st["done"] == 4 and st["eta_s"] == 0 and st["elapsed_s"] >= 0


def test_rerun_replaces_prior_rows(synced, tmp_path):
    d = folder(tmp_path)
    run(synced, d)
    n = len(results(synced))
    run(synced, d)
    assert len(results(synced)) == n


def test_methods_keep_separate_rows(synced, tmp_path):
    d = folder(tmp_path)
    run(synced, d, method="md")
    run(synced, d, method="sam3")
    assert {r["method"] for r in results(synced)} == {"md", "sam3"}
    assert len(results(synced)) == 2 * expected_detections(["IMG_0005.JPG"])


def test_inference_crash_is_an_error_and_keeps_earlier_answers(synced, tmp_path, monkeypatch):
    d = folder(tmp_path)
    run(synced, d)
    before = results(synced)
    assert before

    def boom(paths, calibration, method):
        raise RuntimeError("CUDA out of memory")
        yield

    monkeypatch.setattr(api.inference, "backend", boom)
    st = run(synced, d, rerun=True)
    assert st["status"] == "error" and "CUDA out of memory" in st["error"]
    assert [r["distance_m"] for r in results(synced)] == [r["distance_m"] for r in before]  # rows replaced only once new ones exist


# --- no windows, no holds (ticket 15) ---------------------------------------------------

def test_photo_without_capture_date_is_measured_anyway(synced, tmp_path):
    st = run(synced, folder(tmp_path, photos={"IMG_0005.JPG": jpeg(date=None)}))
    assert st["status"] == "done" and st["detections"] == expected_detections(["IMG_0005.JPG"])
    assert results(synced)[0]["captured_at"] is None


def test_photo_older_than_the_flag_photo_is_measured_against_it_anyway(synced, tmp_path):
    st = run(synced, folder(tmp_path, photos={"IMG_0005.JPG": jpeg("2025:01:01 08:00:00")}))
    assert st["status"] == "done" and results(synced)[0]["calibration_image"] == FLAG


def test_corrupt_photo_is_skipped_and_counted_not_a_crashed_run(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0005.JPG": jpeg(IN_WINDOW)[:40], "IMG_0006.JPG": jpeg(IN_WINDOW)})
    st = run(synced, d)
    assert st["status"] == "done" and st["unreadable"] == 1 and st["done"] == 2
    assert st["detections"] == expected_detections(["IMG_0006.JPG"])


def test_the_chosen_flag_photo_is_used_even_when_a_newer_one_exists(cloud, synced, tmp_path):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "data": flag_photo_data(image="IMG_7000.JPG")})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    d = folder(tmp_path)
    run(synced, d, flag="IMG_5304.JPG")
    assert results(synced)[0]["calibration_image"] == "IMG_5304.JPG"
    st = run(synced, d, flag="IMG_7000.JPG")  # a different flag photo is a different answer: measured again, rows replaced
    assert st["skipped"] == 0 and results(synced)[0]["calibration_image"] == "IMG_7000.JPG"


def test_backend_gets_the_calibration_row_and_its_flag_photo(synced, tmp_path, monkeypatch):
    seen = {}

    def spy(paths, calibration, method):
        seen.update(calibration)
        yield from inference.fake(paths, calibration, method)

    monkeypatch.setattr(api.inference, "backend", spy)
    run(synced, folder(tmp_path))
    assert seen["site"] == "TON_CAM02" and seen["image_name"] == "IMG_5304.JPG"
    assert Path(seen["ref_path"]).read_bytes()[:2] == b"\xff\xd8"  # the cached flag photo
    import json
    assert json.loads(seen["model"])  # the fitted ModelB


def test_relative_folder_path_keys_the_same_photo(synced, tmp_path, monkeypatch):
    d = folder(tmp_path)
    run(synced, d)
    monkeypatch.chdir(tmp_path)
    run(synced, Path("photos/TON_CAM02"))
    assert len({r["path"] for r in results(synced)}) == 1 and Path(results(synced)[0]["path"]).is_absolute()


def test_run_without_a_method_uses_the_default(synced, tmp_path):
    run(synced, folder(tmp_path), method=None)
    assert {r["method"] for r in results(synced)} == {inference.DEFAULT_METHOD}


def test_each_methods_rows_keep_the_alignment_score_they_were_read_under(synced, tmp_path, monkeypatch):
    def realign(paths, calibration, method):  # RoMa samples matches: every run aligns a little differently
        for res in inference.fake(paths, calibration, method):
            yield inference.PhotoResult(res.detections, {"md": 300, "sam3": 120}[method])

    monkeypatch.setattr(api.inference, "backend", realign)
    d = folder(tmp_path)
    run(synced, d, method="md")
    run(synced, d, method="sam3")
    assert {r["method"]: r["match_score"] for r in results(synced)} == {"md": 300, "sam3": 120}


# --- cancel, resume, rerun (ticket 10) -------------------------------------------------

def gated_backend(gate: threading.Semaphore, seen: list):
    """A backend that needs one gate release per photo and records which photos it was asked for."""
    def slow(paths, calibration, method):
        seen.extend(paths)
        for p in paths:
            assert gate.acquire(timeout=5), "test never released the gate"
            yield from inference.fake([p], calibration, method)
    return slow


def test_cancel_stops_between_photos_and_the_next_run_picks_up_the_rest(synced, tmp_path, monkeypatch):
    gate, seen = threading.Semaphore(0), []
    monkeypatch.setattr(api.inference, "backend", gated_backend(gate, seen))
    names = [f"IMG_{i}.JPG" for i in range(4)]
    d = folder(tmp_path, photos={n: jpeg(IN_WINDOW) for n in names})
    synced.post("/api/run", json={"folder": str(d), "site": SITE, "flag": FLAG, "method": "md"})
    gate.release()
    for _ in range(200):  # cancel once the first photo is in
        if synced.get("/api/run").json()["done"] >= 1:
            break
        time.sleep(0.01)
    assert synced.post("/api/run/cancel").status_code == 200
    gate.release(3)
    st = wait(synced)
    assert st["status"] == "cancelled" and 1 <= st["done"] < 4
    finished = st["done"]
    seen.clear()
    st = run(synced, d)  # the same button again: only what is left
    assert st["status"] == "done" and st["skipped"] == finished and st["done"] == 4
    assert len(seen) == 4 - finished and len(results(synced)) == expected_detections(names)


def test_crash_midway_keeps_finished_photos_and_the_next_run_measures_only_the_rest(synced, tmp_path, monkeypatch):
    names = [f"IMG_{i}.JPG" for i in range(3)]
    d = folder(tmp_path, photos={n: jpeg(IN_WINDOW) for n in names})
    seen = []

    def dies_after_one(paths, calibration, method):
        seen.extend(paths)
        yield from inference.fake(paths[:1], calibration, method)
        raise RuntimeError("CUDA error: device-side assert")  # or the power went out

    monkeypatch.setattr(api.inference, "backend", dies_after_one)
    assert run(synced, d)["status"] == "error"
    assert synced.get("/api/summary").json()["photos"] == 1  # exactly the finished photo is on record
    monkeypatch.setattr(api.inference, "backend", inference.fake)
    seen.clear()
    st = run(synced, d)
    assert st["status"] == "done" and st["skipped"] == 1 and len(results(synced)) == expected_detections(names)


def test_new_photos_in_a_folder_are_measured_without_redoing_old_ones_unless_rerun(synced, tmp_path, monkeypatch):
    spy, seen = spying()
    monkeypatch.setattr(api.inference, "backend", spy)
    d = folder(tmp_path)
    run(synced, d)
    (d / "IMG_0006.JPG").write_bytes(jpeg(IN_WINDOW))  # next SD-card dump into the same folder
    seen.clear()
    st = run(synced, d)
    assert [p.name for p in seen] == ["IMG_0006.JPG"] and st["skipped"] == 1
    seen.clear()
    run(synced, d, rerun=True)
    assert sorted(p.name for p in seen) == ["IMG_0005.JPG", "IMG_0006.JPG"]


def test_relabeled_flag_photo_remeasures_its_photos_on_the_next_run(cloud, synced, tmp_path, monkeypatch):
    spy, seen = spying()
    monkeypatch.setattr(api.inference, "backend", spy)
    d = folder(tmp_path)
    run(synced, d)
    assert run(synced, d)["skipped"] == 1
    cloud["annotations"] = [{**ANN, "updated_at": "2026-08-01T00:00:00+00:00"}]  # relabeled in FlagLabel: new geometry
    synced.post("/api/sync")
    seen.clear()
    st = run(synced, d)
    assert st["skipped"] == 0 and [p.name for p in seen] == ["IMG_0005.JPG"]
