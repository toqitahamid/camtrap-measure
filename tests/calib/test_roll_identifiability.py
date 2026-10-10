"""Self-check for the roll-identifiability prior in ModelB.fit.

Rule (experiments/refnet/30_roll_identifiability): a photo with <=1 distinct
DIRECT-marker transect (source wire_point / f2g_end) cannot identify camera
roll, so roll is hard-fixed to 0 and only f/h/pitch are fitted; a photo with
>=2 direct transects fits all 4 params (roll free) exactly as before.
Relaxed by experiments/refnet/47_app_roll_rule: roll is also fitted when >=2
transects each carry >=2 ground obs of any source (vertical-span projections
count) at >=2 distinct distances. The synthetic flags stand at the height the
projection ratio assumes (data.VSPAN_PROJ_RATIO, folder 52).

Run standalone:
    PYTHONPATH=. ./depthenv/bin/python tests/test_roll_identifiability.py
Or via pytest.
"""
import math

from camtrap_measure.calib import data
from camtrap_measure.calib.data import VSPAN_PROJ_RATIO, GroundObs, PhotoData, from_annotation
from camtrap_measure.calib.model_b import ModelB, PlaneParams, roll_identifiable, world_to_pixel

CX, CY = 960.0, 540.0
H_TRUE = 2.0
F_TRUE = 3000.0
PITCH_TRUE = 0.2


def _obs(x, z, p_true, transect):
    """Project a ground world point (y = h) to a direct GroundObs."""
    u, v = world_to_pixel(x, H_TRUE, z, p_true, CX, CY)
    dist = math.hypot(x, z)
    return GroundObs(u, v, dist, transect, "wire_point", 1.0)


def _photo(ground):
    ph = PhotoData("SYNTH", "img.jpg", 1920, 1080)
    ph.ground = ground
    return ph


def test_three_transects_fits_roll_freely():
    """3 direct transects -> roll is fitted (recovers the injected nonzero roll)."""
    p_true = PlaneParams(F_TRUE, H_TRUE, PITCH_TRUE, 0.12)
    ground = []
    for x, transect in [(-2.0, "L"), (0.0, "C"), (2.0, "R")]:
        for z in (5.0, 8.0, 11.0):
            ground.append(_obs(x, z, p_true, transect))
    m = ModelB.fit(_photo(ground))
    assert m.ok, "3-transect synthetic photo should fit"
    assert abs(m.params.roll - 0.12) < 1e-3, (
        f"roll should recover ~0.12 freely, got {m.params.roll}")


def test_one_transect_fixes_roll_to_zero():
    """<=1 direct transect -> roll hard-fixed to exactly 0.0, f/h/pitch still fit."""
    p_true = PlaneParams(F_TRUE, H_TRUE, PITCH_TRUE, 0.0)
    ground = [_obs(0.0, z, p_true, "C") for z in (4.0, 5.0, 6.0, 8.0, 10.0, 12.0)]
    m = ModelB.fit(_photo(ground))
    assert m.ok, "1-transect synthetic photo should still fit (3 free params)"
    assert m.params.roll == 0.0, f"roll must be exactly 0.0, got {m.params.roll}"
    assert abs(m.params.h - H_TRUE) < 1e-2, f"height off: {m.params.h}"
    assert abs(m.params.pitch - PITCH_TRUE) < 1e-2, f"pitch off: {m.params.pitch}"


# --- folder 47: vertical spans on two transects also pin roll -----------------------------------------------

BODY_H_M = 0.0635  # flag body height (the data.py default)
# Flag top above the ground: (VSPAN_PROJ_RATIO + 1) body heights, 36.8 cm, so the rendered spans project onto the
# true ground under the app's ratio. Before folder 52: the wire's nominal 49.53 cm, with ratio (49.53 - 6.35) / 6.35.
TOP_M, OLD_TOP_M, OLD_RATIO = (VSPAN_PROJ_RATIO + 1) * BODY_H_M, 0.4953, (49.53 - 6.35) / 6.35
P_ROLLED = PlaneParams(3000.0, 1.2, 0.12, 0.10)


