"""Post-run summary, suspicious gallery and the gated CSV export — the rules a technician relies on,
asserted through the API over a scripted inference backend."""

import csv

import pytest

from camtrap_measure import api, distance, inference, report

from tests.conftest import jpeg
from tests.test_measure import folder, run

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
}


@pytest.fixture
def measured(synced, tmp_path, monkeypatch):
    def scripted(paths, calibration, method):
        for p in paths:
            dets, score = SCRIPT[p.name]
            yield inference.PhotoResult(dets, score)

    monkeypatch.setattr(api.inference, "backend", scripted)
    photos = {n: jpeg(f"2026:05:{i + 1:02d} 08:00:00") for i, n in enumerate(SCRIPT)}
    photos["IMG_0007.JPG"] = jpeg(None)  # no capture date → held
    st = run(synced, folder(tmp_path, photos=photos))
    assert st["status"] == "done" and st["held"] == 1
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
    assert s["photos"] == 8 and s["held"] == 1 and s["detections"] == 7 and s["deer"] == 5
    assert s["suspicious"] == 3  # the weak box, the unsure animal, the misfiled photo's deer; the raccoon is filtered, not suspicious
    bins = {(b["lo"], b["hi"]): b["n"] for b in s["histogram"]}  # deer rows only: the survey target
    assert bins[(4, 6)] == 1 and bins[(6, 8)] == 2 and bins[(12, 14)] == 1 and sum(bins.values()) == 5
    [cam] = s["cameras"]
    assert cam["site"] == "TON_CAM02" and cam["photos"] == 8 and cam["held"] == 1 and cam["deer"] == 5
    assert cam["median_m"] == 7.0 and cam["suspicious"] == 3


def test_summary_filters_by_site_and_date(measured):
    assert measured.get("/api/summary", params={"site": "TON_CAM99"}).json()["photos"] == 0
    s = measured.get("/api/summary", params={"date_from": "2026-05-02", "date_to": "2026-05-03"}).json()
    assert s["photos"] == 3 and s["held"] == 1 and s["detections"] == 3  # the undated held photo is in every range
    assert measured.get("/api/summary", params={"date_from": "May 2nd"}).status_code == 422


def test_summary_suspicious_count_matches_what_the_export_leaves_out(measured):
    for all_species in (False, True):
        n = measured.get("/api/summary", params={"all_species": all_species}).json()["suspicious"]
        doc, _ = export(measured, all_species=all_species)
        assert f"{n} suspicious rows excluded" in doc[0]
    assert measured.get("/api/summary", params={"all_species": True}).json()["suspicious"] == 4  # + the weak raccoon


# --- suspicious gallery -----------------------------------------------------------------

def test_gallery_shows_only_suspicious_photos_each_with_its_reason(measured):
    g = measured.get("/api/suspicious").json()
    by = {x["photo"]: x for x in g}
    assert set(by) == {"IMG_0002.JPG", "IMG_0003.JPG", "IMG_0005.JPG", "IMG_0007.JPG", "IMG_0008.JPG"}
    assert "confidence" in by["IMG_0002.JPG"]["reasons"][0] and "0.30" in by["IMG_0002.JPG"]["reasons"][0]
    assert any("unsure" in r for r in by["IMG_0003.JPG"]["reasons"])
    assert any("flag photo" in r and "9" in r for r in by["IMG_0005.JPG"]["reasons"])
    assert by["IMG_0007.JPG"]["held"] and "capture date" in by["IMG_0007.JPG"]["reasons"][0]
    assert by["IMG_0003.JPG"]["detections"][0]["species"] == "unsure"  # boxes come along for the overlay
    g = measured.get("/api/suspicious", params={"date_from": "2026-05-04"}).json()
    assert {x["photo"] for x in g} == {"IMG_0005.JPG", "IMG_0007.JPG", "IMG_0008.JPG"}  # undated held photo never drops out


def test_photo_endpoint_serves_measured_photos_only(measured, tmp_path):
    path = measured.get("/api/suspicious").json()[0]["path"]
    r = measured.get("/api/photo", params={"path": path})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert measured.get("/api/photo", params={"path": str(tmp_path / "elsewhere.JPG")}).status_code == 404


# --- export -----------------------------------------------------------------------------

def test_export_defaults_to_deer_rows_without_suspicious_ones_and_documents_itself(measured):
    doc, rows = export(measured)
    assert [r["photo"] for r in rows] == ["IMG_0001.JPG", "IMG_0003.JPG"]  # clean deer; the sure deer beside the unsure one
    assert rows[0]["camera"] == "TON_CAM02" and rows[0]["timestamp"] == "2026-05-01T08:00:00"
    assert rows[0]["distance_m"] == "5.0" and rows[0]["q05_m"] == "4.25" and rows[0]["q95_m"] == "6.0"
    assert rows[0]["method"] == "md" and rows[0]["flag"] == ""
    assert set(rows[0]) == {"photo", "camera", "timestamp", "species", "distance_m", "q05_m", "q95_m", "confidence",
                            "method", "match_score", "flag"}
    text = "\n".join(doc)
    assert "3 suspicious rows excluded" in text and "metres" in text and "90%" in text
    for col in ("distance_m", "q05_m", "q95_m", "confidence", "method", "flag", "timestamp"):
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
    assert [r["species"] for r in rows] == ["white-tailed deer", "white-tailed deer", "raccoon"]  # the weak raccoon is still gated


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
