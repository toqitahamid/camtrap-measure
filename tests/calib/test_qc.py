import pytest
from camtrap_measure.calib.data import GroundObs, SizeObs, PhotoData
from camtrap_measure.calib.qc import monotonicity, loo_cv
from camtrap_measure.calib.model_b import ModelB
from .synth import projective_photo, flat_photo

def test_monotonicity_clean():
    ph, _ = projective_photo()
    assert monotonicity(ph) == []

def test_monotonicity_catches_swapped_labels():
    ph, _ = projective_photo()
    # swap the distance tags of the 5 m and 6 m flags on C
    for g in ph.ground:
        if g.transect == "C" and g.dist == 5.0:
            g.dist = 6.0
        elif g.transect == "C" and g.dist == 6.0:
            g.dist = 5.0
    v = monotonicity(ph)
    assert any(x["transect"] == "C" and x["kind"] == "ground_v" for x in v)

def test_loo_cv_small_errors_on_synthetic():
    ph, _ = projective_photo(noise_px=1.0)
    rows = loo_cv(ph)
    assert len(rows) == 42
    errs_b = [abs(r["err_b"]) for r in rows if r["err_b"] is not None]
    assert len(errs_b) > 35
    errs_b.sort()
    assert errs_b[len(errs_b) // 2] < 0.5      # median LOO error under 0.5 m
    # interior flags should also be well-predicted by Model A
    errs_a = [abs(r["err_a"]) for r in rows if r["err_a"] is not None]
    assert sorted(errs_a)[len(errs_a) // 2] < 0.5
