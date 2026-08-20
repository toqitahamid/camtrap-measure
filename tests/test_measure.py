"""Measurement runs through the API, with inference faked at its boundary and Supabase faked at its seam."""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from camtrap_measure import api, inference

from tests.conftest import ANN, flag_photo_data, jpeg

IN_WINDOW = "2026:05:01 08:00:00"  # after the March flag photo


def folder(tmp_path: Path, site="TON_CAM02", photos: dict[str, bytes] | None = None) -> Path:
    d = tmp_path / "photos" / site
    d.mkdir(parents=True)
    for name, data in (photos or {"IMG_0005.JPG": jpeg(IN_WINDOW, "Browning", "BTC-7E")}).items():
        (d / name).write_bytes(data)
    return d


def run(c: TestClient, d: Path, method: str | None = "md", timeout=4.0, rerun=False) -> dict:
    """Start a run (method=None: let the API pick its default) and poll until it ends."""
    r = c.post("/api/run", json={"folder": str(d), "rerun": rerun, **({"method": method} if method else {})})
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

def test_folder_named_after_unknown_camera_is_refused(synced, tmp_path):
    d = folder(tmp_path, site="TON_CAM99")
    r = synced.post("/api/run", json={"folder": str(d), "method": "md"})
    assert r.status_code == 400
    assert "TON_CAM99" in r.json()["detail"] and "not a registered camera" in r.json()["detail"]


def test_missing_folder_is_refused(synced, tmp_path):
    r = synced.post("/api/run", json={"folder": str(tmp_path / "nope" / "TON_CAM02"), "method": "md"})
    assert r.status_code == 400 and "not found" in r.json()["detail"]


def test_folder_without_jpegs_is_refused(synced, tmp_path):
    d = folder(tmp_path, photos={"notes.txt": b"x"})
    r = synced.post("/api/run", json={"folder": str(d), "method": "md"})
    assert r.status_code == 400 and "no jpeg" in r.json()["detail"].lower()


def test_before_first_sync_asks_for_sync(client, tmp_path):
    r = client.post("/api/run", json={"folder": str(folder(tmp_path)), "method": "md"})
    assert r.status_code == 400 and "Sync" in r.json()["detail"]


# --- a run ----------------------------------------------------------------------

def test_run_writes_one_row_per_detection_with_exif_make_model(synced, tmp_path):
    names = ["IMG_0001.JPG", "IMG_0002.jpg", "IMG_0003.JPEG"]
    d = folder(tmp_path, photos={n: jpeg(IN_WINDOW, "Browning", "BTC-7E") for n in names})
    st = run(synced, d)
    assert st["status"] == "done" and st["total"] == 3 and st["done"] == 3 and st["held"] == 0
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
    synced.post("/api/run", json={"folder": str(d), "method": "md"})
    st = synced.get("/api/run").json()
    assert st["status"] == "running" and st["total"] == 4 and st["done"] == 0 and st["eta_s"] is None
    assert synced.post("/api/run", json={"folder": str(d), "method": "md"}).status_code == 409
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


# --- calibration windows and holds ------------------------------------------------

def test_photo_before_any_flag_photo_is_held_and_banner_names_the_gap(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg("2026:01:15 08:00:00")})
    st = run(synced, d)
    assert st["held"] == 1 and st["detections"] == 0 and results(synced) == []
    [banner] = st["held_reasons"]
    assert banner["count"] == 1
    assert "TON_CAM02" in banner["reason"] and "2026-01-15" in banner["reason"] and "FlagLabel" in banner["reason"]


def test_photo_without_capture_date_is_held(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg(None)})
    st = run(synced, d)
    assert st["held"] == 1 and "capture date" in st["held_reasons"][0]["reason"]


def test_red_calibration_holds_photos_and_banner_says_what_to_fix(cloud, synced, tmp_path):
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(n=4), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")
    d = folder(tmp_path, photos={f"IMG_{i}.JPG": jpeg(IN_WINDOW) for i in range(3)})
    st = run(synced, d)
    assert st["held"] == 3 and results(synced) == []
    [banner] = st["held_reasons"]
    assert banner["count"] == 3 and "IMG_5304.JPG" in banner["reason"] and "label more flags" in banner["reason"]


