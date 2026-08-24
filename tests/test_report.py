"""Post-run summary, the folder listing and the gated CSV export — the rules a technician relies on,
asserted through the API over a scripted inference backend."""

import csv
from pathlib import Path

import pytest

from camtrap_measure import api, distance, inference, report

from tests.conftest import ANN, flag_photo_data, jpeg
from tests.test_measure import FLAG, SITE, folder, run

D = inference.Detection


def det(species="white-tailed deer", conf=0.9, d=5.0, x=0.2):
    return D(x, 0.3, x + 0.2, 0.7, species, conf, d, d * 0.85 if d else None, d * 1.2 if d else None)


# photo → (detections, match_score): a clean deer, a weak box, an unsure species, a raccoon, a misfiled photo, an empty frame,
# a weak raccoon. Scripted at the inference boundary like the shipped fake, but with every rule's case by construction.
SCRIPT = {
    "IMG_0001.JPG": ([det()], 300),
    "IMG_0002.JPG": ([det(conf=0.3, d=9.0)], 300),
    "IMG_0003.JPG": ([det(species="unsure", d=12.0), det(d=6.0, x=0.6)], 300),
    "IMG_0004.JPG": ([det(species="raccoon", d=3.0)], 300),
    "IMG_0005.JPG": ([det(d=7.0)], 9),
    "IMG_0006.JPG": ([], None),
    "IMG_0008.JPG": ([det(species="raccoon", conf=0.2, d=4.0)], 300),
    "IMG_0007.JPG": ([det(species="raccoon", d=7.0)], 300),  # no capture date: measured like any other (ticket 15), in every date range
}


@pytest.fixture
def measured(synced, tmp_path, monkeypatch):
    def scripted(paths, calibration, method, **_):
        for p in paths:
            dets, score = SCRIPT[p.name]
            yield inference.PhotoResult(dets, score, p)

    monkeypatch.setattr(api.inference, "backend", scripted)
    photos = {n: jpeg(f"2026:05:{i + 1:02d} 08:00:00") for i, n in enumerate(SCRIPT) if n != "IMG_0007.JPG"}
    photos["IMG_0007.JPG"] = jpeg(None)
    st = run(synced, folder(tmp_path, photos=photos))
    assert st["status"] == "done" and st["unreadable"] == 0
    return synced


def export(c, **params):
    r = c.get("/api/export.csv", params=params)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), r.text
    doc = [l for l in r.text.splitlines() if l.startswith("#")]
    rows = list(csv.DictReader(l for l in r.text.splitlines() if not l.startswith("#")))
    return doc, rows


# --- summary -------------------------------------------------------------------------

def test_summary_counts_histogram_and_per_camera_stats(measured):
    s = measured.get("/api/summary").json()
    assert s["photos"] == 8 and s["held"] == 0 and s["detections"] == 8 and s["deer"] == 5
    assert s["suspicious"] == 3  # the weak box, the unsure animal, the misfiled photo's deer; the raccoon is filtered, not suspicious
    bins = {(b["lo"], b["hi"]): b["n"] for b in s["histogram"]}  # deer rows only: the survey target
    assert bins[(4, 6)] == 1 and bins[(6, 8)] == 2 and bins[(12, 14)] == 1 and sum(bins.values()) == 5
    [cam] = s["cameras"]
    assert cam["site"] == "TON_CAM02" and cam["photos"] == 8 and cam["held"] == 0 and cam["deer"] == 5
    assert cam["median_m"] == 7.0 and cam["suspicious"] == 3


def test_summary_filters_by_site_and_date(measured):
    assert measured.get("/api/summary", params={"site": "TON_CAM99"}).json()["photos"] == 0
    s = measured.get("/api/summary", params={"date_from": "2026-05-02", "date_to": "2026-05-03"}).json()
    assert s["photos"] == 3 and s["detections"] == 4  # the undated photo is in every range
    assert measured.get("/api/summary", params={"date_from": "May 2nd"}).status_code == 422


