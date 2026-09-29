"""Distance sampling: the density is only worth showing if it recovers a density we planted. Deer are simulated
in a known density around cameras with known effort, seen with a known detection function, and the estimate
has to come back to it. Then the rules the screen and the R file rely on: truncation, cameras with no deer,
the seeded interval, and which rows may enter at all."""

import csv
import math

import numpy as np
import pytest
from scipy.integrate import quad

from camtrap_measure import density, report, store

from tests.test_report import measured  # noqa: F401  (fixture: a scripted folder measured through the API)

SAVED = {"interval_s": None, "truncation_m": None, "cameras": {}}
DAYS, T, FOV = 30, 2.0, 42.0


def survey(true_per_km2: float, g, cameras: int = 10, seed: int = 1, empty: tuple[str, ...] = ()):
    """Rows and photos of a simulated survey: deer placed uniformly in a 60 m disc around each camera over the
    whole of its snapshot effort, each seen with probability g(r). Every camera runs DAYS days at FOV degrees."""
    rng = np.random.default_rng(seed)
    big_w = 60.0
    rows, photos = [], []
    for k in range(cameras):
        site = f"CAM{k:02d}"
        for i, day in enumerate(("2026-01-01T06:00:00", f"2026-01-{DAYS:02d}T18:00:00")):
            photos.append({"path": f"D:\\cards\\{site}\\IMG_{i}.JPG", "site": site, "captured_at": day,
                           "make": "BROWNING", "model": "BTC-7E", "method": "md"})
        if site in empty:
            continue
        moments = DAYS * 86_400 / T * FOV / 360
        n = rng.poisson(true_per_km2 / 1e6 * math.pi * big_w**2 * moments)
        r = big_w * np.sqrt(rng.random(n))
        r = r[rng.random(n) < g(r)]
        for i, x in enumerate(r):
            rows.append(det(site, float(x), idx=i))
    return rows, photos


def det(site: str, d: float | None, idx: int = 0, **kw) -> dict:
    row = {"path": f"D:\\cards\\{site}\\IMG_0.JPG", "site": site, "captured_at": "2026-01-01T06:00:00", "idx": idx,
           "method": "md", "species": "white-tailed deer", "confidence": 0.9, "match_score": 300, "distance_m": d,
           "q05_m": d * 0.9 if d is not None else None, "q95_m": d * 1.1 if d is not None else None}
    return {**row, **kw}


def half_normal(sigma):
    return lambda r: np.exp(-r * r / (2 * sigma * sigma))


def hazard_rate(sigma, b):
    return lambda r: 1 - np.exp(-np.power(np.maximum(r, 1e-9) / sigma, -b))


# --- the method -----------------------------------------------------------------------------------------------

def test_half_normal_survey_recovers_the_planted_density():
    rows, photos = survey(3.0, half_normal(6.0))
    res = density.estimate(rows, photos, SAVED, reps=200)
    assert res["fit"]["model"] == "half-normal"
    assert res["fit"]["sigma"] == pytest.approx(6.0, rel=0.1)
    assert res["density"]["per_km2"] == pytest.approx(3.0, rel=0.15)
    assert res["density"]["lo"] <= 3.0 <= res["density"]["hi"]


def test_hazard_rate_survey_is_fitted_and_chosen_by_aic():
    rows, photos = survey(3.0, hazard_rate(8.0, 4.0), seed=3)
    res = density.estimate(rows, photos, {**SAVED, "truncation_m": 20.0}, reps=100)
    assert res["fit"]["model"] == "hazard-rate" and res["fit"]["other"]["model"] == "half-normal"
    assert res["fit"]["aic"] < res["fit"]["other"]["aic"]
    assert res["fit"]["b"] == pytest.approx(4.0, rel=0.3) and res["fit"]["sigma"] == pytest.approx(8.0, rel=0.15)
    assert res["density"]["per_km2"] == pytest.approx(3.0, rel=0.2)


def test_detection_probability_of_a_known_half_normal():
    """P = 2σ²(1 − exp(−w²/2σ²)) / w² for a half-normal, and the effective radius is w√P."""
    f = {"model": "half-normal", "sigma": 5.0, "b": None}
    want = 2 * 25 * (1 - math.exp(-100 / 50)) / 100
    assert density.detection_p(f, 10.0) == pytest.approx(want)
    for b in (1.0, 3.0, 20.0):  # the fixed quadrature against scipy's adaptive one, up to a sharp shoulder
        hr = {"model": "hazard-rate", "sigma": 5.0, "b": b}
        want, _ = quad(lambda r: r * (1 - math.exp(-((r / 5.0) ** -b))) if r > 0 else 0.0, 0, 10, points=[5], limit=200)
        assert density.detection_p(hr, 10.0) == pytest.approx(2 * want / 100, rel=1e-4)


