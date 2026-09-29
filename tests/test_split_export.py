"""The export as one file per site or per camera (ticket 26): the site a camera belongs to, the site column,
the files the split writes into a folder, and the screen's filters applied to each file."""

import csv
from pathlib import Path

import pytest

from camtrap_measure import api, dialogs, inference, report

from tests.conftest import ANN, flag_photo_data, jpeg
from tests.test_measure import folder, run

D = inference.Detection
DEER = D(0.2, 0.3, 0.4, 0.7, "white-tailed deer", 0.9, 5.0, 4.0, 6.0)
WEAK = D(0.2, 0.3, 0.4, 0.7, "white-tailed deer", 0.3, 8.0, 7.0, 9.0)  # low detector confidence: needs a look
COON = D(0.2, 0.3, 0.4, 0.7, "raccoon", 0.9, 3.0, 2.5, 3.5)
SCRIPT = {"IMG_A.JPG": [DEER], "IMG_B.JPG": [WEAK], "IMG_C.JPG": [COON]}

# camera -> {photo: capture date}. SRF_CAM08 saw only a raccoon, so a deer export has nothing for it.
CAMERAS = {
    "MAS_CAM01": {"IMG_A.JPG": "2026:05:01 08:00:00", "IMG_B.JPG": "2026:05:02 08:00:00"},
    "MAS_CAM02": {"IMG_A.JPG": "2026:05:03 08:00:00"},
    "TON_CAM02": {"IMG_A.JPG": "2026:05:01 08:00:00", "IMG_C.JPG": "2026:05:02 08:00:00"},
    "SRF_CAM08": {"IMG_C.JPG": "2026:05:01 08:00:00"},
}


@pytest.fixture
def measured(cloud, client, tmp_path, monkeypatch):
    """Four cameras on three sites, each synced with a flag photo and measured."""
    cloud["annotations"], cloud["sites"] = [], []
    for cam in CAMERAS:
        cloud["annotations"].append({**ANN, "site": cam, "storage_path": f"{cam}/IMG_5304.JPG",
                                     "data": flag_photo_data(site=cam)})
        cloud["photos"][f"{cam}/IMG_5304.JPG"] = jpeg()
        cloud["sites"].append({"name": cam})
    client.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    assert client.post("/api/sync").json()["ok"]

    def scripted(paths, calibration, method, **_):
        for p in paths:
            yield inference.PhotoResult(SCRIPT[p.name], 300, p)

    monkeypatch.setattr(api.inference, "backend", scripted)
    for cam, photos in CAMERAS.items():
        d = folder(tmp_path, site=cam, photos={n: jpeg(t) for n, t in photos.items()})
        assert run(client, d, site=cam, flag="IMG_5304.JPG")["status"] == "done"
    return client


def split(c, to: Path, by: str, **params) -> dict:
    r = c.post("/api/export/split", params={"to": str(to), "by": by, **params})
    assert r.status_code == 200, r.text
    return r.json()