def _annotation(p, direct=("C",), spans=("L", "C", "R"), dists=(4.0, 6.0, 8.0, 10.0, 12.0, 14.0), top_m=TOP_M):
    """A schema-v2 FlagLabel annotation rendered from camera p: wire ground points on the `direct` transects and
    flag-body vertical spans on the `spans` transects, flags at 4-14 m on azimuths -12, 0, +12 deg."""
    pts, vspans = [], []
    for transect, az in zip("LCR", (-12.0, 0.0, 12.0)):
        for d in dists:
            x, z = d * math.sin(math.radians(az)), d * math.cos(math.radians(az))
            if transect in direct:
                u, v = world_to_pixel(x, p.h, z, p, CX, CY)
                pts.append({"u": u, "v": v, "transect": transect, "distance": d})
            if transect in spans:  # top and bottom of the flag body; the ground is at y = h
                (u1, v1), (u2, v2) = (world_to_pixel(x, p.h - y, z, p, CX, CY) for y in (top_m, top_m - BODY_H_M))
                vspans.append({"u1": u1, "v1": v1, "u2": u2, "v2": v2, "transect": transect, "distance": d})
    return {"site": "SYN", "image": "SYN.JPG", "image_w": 1920, "image_h": 1080, "wire_ground_points": pts,
            "flag_vertical_spans": vspans, "flag_horizontal_spans": [], "flag_to_ground_spans": []}


def test_direct_marks_on_one_transect_and_spans_on_three_fit_the_roll():
    """The old rule held roll at 0 here (one direct transect); the span projections cover L, C and R."""
    photo = from_annotation(_annotation(P_ROLLED))
    assert len({o.transect for o in photo.ground if o.source == "wire_point"}) == 1
    assert roll_identifiable(photo.ground)
    m = ModelB.fit(photo)
    assert m.ok and abs(m.params.roll - P_ROLLED.roll) < 1e-3, m.params
    assert abs(m.params.pitch - P_ROLLED.pitch) < 0.01 and abs(m.params.h - P_ROLLED.h) < 0.05, m.params


def test_spans_on_one_transect_still_hold_roll_at_zero():
    photo = from_annotation(_annotation(P_ROLLED, spans=("C",)))
    assert not roll_identifiable(photo.ground)
    m = ModelB.fit(photo)
    assert m.ok and m.params.roll == 0.0


def test_a_second_transect_needs_two_distances():
    """Spans on L at a single distance do not make L count: >= 2 obs at >= 2 distinct distances per transect."""
    one = _annotation(P_ROLLED, spans=())
    one["flag_vertical_spans"] = [s for s in _annotation(P_ROLLED, spans=("L",))["flag_vertical_spans"]
                                  if s["distance"] == 6.0] * 2
    photo = from_annotation(one)
    assert not roll_identifiable(photo.ground)
    assert ModelB.fit(photo).params.roll == 0.0
    two = _annotation(P_ROLLED, spans=())
    two["flag_vertical_spans"] = [s for s in _annotation(P_ROLLED, spans=("L",))["flag_vertical_spans"]
                                  if s["distance"] in (6.0, 10.0)]
    assert roll_identifiable(from_annotation(two).ground)


def test_two_direct_transects_fit_exactly_as_before(monkeypatch):
    """The old rule's case is untouched: same decision, and the same numbers as the code before folder 47
    (pinned from git HEAD's ModelB.fit, 2026-10-10). Pinned under the projection ratio of that code, 6.8, which
    folder 52 changed; so this test sets it back and renders the flags at 49.53 cm."""
    monkeypatch.setattr(data, "VSPAN_PROJ_RATIO", OLD_RATIO)
    photo = from_annotation(_annotation(P_ROLLED, direct=("L", "R"), top_m=OLD_TOP_M))
    assert roll_identifiable(photo.ground)
    p = ModelB.fit(photo).params
    for got, want in ((p.f, 3050.3959378015134), (p.h, 1.1820915767554494), (p.pitch, 0.11807870183083646),
                      (p.roll, 0.09999999999709319)):
        assert math.isclose(got, want, rel_tol=1e-6), (got, want)


if __name__ == "__main__":
    test_three_transects_fits_roll_freely()
    test_one_transect_fixes_roll_to_zero()
    print("PASS: roll fitted freely with 3 transects; hard-fixed to 0 with 1 transect")
