"""Clearing measurements: one photo, or one camera's worth.

A re-measure replaces an answer, but nothing could take one away — so a wrong flag photo, a bad
calibration or a folder measured under the wrong camera left numbers on record with no way to remove
them except editing the database by hand (researcher, 2026-08-25).

What must never go with them: the photos on disk, and anything synced from FlagLabel. Cameras,
annotations, calibrations and the cached flag photos are not this app's to delete, and re-measuring
needs every one of them.
"""

import pytest

from camtrap_measure import api, store

from tests.test_measure import folder, jpeg, results, run  # noqa: F401

IN_WINDOW = "2026:05:01 08:00:00"


def measured(client, tmp_path, names=("IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG")):
    d = folder(tmp_path, photos={n: jpeg(IN_WINDOW) for n in names})
    assert run(client, d)["status"] == "done"
    return d


def test_clearing_one_photo_leaves_the_others(synced, tmp_path):
    measured(synced, tmp_path)
    before = results(synced)
    victim = before[0]["path"]

    r = synced.post("/api/results/clear", params={"path": victim})
    assert r.status_code == 200 and r.json()["photos"] == 1

    after = results(synced)
    assert victim not in {row["path"] for row in after}
    assert {row["path"] for row in after} == {row["path"] for row in before} - {victim}


def test_clearing_a_camera_clears_every_photo_measured_under_it(synced, tmp_path):
    measured(synced, tmp_path)
    site = results(synced)[0]["site"]

    r = synced.post("/api/results/clear", params={"site": site})
    assert r.status_code == 200 and r.json()["photos"] == 3 and r.json()["detections"] > 0
    assert results(synced) == []
    assert synced.get("/api/summary").json()["photos"] == 0


def test_a_cleared_photo_is_measured_again_rather_than_skipped(synced, tmp_path):
    """The point of clearing: the next run does the work again instead of reporting it already done."""
    d = measured(synced, tmp_path)
    before = results(synced)
    assert run(synced, d)["skipped"] == 3  # all current, nothing to do

    synced.post("/api/results/clear", params={"path": results(synced)[0]["path"]})
    again = run(synced, d)
    assert again["skipped"] == 2 and again["status"] == "done"
    assert len(results(synced)) == len(before)  # measured afresh, and back on record


def test_the_photos_and_everything_synced_survive(synced, tmp_path):
    """Only the app's own answers go."""
    d = measured(synced, tmp_path)
    site = results(synced)[0]["site"]
    cameras_before = synced.get("/api/cameras").json()
    flag = cameras_before[0]["flags"][0]["image_name"]

    synced.post("/api/results/clear", params={"site": site})

    assert sorted(p.name for p in d.iterdir()) == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"]
    assert synced.get("/api/cameras").json() == cameras_before          # cameras and their flag photos
    assert store.calibrations()                                          # the fits the measurement needs
    assert synced.get("/api/flag", params={"site": site, "image": flag}).status_code == 200  # cached flag photo


def test_clearing_needs_to_be_told_which(synced):
    """Neither would empty the whole store, which no button asks for; both is a contradiction."""
    assert synced.post("/api/results/clear").status_code == 400
    assert synced.post("/api/results/clear", params={"site": "A", "path": "B"}).status_code == 400
    with pytest.raises(ValueError):
        store.clear_measurements()


def test_clearing_nothing_is_not_an_error(synced):
    """A camera with no measurements yet: the button says "0", it does not fail."""
    r = synced.post("/api/results/clear", params={"site": "TON_CAM02"})
    assert r.status_code == 200 and r.json() == {"photos": 0, "detections": 0}


def test_a_run_in_progress_refuses_to_have_its_answers_pulled_out(synced, tmp_path, monkeypatch):
    """Deleting rows a running job is still writing is a race with the store as the loser."""
    monkeypatch.setattr(api.measure, "current", {"status": "running"})
    r = synced.post("/api/results/clear", params={"site": "TON_CAM02"})
    assert r.status_code == 409 and "run is in progress" in r.json()["detail"]


# --- the flag photo the window shows -------------------------------------------------------------

def test_the_folder_listing_says_which_camera_each_flag_photo_belongs_to(synced, tmp_path):
    """The window shows the flag photo a number was read against. It knows the flag's *name* from the
    photo's own record, but was taking the *camera* from whichever one is selected in the dropdown —
    so choosing another camera asked for one camera's flag under another camera's name, which is a 404
    and a blank frame (reported 2026-08-25). The pair has to travel together."""
    d = measured(synced, tmp_path)
    listing = synced.get("/api/folder", params={"path": str(d), "site": "TON_CAM02",
                                                "flag": "IMG_5304.JPG", "method": "md"}).json()
    rows = [r for r in listing["rows"] if r["measured"]]
    assert rows, "nothing measured to check"
    for r in rows:
        assert r["flag_site"] and r["flag_image"]
        # the pair the window will ask for must be one the engine will actually serve
        assert synced.get("/api/flag", params={"site": r["flag_site"], "image": r["flag_image"]}).status_code == 200

    unmeasured = [r for r in listing["rows"] if not r["measured"]]
    assert all(r["flag_site"] is None for r in unmeasured)  # nothing measured it, so no pair to report