def test_photo_matches_latest_window_at_or_before_its_timestamp(cloud, synced, tmp_path):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "data": flag_photo_data(image="IMG_7000.JPG")})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg("2026:07:04 09:00:00")
    synced.post("/api/sync")
    d = folder(tmp_path, photos={"IMG_0005.JPG": jpeg("2026:05:01 08:00:00"),   # old geometry
                                 "IMG_0006.JPG": jpeg("2026:07:04 09:00:00"),   # exactly at the re-flag: new
                                 "IMG_0007.JPG": jpeg("2026:08:01 08:00:00")})  # new geometry
    st = run(synced, d)
    assert st["held"] == 0
    by_photo = {Path(r["path"]).name: r["calibration_image"] for r in results(synced)}
    assert by_photo == {"IMG_0005.JPG": "IMG_5304.JPG", "IMG_0006.JPG": "IMG_7000.JPG", "IMG_0007.JPG": "IMG_7000.JPG"}


def test_held_photo_loses_stale_rows_of_every_method_on_rerun(cloud, synced, tmp_path):
    d = folder(tmp_path)
    run(synced, d, method="md")
    run(synced, d, method="sam3")
    assert results(synced)
    cloud["annotations"] = [{**ANN, "data": flag_photo_data(n=4), "updated_at": "2026-07-01T00:00:00+00:00"}]
    synced.post("/api/sync")  # the flag photo got relabeled badly: its window is red now
    st = run(synced, d, method="md")
    assert st["held"] == 1 and results(synced) == []


def test_undated_flag_photo_holds_the_camera_like_its_verdict_does(cloud, synced, tmp_path):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "status": "empty", "data": None})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg(date=None)
    synced.post("/api/sync")
    assert {c["site"]: c["verdict"] for c in synced.get("/api/cameras").json()} == {"TON_CAM02": "red"}
    st = run(synced, folder(tmp_path))
    assert st["held"] == 1 and "IMG_7000.JPG" in st["held_reasons"][0]["reason"]


def test_corrupt_photo_is_held_not_a_crashed_run(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0005.JPG": jpeg(IN_WINDOW)[:40], "IMG_0006.JPG": jpeg(IN_WINDOW)})
    st = run(synced, d)
    assert st["status"] == "done" and st["held"] == 1 and st["detections"] == expected_detections(["IMG_0006.JPG"])


def test_photo_is_held_until_its_flag_photo_is_on_disk(synced, tmp_path):
    from camtrap_measure import store
    store.ref_path("TON_CAM02", "IMG_5304.JPG").unlink()
    st = run(synced, folder(tmp_path))
    assert st["held"] == 1 and results(synced) == []
    assert "IMG_5304.JPG" in st["held_reasons"][0]["reason"] and "Sync" in st["held_reasons"][0]["reason"]
    assert synced.post("/api/sync").json()["remeasure"] == 1  # refetches the missing flag photo, then measures the held photo
    wait(synced)
    assert results(synced)
    assert run(synced, folder(tmp_path / "again"))["held"] == 0


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
    synced.post("/api/run", json={"folder": str(d), "method": "md"})
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


# --- held photos are measured after the sync that calibrates them --------------------------

def test_sync_measures_held_photos_once_their_calibration_arrives(cloud, client, tmp_path):
    cloud["annotations"] = []  # camera registered, no flag photo labeled yet
    client.post("/api/login", json={"email": "tech@dept.gov", "password": "pw"})
    client.post("/api/sync")
    d = folder(tmp_path)
    st = run(client, d)
    assert st["held"] == 1 and results(client) == []
    cloud["annotations"] = [ANN]  # the flag photo gets labeled
    r = client.post("/api/sync").json()
    assert r["ok"] and r["remeasure"] == 1
    st = wait(client)
    assert st["status"] == "done" and st["held"] == 0 and st["done"] == 1 and st["method"] is None and st["site"] == ""
    assert len(results(client)) == expected_detections(["IMG_0005.JPG"])
    assert client.post("/api/sync").json()["remeasure"] == 0  # nothing left to catch up on


def test_photos_a_sync_can_never_fix_are_not_retried(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg(None), "IMG_0002.JPG": jpeg("2026:01:15 08:00:00")})
    assert run(synced, d)["held"] == 2  # no capture date; before any flag photo
    assert synced.post("/api/sync").json()["remeasure"] == 1  # only the dated one could be helped by a future flag photo


def test_sync_during_a_run_leaves_held_photos_for_the_next_sync(cloud, synced, tmp_path, monkeypatch):
    gate = threading.Semaphore(0)
    monkeypatch.setattr(api.inference, "backend", gated_backend(gate, []))
    synced.post("/api/run", json={"folder": str(folder(tmp_path)), "method": "md"})
    assert synced.post("/api/sync").json()["remeasure"] is None  # busy: not attempted, not an error
    gate.release()