def test_truncation_defaults_to_the_95th_percentile_rounded_up_and_can_be_set():
    rows = [det("CAM00", float(d), idx=i) for i, d in enumerate(range(1, 101))]  # 1..100 m
    photos = survey(0, half_normal(5), cameras=1)[1]
    res = density.estimate(rows, photos, SAVED, reps=20)
    assert res["truncation_default_m"] == 96.0 and res["truncation_m"] == 96.0  # p95 of 1..100 is 95.05
    assert res["used"] == 96 and res["beyond"] == 4
    res = density.estimate(rows, photos, {**SAVED, "truncation_m": 50.0}, reps=20)
    assert res["truncation_m"] == 50.0 and res["used"] == 50 and res["beyond"] == 50
    assert all(b["hi"] <= 50.0 + 1e-9 for b in res["bins"])


def test_a_camera_with_no_deer_still_counts_in_the_effort():
    rows, photos = survey(3.0, half_normal(6.0), cameras=4, empty=("CAM03",))
    with_empty = density.estimate(rows, photos, SAVED, reps=20)
    without = density.estimate(rows, [p for p in photos if p["site"] != "CAM03"], SAVED, reps=20)
    assert [c["site"] for c in with_empty["cameras"]][-1] == "CAM03"
    assert with_empty["effort"] == pytest.approx(without["effort"] * 4 / 3)
    assert with_empty["density"]["per_km2"] == pytest.approx(without["density"]["per_km2"] * 3 / 4)


def test_effort_is_snapshot_moments_times_the_share_of_the_circle():
    photos = survey(0, half_normal(5), cameras=1)[1]
    [cam] = density.camera_setup(photos, {})
    assert cam["active_days"] == DAYS and cam["fov_deg"] == 42.0 and cam["fov_checked"] is False
    assert density.effort([cam], 2.0) == {"CAM00": DAYS * 86_400 / 2.0 * 42 / 360}
    [cam] = density.camera_setup(photos, {"CAM00": {"active_days": 10, "fov_deg": 60}})
    assert cam["active_days"] == 10 and cam["active_days_default"] == DAYS and cam["fov_checked"] is True
    assert density.effort([cam], 5.0) == {"CAM00": 10 * 86_400 / 5.0 * 60 / 360}


def test_field_of_view_comes_from_the_model_table_only(monkeypatch):
    photos = survey(0, half_normal(5), cameras=1)[1]
    monkeypatch.setattr(density, "FOV_BY_MODEL", {("BROWNING", "BTC-7E"): 41.0})
    [cam] = density.camera_setup(photos, {})
    assert cam["fov_deg"] == 41.0 and cam["fov_checked"] is True


def test_fitting_works_while_torch_is_half_imported(monkeypatch):
    """The model warmup imports torch on another thread. A gradient optimiser in scipy asks whether its input is a
    torch tensor, and a half-imported torch has no Tensor yet: DENSITY answered 500 at startup (2026-09-28)."""
    import sys
    import types

    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))  # no Tensor, as mid-import
    r = np.array([3.0, 4.5, 5.0, 6.2, 7.1, 8.0, 9.4, 10.2])
    chosen, other = density.fit(r, 12.0)
    assert {chosen["model"], other["model"]} == {"half-normal", "hazard-rate"}


def test_the_interval_holds_the_estimate_and_is_the_same_every_time():
    rows, photos = survey(3.0, half_normal(6.0), cameras=6, seed=7)
    a = density.estimate(rows, photos, SAVED, reps=200)
    b = density.estimate(rows, photos, SAVED, reps=200)
    assert a["density"] == b["density"]
    assert a["density"]["lo"] < a["density"]["per_km2"] < a["density"]["hi"]


def test_fewer_than_three_cameras_resample_deer_and_few_deer_warn():
    rows, photos = survey(0.1, half_normal(6.0), cameras=2, seed=5)
    res = density.estimate(rows, photos, SAVED, reps=100)
    assert 0 < res["used"] < density.MIN_DEER and res["too_few"] is True
    assert res["density"]["lo"] <= res["density"]["per_km2"] <= res["density"]["hi"]


def test_no_deer_gives_setup_but_no_estimate():
    photos = survey(0, half_normal(5), cameras=2)[1]
    res = density.estimate([], photos, SAVED)
    assert res["used"] == 0 and res["density"] is None and res["fit"] is None and len(res["cameras"]) == 2