def test_summary_and_export_narrow_to_the_chosen_folder(measured, tmp_path):
    """RESULTS answers for the folder in the bar. Without this a freshly opened window showed the last run's
    numbers over photos nobody had chosen (reported 2026-08-23)."""
    d = tmp_path / "photos" / "TON_CAM02"
    s = measured.get("/api/summary", params={"folder": str(d)}).json()
    assert s["photos"] == 8 and s["detections"] == 8 and s["deer"] == 5

    elsewhere = measured.get("/api/summary", params={"folder": str(tmp_path / "photos" / "TON_CAM03")}).json()
    assert elsewhere["photos"] == 0 and elsewhere["detections"] == 0 and elsewhere["cameras"] == []
    # the folder itself, never what lies under it: a run reads the JPEGs of one folder only
    assert measured.get("/api/summary", params={"folder": str(tmp_path / "photos")}).json()["photos"] == 0

    doc, rows = export(measured, folder=str(d))
    assert f"folder={d}" in doc[0] and len(rows) == 2  # the five deer less the three suspicious
    _, none = export(measured, folder=str(tmp_path / "photos" / "TON_CAM03"))
    assert none == []


def test_summary_suspicious_count_matches_what_the_export_leaves_out(measured):
    for all_species in (False, True):
        n = measured.get("/api/summary", params={"all_species": all_species}).json()["suspicious"]
        doc, _ = export(measured, all_species=all_species)
        assert f"{n} suspicious rows excluded" in doc[0]
    assert measured.get("/api/summary", params={"all_species": True}).json()["suspicious"] == 4  # + the weak raccoon


# --- the folder listing ------------------------------------------------------------------

def listing(c, d, method="md", site=SITE, flag=FLAG) -> dict:
    r = c.get("/api/folder", params={"path": str(d), "site": site, "flag": flag, "method": method})
    assert r.status_code == 200, r.text
    return r.json()


def test_folder_lists_every_photo_with_its_boxes_and_numbers(measured, tmp_path):
    g = listing(measured, tmp_path / "photos" / "TON_CAM02")
    by = {x["name"]: x for x in g["rows"]}
    assert set(by) == set(SCRIPT)  # every photo, not only the suspicious ones: the researcher checks the answers
    assert [x["name"] for x in g["rows"]] == sorted(SCRIPT)  # name order, as the folder itself shows them
    assert g["total"] == 8 and g["unreadable"] == 0
    one = by["IMG_0001.JPG"]
    assert one["measured"] and not one["stale"] and one["flag_image"] == FLAG and one["match_score"] == 300
    assert one["method"] == "md" and one["captured_at"] == "2026-05-01T08:00:00"
    [d] = one["detections"]
    assert d["species"] == "white-tailed deer" and d["distance_m"] == 5.0
    assert (d["q05_m"], d["q95_m"]) == (pytest.approx(4.25), pytest.approx(6.0)) and d["reasons"] == []
    assert (d["x1"], d["y1"], d["x2"], d["y2"]) == (0.2, 0.3, 0.4, 0.7)  # the overlay's box
    assert by["IMG_0006.JPG"]["detections"] == [] and by["IMG_0006.JPG"]["reasons"] == []  # an empty frame is still a row


def test_folder_marks_the_suspicious_photos_and_their_boxes(measured, tmp_path):
    by = {x["name"]: x for x in listing(measured, tmp_path / "photos" / "TON_CAM02")["rows"]}
    assert {n for n, x in by.items() if x["reasons"]} == {"IMG_0002.JPG", "IMG_0003.JPG", "IMG_0005.JPG", "IMG_0008.JPG"}
    assert "confidence" in by["IMG_0002.JPG"]["reasons"][0] and "0.30" in by["IMG_0002.JPG"]["reasons"][0]
    assert any("unsure" in r for r in by["IMG_0003.JPG"]["reasons"])
    assert any("flag photo" in r and "9" in r for r in by["IMG_0005.JPG"]["reasons"])
    unsure, sure = by["IMG_0003.JPG"]["detections"]  # the reason sits on the box it belongs to, not only on the photo
    assert unsure["species"] == "unsure" and any("unsure" in r for r in unsure["reasons"]) and sure["reasons"] == []