def read(path: str) -> tuple[list[str], list[dict]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [l for l in lines if l.startswith("#")], list(csv.DictReader(l for l in lines if not l.startswith("#")))


def names(body: dict) -> list[str]:
    return [Path(p).name for p in body["paths"]]


def test_site_is_the_name_before_the_last_cam():
    assert report.site_of("MAS_CAM01") == "MAS"
    assert report.site_of("SHB_CAM14") == "SHB"
    assert report.site_of("OLD_CAMP_CAM02") == "OLD_CAMP"  # the last _CAM, not the first
    assert report.site_of("TRAILHEAD") == "TRAILHEAD"  # no _CAM: its own site
    assert report.site_of("") == ""


def test_export_has_a_site_column_documented_in_the_header(measured):
    r = measured.get("/api/export.csv")
    rows = list(csv.DictReader(l for l in r.text.splitlines() if not l.startswith("#")))
    assert list(rows[0])[:3] == ["photo", "camera", "site"]
    assert {(row["camera"], row["site"]) for row in rows} == {("MAS_CAM01", "MAS"), ("MAS_CAM02", "MAS"),
                                                              ("TON_CAM02", "TON")}
    assert "# site: the survey site" in r.text


def test_split_by_site_writes_one_file_per_site_with_rows(measured, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    body = split(measured, out, "site")
    assert body["count"] == 2 and body["folder"] == str(out.resolve())
    assert names(body) == ["camtrap-measure_MAS_start_end.csv", "camtrap-measure_TON_start_end.csv"]  # SRF: raccoon only
    doc, rows = read(body["paths"][0])
    assert {(r["camera"], r["photo"]) for r in rows} == {("MAS_CAM01", "IMG_A.JPG"), ("MAS_CAM02", "IMG_A.JPG")}
    assert {r["site"] for r in rows} == {"MAS"}
    assert "site=MAS" in doc[0] and "1 row that needs a look left out" in doc[0]  # the weak box on MAS_CAM01
    assert any(l.startswith("# distance_m:") for l in doc)  # the same column notes as the combined file
    _, rows = read(body["paths"][1])
    assert [r["camera"] for r in rows] == ["TON_CAM02"]


def test_split_by_camera_writes_one_file_per_camera_with_rows(measured, tmp_path):
    body = split(measured, tmp_path, "camera")
    assert names(body) == ["camtrap-measure_MAS_CAM01_start_end.csv", "camtrap-measure_MAS_CAM02_start_end.csv",
                           "camtrap-measure_TON_CAM02_start_end.csv"]
    for path, cam in zip(body["paths"], ["MAS_CAM01", "MAS_CAM02", "TON_CAM02"]):
        doc, rows = read(path)
        assert [r["camera"] for r in rows] == [cam] and f"camera={cam}" in doc[0]


def test_split_applies_the_screen_filters_to_every_file(measured, tmp_path):
    body = split(measured, tmp_path, "camera", date_from="2026-05-02", date_to="2026-05-03", include_suspicious=True)
    # MAS_CAM01 keeps only its weak box (05-02); MAS_CAM02 its deer (05-03); TON_CAM02 has only a raccoon then
    assert names(body) == ["camtrap-measure_MAS_CAM01_2026-05-02_2026-05-03.csv",
                           "camtrap-measure_MAS_CAM02_2026-05-02_2026-05-03.csv"]
    doc, rows = read(body["paths"][0])
    assert [(r["photo"], r["flag"] != "") for r in rows] == [("IMG_B.JPG", True)]
    assert "from=2026-05-02" in doc[0] and "rows that need a look included" in doc[0]

    every = split(measured, tmp_path, "site", all_species=True, survey_site="TON")
    assert names(every) == ["camtrap-measure_TON_start_end.csv"]  # the site filter narrows the split too
    _, rows = read(every["paths"][0])
    assert sorted(r["species"] for r in rows) == ["raccoon", "white-tailed deer"]


def test_split_honours_the_folder_scope(measured, tmp_path):
    body = split(measured, tmp_path, "site", folder=str(tmp_path / "photos" / "TON_CAM02"))
    assert names(body) == ["camtrap-measure_TON_start_end.csv"]


def test_split_never_overwrites_a_file(measured, tmp_path):
    first = split(measured, tmp_path, "site")
    before = Path(first["paths"][0]).read_text(encoding="utf-8")
    Path(first["paths"][0]).write_text("mine", encoding="utf-8")
    second = split(measured, tmp_path, "site")
    assert names(second) == ["camtrap-measure_MAS_start_end (2).csv", "camtrap-measure_TON_start_end (2).csv"]
    assert Path(first["paths"][0]).read_text(encoding="utf-8") == "mine"
    assert read(second["paths"][0])[1] == list(csv.DictReader(l for l in before.splitlines() if not l.startswith("#")))
    assert names(split(measured, tmp_path, "site"))[0] == "camtrap-measure_MAS_start_end (3).csv"


def test_split_refuses_a_missing_folder_or_an_unknown_split(measured, tmp_path):
    r = measured.post("/api/export/split", params={"to": str(tmp_path / "nope"), "by": "site"})
    assert r.status_code == 400 and "Folder not found" in r.json()["detail"]
    r = measured.post("/api/export/split", params={"to": str(tmp_path), "by": "day"})
    assert r.status_code == 400 and "site or camera" in r.json()["detail"]


def test_summary_reads_at_site_level(measured):
    s = measured.get("/api/summary", params={"survey_site": "MAS"}).json()
    assert [c["site"] for c in s["cameras"]] == ["MAS_CAM01", "MAS_CAM02"] and s["photos"] == 3
    assert measured.get("/api/summary", params={"survey_site": "MAS", "site": "TON_CAM02"}).json()["photos"] == 0


def test_cameras_carry_their_survey_site(measured):
    assert {c["site"]: c["survey_site"] for c in measured.get("/api/cameras").json()} == {
        "MAS_CAM01": "MAS", "MAS_CAM02": "MAS", "SRF_CAM08": "SRF", "TON_CAM02": "TON"}


def test_open_folder_opens_only_a_folder_the_split_wrote_to(measured, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(dialogs.os, "startfile", opened.append, raising=False)
    assert measured.post("/api/folder/open", json={"path": str(tmp_path)}).status_code == 404
    body = split(measured, tmp_path, "camera")
    assert measured.post("/api/folder/open", json={"path": body["folder"]}).json() == {"ok": True}
    assert opened == [Path(body["folder"])]