def test_suspicious_non_deer_and_other_method_rows_stay_out():
    photos = survey(0, half_normal(5), cameras=1)[1]
    rows = [det("CAM00", 5.0, idx=0),
            det("CAM00", 6.0, idx=1, species="raccoon"),
            det("CAM00", 7.0, idx=2, species="unsure"),
            det("CAM00", 8.0, idx=3, confidence=0.2),
            det("CAM00", None, idx=4),
            det("CAM00", 9.0, idx=5, match_score=5),
            det("CAM00", 5.5, idx=0, method="sam3")]  # the same deer under the method this photo is not on now
    used, counts = density.deer_rows(rows, photos)
    assert [r["idx"] for r in used] == [0] and used[0]["method"] == "md"
    assert counts == {"deer": 5, "suspicious": 4}  # the raccoon is not a deer; the other four need a look
    res = density.estimate(rows, photos, SAVED, reps=10)
    assert res["deer"] == res["used"] + res["beyond"] + res["suspicious"] + res["no_days_deer"]


# --- the R file -----------------------------------------------------------------------------------------------

def read_r(text: str) -> tuple[list[str], list[dict]]:
    lines = text.splitlines()
    return [l for l in lines if l.startswith("#")], list(csv.DictReader(l for l in lines if not l.startswith("#")))


def test_the_r_file_has_the_distance_columns_and_a_row_for_a_camera_with_no_deer():
    rows, photos = survey(3.0, half_normal(6.0), cameras=3, empty=("CAM02",))
    saved = {**SAVED, "truncation_m": 15.0, "cameras": {"CAM01": {"fov_deg": 60}}}
    doc, out = read_r(density.export_csv(rows, photos, saved, {}))
    assert list(out[0]) == ["Region.Label", "Area", "Sample.Label", "Effort", "object", "distance", "size", "photo",
                            "timestamp"]
    deer = [r for r in out if r["distance"] != "NA"]
    assert len(deer) == sum(1 for r in rows if r["distance_m"] <= 15.0)
    assert all(float(r["distance"]) <= 15.0 and r["size"] == "1" for r in deer)
    assert [r["object"] for r in deer] == [str(i) for i in range(1, len(deer) + 1)]
    [zero] = [r for r in out if r["Sample.Label"] == "CAM02"]
    assert zero["distance"] == "NA" and zero["object"] == "NA"
    assert float(zero["Effort"]) == pytest.approx(DAYS * 86_400 / 2 * 42 / 360)
    assert float(next(r for r in out if r["Sample.Label"] == "CAM01")["Effort"]) == pytest.approx(DAYS * 86_400 / 2 * 60 / 360)
    text = "\n".join(doc)
    assert 'transect = "point"' in text and 'er_est = "P2"' in text and "truncation = 15" in text
    assert "t = 2 s" in text and "availability is taken as 1" in text


# --- through the API ------------------------------------------------------------------------------------------

def test_api_reads_saved_settings_and_exports(measured, monkeypatch):  # noqa: F811
    monkeypatch.setattr(density, "BOOTSTRAPS", 20)
    res = measured.get("/api/density").json()
    # the scripted folder: 5 deer-like rows, 3 suspicious, 1 raccoon-free clean deer at 5 m and one at 6 m
    assert res["deer"] == 5 and res["suspicious"] == 3 and res["used"] + res["beyond"] == 2
    assert res["interval_s"] == 2.0 and res["cameras"][0]["site"] == "TON_CAM02"
    r = measured.post("/api/density/settings", json={"interval_s": 5, "cameras": {"TON_CAM02": {"fov_deg": 55}}})
    assert r.status_code == 200
    res = measured.get("/api/density").json()
    assert res["interval_s"] == 5 and res["cameras"][0]["fov_deg"] == 55 and res["cameras"][0]["fov_checked"]
    assert store.config()["density"]["cameras"] == {"TON_CAM02": {"fov_deg": 55}}
    measured.post("/api/density/settings", json={"cameras": {"TON_CAM02": {"fov_deg": None}}})
    assert measured.get("/api/density").json()["cameras"][0]["fov_deg"] == 42.0
    assert measured.post("/api/density/settings", json={"interval_s": -1}).status_code == 400
    csv_r = measured.get("/api/density.csv")
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    _, out = read_r(csv_r.text)
    assert all(r["Sample.Label"] == "TON_CAM02" for r in out) and out


def test_saving_density_settings_keeps_the_installer_config():
    store.save_config({"hf_token": "hf_x", "weights_from": "bundle"})
    density.save_settings({"truncation_m": 25})
    assert store.config() == {"hf_token": "hf_x", "weights_from": "bundle",
                              "density": {"interval_s": None, "truncation_m": 25, "cameras": {}}}
    assert report.DEER >= {density.SPECIES}