def test_folder_lists_the_photos_before_anything_has_been_measured(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0002.JPG": jpeg("2026:05:02 08:00:00"), "IMG_0001.JPG": jpeg(None)})
    g = listing(synced, d)
    assert g["folder"] == str(d) and g["total"] == 2 and g["unreadable"] == 0
    first, second = g["rows"]
    assert [first["name"], second["name"]] == ["IMG_0001.JPG", "IMG_0002.JPG"]
    assert first["path"] == str(d / "IMG_0001.JPG") and first["captured_at"] is None  # EXIF, read without measuring
    assert second["captured_at"] == "2026-05-02T08:00:00"
    for x in (first, second):
        assert x["measured"] is False and x["stale"] is False and x["detections"] == [] and x["reasons"] == []
        assert x["match_score"] is None and x["method"] is None and x["flag_image"] is None


def test_folder_reads_a_photo_measured_with_the_other_method_as_unmeasured(measured, tmp_path):
    """The window must never say 'no animal' about a photo it has not looked at under the method on screen."""
    by = {x["name"]: x for x in listing(measured, tmp_path / "photos" / "TON_CAM02", method="sam3")["rows"]}
    one = by["IMG_0001.JPG"]  # measured, but with md
    assert one["measured"] is False and one["stale"] is False and one["detections"] == [] and one["reasons"] == []
    assert one["method"] is None and one["match_score"] is None and one["flag_image"] is None
    assert one["captured_at"] == "2026-05-01T08:00:00"  # still a photo in the folder, listed like any other


def test_folder_counts_the_files_it_cannot_read_and_still_lists_them(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg()[:40], "IMG_0002.JPG": jpeg()})
    g = listing(synced, d)
    assert g["total"] == 2 and g["unreadable"] == 1  # a truncated file must not hide the rest of the folder
    broken, fine = g["rows"]
    assert broken["name"] == "IMG_0001.JPG" and "could not be read" in broken["reasons"][0]
    assert fine["reasons"] == []


def test_folder_calls_an_answer_read_against_another_flag_photo_stale(cloud, synced, tmp_path):
    cloud["annotations"].append({**ANN, "image_name": "IMG_7000.JPG", "storage_path": "TON_CAM02/IMG_7000.JPG",
                                 "data": flag_photo_data(image="IMG_7000.JPG")})
    cloud["photos"]["TON_CAM02/IMG_7000.JPG"] = jpeg()
    synced.post("/api/sync")
    d = folder(tmp_path)
    run(synced, d, flag=FLAG)
    assert [x["stale"] for x in listing(synced, d, flag=FLAG)["rows"]] == [False]
    [other] = listing(synced, d, flag="IMG_7000.JPG")["rows"]  # the other flag photo is another answer
    assert other["measured"] is True and other["stale"] is True and other["flag_image"] == FLAG


def test_folder_calls_an_answer_from_before_a_relabel_stale(cloud, synced, tmp_path):
    d = folder(tmp_path)
    run(synced, d)
    cloud["annotations"] = [{**ANN, "updated_at": "2026-08-01T00:00:00+00:00"}]  # relabeled in FlagLabel: new geometry
    synced.post("/api/sync")
    assert [x["stale"] for x in listing(synced, d)["rows"]] == [True]
    run(synced, d)  # measuring the folder again is exactly what clears it
    assert [x["stale"] for x in listing(synced, d)["rows"]] == [False]


def test_folder_that_is_not_there_is_refused_in_plain_words(synced, tmp_path):
    r = synced.get("/api/folder", params={"path": str(tmp_path / "nope"), "site": SITE, "flag": FLAG})
    assert r.status_code == 400 and "not found" in r.json()["detail"]


def test_folder_that_cannot_be_read_is_refused_in_plain_words(synced, tmp_path, monkeypatch):
    d = folder(tmp_path)

    def denied(self):  # the share dropped, or this Windows account may not read the folder
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "iterdir", denied)
    r = synced.get("/api/folder", params={"path": str(d), "site": SITE, "flag": FLAG})
    assert r.status_code == 400 and "Could not read" in r.json()["detail"] and "Access is denied" in r.json()["detail"]


def test_photo_endpoint_serves_measured_photos(measured, tmp_path):
    path = listing(measured, tmp_path / "photos" / "TON_CAM02")["rows"][0]["path"]
    for size in ("thumb", "full"):
        r = measured.get("/api/photo", params={"path": path, "size": size})
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert measured.get("/api/photo", params={"path": str(tmp_path / "elsewhere.JPG")}).status_code == 404


