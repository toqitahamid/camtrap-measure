import pytest
from camtrap_measure.calib.model_a import ModelA, blend
from .synth import flat_photo

def test_blend():
    anchors = [(0.0, 10.0), (100.0, 20.0)]
    assert blend(50.0, anchors) == pytest.approx(15.0)
    assert blend(-5.0, anchors) == 10.0      # outside fan -> nearest
    assert blend(500.0, anchors) == 20.0
    assert blend(7.0, [(3.0, 42.0)]) == 42.0  # single anchor

def test_interpolates_on_transect():
    m = ModelA.fit(flat_photo())
    d, status = m.predict(960.0, 1000.0 - 30.0 * 7.5)  # halfway between 7 and 8 m on C
    assert status == "ok" and d == pytest.approx(7.5, abs=0.05)

def test_blends_between_transects():
    m = ModelA.fit(flat_photo())
    d, status = m.predict(830.0, 1000.0 - 30.0 * 5.0)  # midway between L(700) and C(960)
    assert status == "ok" and d == pytest.approx(5.0, abs=0.05)

def test_out_of_range():
    m = ModelA.fit(flat_photo(dists=range(2, 16)))
    d, status = m.predict(960.0, 990.0)   # v below nearest flag (closer than 2 m)
    assert d is None and status == "below_range"
    d, status = m.predict(960.0, 300.0)   # v above farthest flag
    assert d is None and status == "beyond_range"

def test_single_transect_fallback():
    ph = flat_photo(transects=(("R", 1220.0),))
    m = ModelA.fit(ph)
    d, status = m.predict(200.0, 1000.0 - 30.0 * 6.0)  # far from R, still answered
    assert status == "ok" and d == pytest.approx(6.0, abs=0.05)

def test_insufficient_data():
    ph = flat_photo(dists=[5], transects=(("C", 960.0),))  # one flag: cannot interpolate
    m = ModelA.fit(ph)
    assert m.predict(960.0, 850.0) == (None, "insufficient_data")

def test_duplicate_observations_averaged():
    ph = flat_photo()
    # add a second, offset observation of the C-transect 5 m flag
    from camtrap_measure.calib.data import GroundObs
    ph.ground.append(GroundObs(970.0, 1000.0 - 30.0 * 5.0 + 10.0, 5.0, "C", "vspan_proj", 0.5))
    m = ModelA.fit(ph)
    d, status = m.predict(960.0, 1000.0 - 30.0 * 5.0 + 5.0)  # at the averaged v
    assert status == "ok" and d == pytest.approx(5.0, abs=0.1)

def test_coincident_rows_do_not_crash():
    ph = flat_photo(dists=[5], transects=(("C", 960.0),))
    from camtrap_measure.calib.data import GroundObs
    ph.ground.append(GroundObs(960.0, 1000.0 - 30.0 * 5.0, 7.0, "C", "wire_point", 1.0))  # same v, different dist
    m = ModelA.fit(ph)  # must not raise
    assert m.predict(960.0, 850.0) == (None, "insufficient_data")