def test_photo_endpoint_serves_a_photo_of_a_listed_folder_before_it_is_measured(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg()})
    p = str(d / "IMG_0001.JPG")
    assert synced.get("/api/photo", params={"path": p}).status_code == 404  # no folder listed yet
    listing(synced, d)
    r = synced.get("/api/photo", params={"path": p, "size": "thumb"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_photo_endpoint_refuses_a_file_that_is_merely_near_a_listed_folder(synced, tmp_path):
    d = folder(tmp_path, photos={"IMG_0001.JPG": jpeg(), "notes.txt": b"x"})
    (d / "sub").mkdir()
    (d / "sub" / "IMG_0001.JPG").write_bytes(jpeg())
    listing(synced, d)
    for path in (d / "sub" / "IMG_0001.JPG", d / "notes.txt", d.parent / "IMG_0001.JPG"):
        assert synced.get("/api/photo", params={"path": str(path)}).status_code == 404, path


def test_flag_endpoint_serves_synced_flag_photos_only(measured):
    r = measured.get("/api/flag", params={"site": "TON_CAM02", "image": FLAG})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert measured.get("/api/flag", params={"site": "TON_CAM02", "image": "nope.JPG"}).status_code == 404


# --- export -----------------------------------------------------------------------------

def test_export_defaults_to_deer_rows_without_suspicious_ones_and_documents_itself(measured):
    doc, rows = export(measured)
    assert [r["photo"] for r in rows] == ["IMG_0001.JPG", "IMG_0003.JPG"]  # clean deer; the sure deer beside the unsure one
    assert rows[0]["camera"] == "TON_CAM02" and rows[0]["timestamp"] == "2026-05-01T08:00:00"
    assert rows[0]["distance_m"] == "5.0" and rows[0]["q05_m"] == "4.25" and rows[0]["q95_m"] == "6.0"
    assert rows[0]["method"] == "md" and rows[0]["flag"] == ""
    assert set(rows[0]) == {"photo", "camera", "timestamp", "species", "distance_m", "q05_m", "q95_m", "confidence",
                            "method", "fidelity", "match_score", "flag"}  # fidelity: which settings made the number
    text = "\n".join(doc)
    assert "3 suspicious rows excluded" in text and "metres" in text and "90%" in text
    for col in ("distance_m", "q05_m", "q95_m", "confidence", "method", "fidelity", "flag", "timestamp"):
        assert col in text


def test_export_checkbox_includes_suspicious_rows_with_their_reason_in_the_flag_column(measured):
    doc, rows = export(measured, include_suspicious=True)
    assert [r["photo"] for r in rows] == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG", "IMG_0003.JPG", "IMG_0005.JPG"]
    flags = {(r["photo"], r["species"]): r["flag"] for r in rows}
    assert "confidence" in flags[("IMG_0002.JPG", "white-tailed deer")]
    assert "unsure" in flags[("IMG_0003.JPG", "unsure")]
    assert "flag photo" in flags[("IMG_0005.JPG", "white-tailed deer")]
    assert "suspicious rows included" in "\n".join(doc)


def test_export_all_species_toggle_adds_the_raccoon(measured):
    _, rows = export(measured, all_species=True)
    assert [r["species"] for r in rows] == ["raccoon", "white-tailed deer", "white-tailed deer", "raccoon"]  # undated photo first; the weak raccoon is still gated


def test_export_names_every_method_present_so_doubled_animals_are_not_a_surprise(measured, tmp_path):
    run(measured, tmp_path / "photos" / "TON_CAM02", method="sam3")
    doc, rows = export(measured)
    assert len(rows) == 4 and {r["method"] for r in rows} == {"md", "sam3"}
    assert any("methods present: md, sam3" in l and "one row per animal per method" in l for l in doc)


def test_export_filters_site_and_date_range(measured):
    _, rows = export(measured, site="TON_CAM02", date_from="2026-05-03", date_to="2026-05-03", include_suspicious=True)
    assert {r["photo"] for r in rows} == {"IMG_0003.JPG"}
    assert export(measured, site="TON_CAM99")[1] == []
    doc, _ = export(measured, site="TON_CAM02", date_from="2026-05-03")
    assert "site=TON_CAM02" in doc[0] and "from=2026-05-03" in doc[0]


def test_suspicious_thresholds_are_named_in_the_reasons():
    row = {"match_score": 9, "confidence": 0.3, "species": "unsure", "distance_m": 5.0}
    text = " ".join(report.reasons(row))
    assert str(distance.MIN_INLIERS) in text and str(report.LOW_CONF) in text
    assert report.reasons({"match_score": 300, "confidence": 0.9, "species": "white-tailed deer", "distance_m": 5.0}) == []
    assert "ground" in report.reasons({"match_score": 300, "confidence": 0.9, "species": "white-tailed deer", "distance_m": None})[0]
