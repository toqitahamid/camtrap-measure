"""How a photo is lined up with its flag photo (ticket 33): day photos directly; a night photo by the Night rule. Copy
the nearer day photo's line-up when the day photos before (A) and after (B) agree the camera did not move; when it
moved, vote and Chain through the winning day photo, or Fall back to the nearer one; Copy the one day photo when only
one is found; the flag photos stand as day photos at the ends of a deployment; never a link from a night photo to a
flag photo. Also which stored answers are measured again, the researcher log (one line per photo, its reasons and
the Night-rule detail), and the same answer on every path.

The rules run on stand-in models: `Stub` hands the planner made-up links, and `inference.FakeModels` runs Real's own
two-stage run without a GPU. Numbers in the links are inliers, or (inliers, dx, dy) for a homography that shifts by
(dx, dy) px; the shift p95 of such a link is exactly hypot(dx, dy). Every rule's source is the grilling log
(.scratch/app/issues/33-night-bracket-grilling.md) and research folders 43, 59 and 60 of ../distance_estimation."""

import json
import os
import shutil
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageFile

from camtrap_measure import api, batch, calibration, inference, lineup, measure, report, store

from tests.conftest import flag_photo_data

FLAG = "FLAG.JPG"
NIGHT, DAY = True, False


def shot(at: str | None, night: bool | None, size=(1920, 1080), colour=(90, 120, 60)) -> bytes:
    """A JPEG with a capture time and the EXIF Flash tag Browning writes (13 at night, 16 by day; None: no tag)."""
    exif = Image.Exif()
    ifd = exif.get_ifd(0x8769)
    if at:
        ifd[0x9003] = at
    if night is not None:
        ifd[0x9209] = 13 if night else 16
    buf = BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG", exif=exif.tobytes(), quality=30)
    return buf.getvalue()


def camera(tmp_path: Path, photos: dict[str, tuple[str | None, bool]], name="cam") -> Path:
    """A camera folder: file name -> (capture time 'YYYY:MM:DD HH:MM:SS', night)."""
    d = tmp_path / name
    d.mkdir(parents=True)
    for n, (at, night) in photos.items():
        (d / n).write_bytes(shot(at, night))
    return d


def flag_cal(tmp_path: Path, name=FLAG, updated="v1", at: str | None = "2026:01:01 10:00:00") -> dict:
    """A usable calibration (the synthetic camera of conftest) with its flag photo on disk, taken at `at`."""
    p = tmp_path / "flags" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(shot(at, DAY))
    row = calibration.fit({"site": "CAM", "image_name": name, "status": "annotated", "updated_at": updated,
                           "data": flag_photo_data()}, p.read_bytes())
    assert row["ok"]
    return {**row, "ref_path": str(p)}


def later_flag(tmp_path: Path, monkeypatch, name="FLAG2.JPG", at="2026:01:12 09:00:00") -> dict:
    """A second flag photo of the camera (a service visit), as the store would list it."""
    g = flag_cal(tmp_path, name, at=at)
    monkeypatch.setattr(lineup, "flag_photos", lambda site: [g] if site == "CAM" else [])
    return g


class Stub:
    """The model call the planner needs, made up and recorded."""

    def __init__(self, links=None, default=8000):
        self.table, self.default, self.calls = links or {}, default, []

    def link(self, target: Path, reference: Path):
        self.calls.append((target.name, reference.name))
        got = self.table.get((target.name, reference.name), self.default)
        if isinstance(got, np.ndarray):
            return got, 8000
        inliers, dx, dy = got if isinstance(got, tuple) else (got, 0.0, 0.0)
        return (np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float) if inliers >= 4 else None), inliers


class Decoding(Stub):
    """Decodes both photos before the made-up link, as the real backend does (inference.Real._link)."""

    def link(self, target: Path, reference: Path):
        for q in (target, reference):
            with Image.open(q) as im:
                im.load()
        return super().link(target, reference)


class Locked(Stub):
    """The photo `name` is locked by another program while the run looks at it."""

    def __init__(self, name: str, links=None):
        super().__init__(links)
        self.name = name

    def link(self, target: Path, reference: Path):
        if self.name in (target.name, reference.name):
            raise PermissionError(f"{self.name} is open in another program")
        return super().link(target, reference)


def cut(path: Path) -> None:
    """Cut a photo short, as a copy that stopped half way does: the header and EXIF survive, the picture does not.
    Decoding it fails under Pillow's default (the caller turns LOAD_TRUNCATED_IMAGES off: the real app's detector
    libraries turn it on, and then only a file that is gone, locked or corrupt beyond that fails)."""
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    with pytest.raises(OSError), Image.open(path) as im:
        im.load()


def never():
    """A stub that fails if it is asked to measure a link: the store must already have it."""
    stub = Stub()
    stub.link = lambda *a: pytest.fail("measured a link the store already had")
    return stub


def planner(stub: Stub, flag: dict, setting: str = "research") -> lineup.Planner:
    return lineup.Planner(stub.link, flag, setting)


def why(line: lineup.Line, **row) -> list[str]:
    """report.reasons of one detection row read through this line-up."""
    return report.reasons({"match_score": line.score, "confidence": 0.9, "species": "white-tailed deer",
                           "distance_m": None, "align_source": line.source, "align_status": line.status,
                           "align_detail": json.dumps(line.detail), **row})


def log_lines() -> list[dict]:
    """Every line of the researcher log (research-log.jsonl) in the test's data folder."""
    return [json.loads(x) for x in (lineup.log_dir() / lineup.LOG_NAME).read_text().splitlines()]


def logged(line: lineup.Line) -> dict | None:
    """The `night` object of the researcher-log line measure._job writes for a photo with this line-up (no boxes):
    None for a day photo, which has no `night` object. What a night answer asks to check by eye is its `checks` field:
    the only place it is kept (user decision 2026-10-11; the export's `check` column is gone)."""
    measure._log_measured(Path("IMG_N.JPG"), "CAM", {}, [], line.public())
    return log_lines()[-1].get("night")


def no_night_to_flag(calls, nights, flags=(FLAG, "FLAG2.JPG")) -> None:
    """Q10: no night photo is ever lined up with a flag photo, in either direction."""
    assert not [c for c in calls if (c[0] in nights and c[1] in flags) or (c[1] in nights and c[0] in flags)], calls


# --- facts about one photo ----------------------------------------------------------------------------------

def test_day_or_night_comes_from_the_flash_bit():
    assert lineup.is_night(13) is True and lineup.is_night(16) is False and lineup.is_night(None) is None
    assert lineup.is_night(9) is True and lineup.is_night(24) is False  # bit 0 only: "fired" whatever the mode bits say


def test_day_or_night_is_read_from_the_file_and_from_colour_when_the_tag_is_missing(tmp_path):
    for name, data, want in [("n.jpg", shot("2026:01:01 22:00:00", NIGHT), True),
                             ("d.jpg", shot("2026:01:01 12:00:00", DAY), False),
                             ("grey.jpg", shot(None, None, colour=(120, 120, 120)), True),   # IR: no colour
                             ("green.jpg", shot(None, None, colour=(60, 140, 50)), False)]:  # daylight: colour
        (tmp_path / name).write_bytes(data)
        assert lineup.read_night(tmp_path / name) is want, name
    (tmp_path / "bad.jpg").write_bytes(b"not a jpeg")
    assert lineup.read_night(tmp_path / "bad.jpg") is None


def test_the_shift_of_a_link_is_the_p95_grid_displacement():
    H = np.array([[1, 0, 3.0], [0, 1, 4.0], [0, 0, 1]])
    assert lineup.shift_p95(H, 1920, 995) == pytest.approx(5.0)
    assert lineup.shift_p95(np.eye(3), 2, 2) == 0.0  # a stub photo smaller than the grid still has a centre


def test_the_camera_counter_is_the_last_number_in_the_file_name():
    assert lineup.counter("IMG_0215.JPG") == 215 and lineup.counter("MAS_CAM07_IMG_0009.jpg") == 9
    assert lineup.counter("night.jpg") is None


# --- day photos -----------------------------------------------------------------------------------------------

def test_a_day_photo_lines_up_directly_as_before(tmp_path):
    d = camera(tmp_path, {"IMG_1.JPG": ("2026:01:10 12:00:00", DAY)})
    stub = Stub({("IMG_1.JPG", FLAG): (7000, 1.0, 0.0)})
    line = planner(stub, flag_cal(tmp_path)).plan(d / "IMG_1.JPG")
    assert (line.source, line.status, line.score, line.night) == ("direct", "ok", 7000, False)
    assert line.H[0, 2] == 1.0 and stub.calls == [("IMG_1.JPG", FLAG)]


@pytest.mark.parametrize("got, reason", [
    ((None, 3), "lines up poorly with its flag photo (3 points, needs 15). Wrong camera, or was it moved?"),
    ((None, 40), "did not line up with its flag photo, so no distance"),  # points, but no homography from them
])
def test_a_day_photo_with_no_line_up_of_its_own_is_not_lined_up(tmp_path, got, reason):
    d = camera(tmp_path, {"IMG_1.JPG": ("2026:01:10 12:00:00", DAY)})
    stub = Stub()
    stub.link = lambda target, reference: got
    line = planner(stub, flag_cal(tmp_path)).plan(d / "IMG_1.JPG")
    assert (line.source, line.status, line.H, line.score) == ("direct", "none", None, got[1])
    assert why(line) == [reason] and logged(line) is None  # a day answer writes no researcher log line


# --- night photos: Copy ------------------------------------------------------------------------------------------

A, P, B = "IMG_1.JPG", "IMG_2.JPG", "IMG_3.JPG"
NIGHT_CAM = {A: ("2026:01:10 12:00:00", DAY),     # the day photo before
             P: ("2026:01:10 22:00:00", NIGHT),   # 10 h after A, 14 h before B
             B: ("2026:01:11 12:00:00", DAY)}     # the day photo after
TO_FLAG = {(A, FLAG): (8000, 0.2, 0.0), (B, FLAG): (9000, 0.1, 0.0)}
MOVED = {**TO_FLAG, (B, A): (9000, 30.0, 0.0)}  # B onto A: 30 px, the camera moved


@pytest.mark.parametrize("at, side, anchor, dx, score", [
    ("2026:01:10 22:00:00", "A", A, 0.2, 8000),   # 10 h after A, 14 h before B
    ("2026:01:11 05:00:00", "B", B, 0.1, 9000),   # 17 h after A, 7 h before B
    ("2026:01:11 00:00:00", "A", A, 0.2, 8000),   # 12 h either way: a tie goes to A
])
def test_a_night_photo_copies_the_line_up_of_the_nearer_day_photo(tmp_path, at, side, anchor, dx, score):
    d = camera(tmp_path, {**NIGHT_CAM, P: (at, NIGHT)})
    stub = Stub(TO_FLAG)
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.source, line.status, line.anchor, line.score, line.night) == ("night", "ok", anchor, score, True)
    assert line.H[0, 2] == pytest.approx(dx)  # the day photo's own line-up to the flag photo, as measured
    assert (line.detail["path"], line.detail["side"], line.detail["before"], line.detail["after"]) == ("copy", side, A, B)
    assert line.detail["flag"] == FLAG and line.detail["gap_unit"] == "s" and line.folder is None
    assert not [c for c in stub.calls if P in c]  # Copy lines the night photo up with nothing
    assert sorted(stub.calls) == sorted([(A, FLAG), (B, FLAG), (B, A)])
    assert why(line) == ["could not find the ground under the animal, so no distance"]  # no line-up reason at all
    assert logged(line)["checks"] == []


@pytest.mark.parametrize("dx, path", [(20.0, "copy"), (20.01, "chain")])
def test_the_day_photos_agree_up_to_a_shift_of_20_px(tmp_path, dx, path):
    d = camera(tmp_path, NIGHT_CAM)
    stub = Stub({**TO_FLAG, (B, A): (9000, dx, 0.0)})
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert line.status == "ok" and line.detail["move_px"] == pytest.approx(dx) and line.detail["path"] == path
    assert ((P, A) in stub.calls) == (path == "chain")  # the vote runs only when the camera moved


@pytest.mark.parametrize("points, path", [(999, "chain"), (1000, "copy")])
def test_day_photos_that_match_under_1000_points_are_read_as_moved(tmp_path, points, path):
    """"Not comparable" (B -> A under 1,000 points; never seen in folder 58) goes to the vote, so there is an answer."""
    d = camera(tmp_path, NIGHT_CAM)
    line = planner(Stub({**TO_FLAG, (B, A): points}), flag_cal(tmp_path)).plan(d / P)
    assert (line.status, line.detail["path"], line.detail["move_points"]) == ("ok", path, points)


@pytest.mark.parametrize("points, before", [(3999, None), (4000, A)])
def test_a_day_photo_needs_4000_points_to_the_flag_photo(tmp_path, points, before):
    d = camera(tmp_path, NIGHT_CAM)
    cal = flag_cal(tmp_path, at=None)  # an undated flag photo takes no part: A can only be the day photo
    line = planner(Stub({**TO_FLAG, (A, FLAG): points}), cal).plan(d / P)
    assert line.detail["before"] == before and line.detail["before_tries"] == [[A, points]]


def test_day_photos_three_tries_a_side_and_burst_mates_skipped(tmp_path):
    d = camera(tmp_path, {"IMG_0.JPG": ("2026:01:09 12:00:00", DAY), "IMG_1.JPG": ("2026:01:10 10:00:00", DAY),
                          "IMG_11.JPG": ("2026:01:10 11:00:00", DAY), "IMG_12.JPG": ("2026:01:10 12:59:00", DAY),
                          "IMG_13.JPG": ("2026:01:10 13:00:00", DAY), "IMG_2.JPG": ("2026:01:10 22:00:00", NIGHT),
                          "IMG_3.JPG": ("2026:01:11 12:00:00", DAY)})
    stub = Stub({(n, FLAG): 3999 for n in ("IMG_1.JPG", "IMG_11.JPG", "IMG_12.JPG", "IMG_13.JPG")})
    line = planner(stub, flag_cal(tmp_path, at=None)).plan(d / "IMG_2.JPG")
    # walking back from 22:00: 13:00 is tried (3,999 < 4,000); 12:59 is its burst mate and is skipped; 11:00 and
    # 10:00 are tries two and three; the day before is never asked
    assert [t for t, r in stub.calls if r == FLAG and t != "IMG_3.JPG"] == ["IMG_13.JPG", "IMG_11.JPG", "IMG_1.JPG"]
    assert (line.status, line.detail["path"], line.anchor) == ("ok", "one_side", "IMG_3.JPG")


def test_night_photos_between_two_day_photos_are_skipped_on_the_way_to_a_day_photo(tmp_path):
    d = camera(tmp_path, {**NIGHT_CAM, "IMG_21.JPG": ("2026:01:10 21:00:00", NIGHT),
                          "IMG_25.JPG": ("2026:01:11 03:00:00", NIGHT)})
    stub = Stub(TO_FLAG)
    plan = planner(stub, flag_cal(tmp_path))
    lines = [plan.plan(d / n) for n in ("IMG_21.JPG", P, "IMG_25.JPG")]
    assert [(x.status, x.anchor) for x in lines] == [("ok", A), ("ok", A), ("ok", B)]  # 03:00 is 9 h before B
    assert sorted(stub.calls) == sorted([(A, FLAG), (B, FLAG), (B, A)])  # one night, each link measured once


def test_the_day_line_up_a_night_photo_copies_is_the_day_photos_own(tmp_path):
    d = camera(tmp_path, NIGHT_CAM)
    plan = planner(Stub(TO_FLAG), flag_cal(tmp_path))
    night, day = plan.plan(d / P), plan.plan(d / A)
    assert night.H is day.H and night.score == day.score == 8000  # one stored link, used by both


# --- night photos: the camera moved (vote, Chain, Fallback) --------------------------------------------------------

@pytest.mark.parametrize("at, to_a, to_b, side", [
    ("2026:01:10 22:00:00", 5000, 6000, "B"),   # more points wins, even on the far side
    ("2026:01:10 22:00:00", 6000, 5000, "A"),
    ("2026:01:10 22:00:00", 5000, 5000, "A"),   # a tie goes to the nearer (A: 10 h against 14 h)
    ("2026:01:11 05:00:00", 5000, 5000, "B"),   # a tie goes to the nearer (B: 7 h against 17 h)
])
def test_when_the_camera_moved_the_side_with_more_points_wins_the_vote(tmp_path, at, to_a, to_b, side):
    d = camera(tmp_path, {**NIGHT_CAM, P: (at, NIGHT)})
    stub = Stub({**MOVED, (P, A): to_a, (P, B): to_b})
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.status, line.detail["path"], line.detail["side"]) == ("ok", "chain", side)
    assert line.anchor == {"A": A, "B": B}[side] and line.detail["vote"] == {"A": [to_a, 0.0], "B": [to_b, 0.0]}
    assert line.score == min({"A": to_a, "B": to_b}[side], {"A": 8000, "B": 9000}[side])  # the weaker link
    no_night_to_flag(stub.calls, {P})
    assert logged(line)["checks"] == []  # a Chain is a measured line-up: nothing to check by eye


@pytest.mark.parametrize("vote, path", [
    ((1999, 5.0, 0.0), "fallback"), ((2000, 5.0, 0.0), "chain"),        # >= 2,000 points
    ((5000, 299.0, 0.0), "chain"), ((5000, 300.0, 0.0), "fallback"),    # shift p95 < 300 px
    ((5000, 0.0, 0.0), "chain"),
])
def test_the_chain_needs_2000_points_and_a_shift_under_300_px(tmp_path, vote, path):
    d = camera(tmp_path, NIGHT_CAM)
    stub = Stub({**MOVED, (P, A): vote, (P, B): 100})  # A wins the vote
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.status, line.detail["path"], line.anchor) == ("ok", path, A)
    if path == "chain":
        assert line.H[0, 2] == pytest.approx(0.2 + vote[1])  # H(A -> flag) . H(night -> A)
    else:  # Fallback: the nearer day photo (A), its own line-up, and the researcher log asks for a look
        assert line.H[0, 2] == pytest.approx(0.2) and line.detail["voted"] == "A"
        log = logged(line)
        assert (log["checks"], log["path"], log["side"], log["anchor"]) == (["moved"], "fallback", "A", A)


def test_the_chain_is_the_day_photos_line_up_after_the_night_photos_line_up_to_it(tmp_path):
    """H(night -> flag) = H(day -> flag) . H(night -> day), homographies mapping target pixels to reference pixels
    (folder 60: dayH[vote] @ nl[vote]). A scale then a shift does not commute, so the order shows."""
    d = camera(tmp_path, NIGHT_CAM)
    scale = np.diag([2.0, 2.0, 1.0])                               # A -> flag: twice the size
    shift = np.array([[1, 0, 10.0], [0, 1, -4.0], [0, 0, 1]])        # night -> A: 10 px right, 4 px up
    stub = Stub({**MOVED, (A, FLAG): scale, (P, A): shift, (P, B): 50})
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert line.detail["path"] == "chain"
    u, v = 100.0, 200.0
    q = line.H @ np.array([u, v, 1.0])
    assert (q[0] / q[2], q[1] / q[2]) == pytest.approx((2 * (u + 10), 2 * (v - 4)))  # shift first, then the scale


def test_a_weak_vote_falls_back_to_the_nearer_day_photo_not_the_voted_one(tmp_path):
    """MAS_CAM07 IMG_1915 (folder 60): night -> A 946 points wins the vote but is under 2,000, so the nearer is copied."""
    d = camera(tmp_path, {**NIGHT_CAM, P: ("2026:01:11 05:00:00", NIGHT)})  # B is nearer
    line = planner(Stub({**MOVED, (P, A): 946, (P, B): 239}), flag_cal(tmp_path)).plan(d / P)
    assert (line.detail["path"], line.detail["voted"], line.detail["side"], line.anchor) == ("fallback", "A", "B", B)
    assert line.score == 9000 and why(line) == ["could not find the ground under the animal, so no distance"]


# --- night photos: one side, the flag photos, none ------------------------------------------------------------------

def test_a_night_photo_with_one_day_photo_copies_it_and_the_move_is_not_checked(tmp_path):
    d = camera(tmp_path, {A: NIGHT_CAM[A], P: NIGHT_CAM[P]})
    stub = Stub(TO_FLAG)
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.status, line.detail["path"], line.anchor, line.score) == ("ok", "one_side", A, 8000)
    assert line.H[0, 2] == pytest.approx(0.2) and stub.calls == [(A, FLAG)]
    assert line.folder == lineup.folder_signature(d, "CAM")  # kept, so a day photo arriving later re-plans it
    log = logged(line)
    assert (log["checks"], log["path"], log["side"], log["anchor"]) == (["unchecked"], "one_side", "A", A)
    d2 = camera(tmp_path, {P: NIGHT_CAM[P], B: NIGHT_CAM[B]}, "cam2")
    late = flag_cal(tmp_path, "LATE.JPG", at="2026:02:01 10:00:00")  # the flag photo after everything: B side
    line = planner(Stub({(B, "LATE.JPG"): 9000}), late).plan(d2 / P)
    assert (line.detail["path"], line.detail["side"], line.anchor) == ("one_side", "B", B)


def test_at_the_start_of_a_deployment_the_flag_photo_is_day_photo_a(tmp_path):
    d = camera(tmp_path, {P: NIGHT_CAM[P], B: NIGHT_CAM[B]})  # no day photo before the night in the folder
    stub = Stub(TO_FLAG)
    cal = flag_cal(tmp_path, at="2026:01:10 20:00:00")  # set up 2 h before the night photo; B is 14 h after it
    line = planner(stub, cal).plan(d / P)
    assert (line.status, line.detail["path"], line.detail["before"], line.detail["after"]) == ("ok", "copy", FLAG, B)
    assert line.anchor == FLAG and np.allclose(line.H, np.eye(3)) and line.score is None  # its own line-up: identity
    assert line.detail["before_tries"] == [[FLAG, None]] and line.detail["move_points"] == 9000
    assert stub.calls == [(B, FLAG)]  # B -> A is B's own line-up to the flag photo: one call for both
    assert why(line) == ["could not find the ground under the animal, so no distance"] and logged(line)["checks"] == []


def test_a_moved_camera_with_the_flag_photo_as_a_votes_on_b_only(tmp_path):
    d = camera(tmp_path, {P: NIGHT_CAM[P], B: NIGHT_CAM[B]})
    stub = Stub({(B, FLAG): (9000, 40.0, 0.0)})  # B is 40 px off the flag photo: the camera moved
    line = planner(stub, flag_cal(tmp_path, at="2026:01:10 20:00:00")).plan(d / P)
    assert (line.detail["path"], line.anchor, line.detail["vote"]) == ("chain", B, {"B": [8000, 0.0]})
    no_night_to_flag(stub.calls, {P})


def test_at_the_end_of_a_deployment_a_later_flag_photo_is_day_photo_b(tmp_path, monkeypatch):
    d = camera(tmp_path, {A: NIGHT_CAM[A], P: ("2026:01:12 05:00:00", NIGHT)})  # no day photo after it
    later_flag(tmp_path, monkeypatch)  # FLAG2 at 01-12 09:00: 4 h after the night photo; A is 41 h before it
    stub = Stub({**TO_FLAG, ("FLAG2.JPG", FLAG): (7000, 0.5, 0.0)})
    cal = flag_cal(tmp_path)
    line = planner(stub, cal).plan(d / P)
    assert (line.detail["path"], line.detail["before"], line.detail["after"], line.anchor) == \
        ("copy", A, "FLAG2.JPG", "FLAG2.JPG")
    assert line.H[0, 2] == pytest.approx(0.5) and line.score == 7000  # FLAG2's line-up to the job's flag photo
    assert sorted(stub.calls) == sorted([(A, FLAG), ("FLAG2.JPG", FLAG), ("FLAG2.JPG", A)])  # B -> A: FLAG2 onto A
    moved = Stub({**TO_FLAG, ("FLAG2.JPG", FLAG): 7000, ("FLAG2.JPG", A): (9000, 50.0, 0.0)})
    line = planner(moved, cal, "another setting").plan(d / P)  # another setting: none of the links above are reused
    assert line.detail["vote"] == {"A": [8000, 0.0]} and line.detail["path"] == "chain"  # FLAG2 takes no part
    no_night_to_flag(moved.calls, {P})


def test_a_later_flag_photo_that_lines_up_poorly_is_a_rejected_try(tmp_path, monkeypatch):
    d = camera(tmp_path, {A: NIGHT_CAM[A], P: NIGHT_CAM[P]})
    later_flag(tmp_path, monkeypatch)
    line = planner(Stub({**TO_FLAG, ("FLAG2.JPG", FLAG): 3999}), flag_cal(tmp_path)).plan(d / P)
    assert (line.detail["path"], line.detail["after"], line.detail["after_tries"]) == \
        ("one_side", None, [["FLAG2.JPG", 3999]])


def test_a_flag_photo_of_another_pixel_size_does_not_stand_as_a_day_photo(tmp_path):
    """Its identity line-up maps the flag photo's pixels, not the night photo's; using it any other way would line the
    night photo up with the flag photo. So it is passed over: here B alone is copied."""
    d = tmp_path / "cam"
    d.mkdir()
    for n in (P, B):
        (d / n).write_bytes(shot(*NIGHT_CAM[n], size=(2048, 1152)))  # the flag photo is 1920 x 1080
    stub = Stub(TO_FLAG)
    line = planner(stub, flag_cal(tmp_path, at="2026:01:10 20:00:00")).plan(d / P)  # set up 2 h before the night
    assert (line.status, line.detail["path"], line.detail["before"], line.anchor) == ("ok", "one_side", None, B)
    assert line.detail["before_tries"] == [] and stub.calls == [(B, FLAG)]
    no_night_to_flag(stub.calls, {P})


def test_a_renamed_copy_of_a_flag_photo_in_the_folder_is_that_flag_photo_and_never_votes(tmp_path, monkeypatch):
    """A folder photo with a flag photo's capture time is that flag photo, whatever its name (Q10): IMG_9 is FLAG2
    copied into the card folder under the camera's own name."""
    later_flag(tmp_path, monkeypatch)  # FLAG2 at 01-12 09:00
    d = camera(tmp_path, {A: NIGHT_CAM[A], P: ("2026:01:12 05:00:00", NIGHT), "IMG_9.JPG": ("2026:01:12 09:00:00", DAY)})
    stub = Stub({**TO_FLAG, ("FLAG2.JPG", FLAG): 7000, ("FLAG2.JPG", A): (9000, 50.0, 0.0)})  # moved: the vote runs
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.detail["after"], line.detail["vote"], line.detail["path"]) == ("FLAG2.JPG", {"A": [8000, 0.0]}, "chain")
    assert not [c for c in stub.calls if "IMG_9.JPG" in c]
    no_night_to_flag(stub.calls, {P})


def test_a_night_photo_with_no_day_photo_and_no_dated_flag_photo_gets_no_distance(tmp_path):
    d = camera(tmp_path, {P: NIGHT_CAM[P]})
    line = planner(Stub(), flag_cal(tmp_path, at=None)).plan(d / P)
    assert (line.status, line.H, line.score, line.detail["why"]) == ("none", None, None, "no_day")
    assert line.folder == lineup.folder_signature(d, "CAM")
    assert why(line) == ["night photo with no day photo before or after it to measure through (a day photo of this "
                         "camera must line up with the flag photo with 4,000 points; 3 tried a side), so no distance"]
    assert logged(line)["checks"] == []  # no number to check; the reason above says why


# --- photos with no capture time (Q13) ------------------------------------------------------------------------------

def test_an_undated_night_photo_is_placed_by_its_file_number(tmp_path):
    d = camera(tmp_path, {"IMG_0004.JPG": ("2026:01:10 12:00:00", DAY), "IMG_0005.JPG": (None, NIGHT),
                          "IMG_0006.JPG": (None, NIGHT), "IMG_0007.JPG": ("2026:01:11 12:00:00", DAY)})
    stub = Stub()
    plan = planner(stub, flag_cal(tmp_path))
    five, six = plan.plan(d / "IMG_0005.JPG"), plan.plan(d / "IMG_0006.JPG")
    assert (five.detail["order"], five.detail["before"], five.detail["after"]) == ("number", "IMG_0004.JPG", "IMG_0007.JPG")
    # no time to measure a gap in: the nearer side is the one fewer photos away (IMG_0005: A; IMG_0006: B)
    assert (five.detail["gap_unit"], five.anchor, six.anchor) == ("photos", "IMG_0004.JPG", "IMG_0007.JPG")
    log = logged(five)
    assert (log["checks"], log["path"], log["side"], log["anchor"]) == (["undated"], "copy", "A", "IMG_0004.JPG")


def test_a_counter_that_restarted_falls_back_to_file_modification_time(tmp_path):
    d = camera(tmp_path, {"IMG_0009.JPG": ("2026:01:10 12:00:00", DAY), "IMG_0005.JPG": (None, NIGHT),
                          "IMG_0002.JPG": ("2026:01:11 12:00:00", DAY)})  # 0002 after 0009: the counter restarted
    t0 = 1_700_000_000 * 10**9
    for i, n in enumerate(("IMG_0009.JPG", "IMG_0005.JPG", "IMG_0002.JPG")):
        os.utime(d / n, ns=(t0 + i * 10**9, t0 + i * 10**9))
    line = planner(Stub(), flag_cal(tmp_path, at=None)).plan(d / "IMG_0005.JPG")
    assert (line.detail["order"], line.detail["before"], line.detail["after"]) == ("mtime", "IMG_0009.JPG", "IMG_0002.JPG")
    assert line.status == "ok" and "undated" in logged(line)["checks"]


def test_one_undated_photo_does_not_reorder_the_dated_photos_even_after_a_counter_restart(tmp_path):
    """Q13 places only the undated photo; the dated ones stay in capture-time order. Here the number cannot place
    IMG_0005 (the restart puts IMG_0002 after IMG_0010), so it goes by file time, after IMG_0002 (copied first)."""
    d = camera(tmp_path, {"IMG_0009.JPG": ("2026:01:10 12:00:00", DAY), "IMG_0010.JPG": ("2026:01:10 22:00:00", NIGHT),
                          "IMG_0002.JPG": ("2026:01:11 12:00:00", DAY),  # the counter restarted after IMG_0010
                          "IMG_0005.JPG": (None, NIGHT)})
    t0 = 1_700_000_000 * 10**9
    for i, n in enumerate(("IMG_0002.JPG", "IMG_0005.JPG", "IMG_0009.JPG", "IMG_0010.JPG")):  # copied in name order
        os.utime(d / n, ns=(t0 + i * 10**9, t0 + i * 10**9))
    plan = planner(Stub(), flag_cal(tmp_path, at=None))
    cam = plan.camera(d / "IMG_0010.JPG")
    assert [q.name for q in cam.order] == ["IMG_0009.JPG", "IMG_0010.JPG", "IMG_0002.JPG", "IMG_0005.JPG"]
    assert cam.placed[d / "IMG_0010.JPG"] == "time" and cam.placed[d / "IMG_0005.JPG"] == "mtime"
    dated = plan.plan(d / "IMG_0010.JPG")
    assert (dated.detail["order"], dated.detail["before"], dated.detail["after"], dated.detail["gap_unit"]) == \
        ("time", "IMG_0009.JPG", "IMG_0002.JPG", "s")
    assert logged(dated)["checks"] == []  # it and both its day photos are dated: nothing to check
    undated = plan.plan(d / "IMG_0005.JPG")
    assert (undated.detail["order"], undated.detail["before"], undated.detail["after"]) == ("mtime", "IMG_0002.JPG", None)
    assert logged(undated)["checks"] == ["unchecked", "undated"]


def test_checks_combine_in_one_researcher_log_line(tmp_path):
    d = camera(tmp_path, {"IMG_0004.JPG": ("2026:01:10 12:00:00", DAY), "IMG_0005.JPG": (None, NIGHT)})
    line = planner(Stub(), flag_cal(tmp_path)).plan(d / "IMG_0005.JPG")
    assert logged(line)["checks"] == ["unchecked", "undated"]


# --- kept in the store, and the same every time -------------------------------------------------------------

def test_a_later_run_reuses_the_links_and_gets_the_same_answer(tmp_path, monkeypatch):
    d = camera(tmp_path, NIGHT_CAM)
    cal = flag_cal(tmp_path)
    first = planner(Stub(MOVED), cal).plan(d / P)  # a Chain: night -> day links are kept too
    again = planner(never(), cal).plan(d / P)
    assert (again.status, again.anchor, again.score, again.detail) == (first.status, first.anchor, first.score, first.detail)
    assert np.allclose(again.H, first.H)
    monkeypatch.setattr(lineup, "VERSION", lineup.VERSION + 1)  # new rules re-plan from the links kept under LINK_VERSION
    assert np.allclose(planner(never(), cal).plan(d / P).H, first.H)


def test_a_link_is_measured_again_when_one_of_its_files_changes(tmp_path):
    d = camera(tmp_path, NIGHT_CAM)
    cal = flag_cal(tmp_path)
    planner(Stub(TO_FLAG), cal).plan(d / P)
    (d / B).write_bytes(shot("2026:01:11 12:00:00", DAY, colour=(91, 120, 60)))  # B edited: its links are not facts any more
    st = (d / B).stat()
    os.utime(d / B, ns=(st.st_atime_ns, st.st_mtime_ns + 10**10))  # a later mtime, whatever the clock's resolution
    stub = Stub(TO_FLAG)
    planner(stub, cal).plan(d / P)
    assert sorted(stub.calls) == sorted([(B, FLAG), (B, A)])


def test_a_link_is_measured_again_under_another_fidelity_or_weights_version(tmp_path):
    d = camera(tmp_path, NIGHT_CAM)
    cal = flag_cal(tmp_path)
    kept = "research upsample 864 weights v1"
    planner(Stub(TO_FLAG), cal, kept).plan(d / P)
    planner(never(), cal, kept).plan(d / P)  # the same setting: the kept links
    for setting in ("research upsample 864 weights v2", "fast upsample 672 weights v1"):
        stub = Stub(TO_FLAG)
        planner(stub, cal, setting).plan(d / P)
        assert sorted(stub.calls) == sorted([(A, FLAG), (B, FLAG), (B, A)]), setting


def test_a_day_photo_that_will_not_decode_is_a_rejected_try_and_is_not_decoded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)  # Pillow's default
    d = camera(tmp_path, {"IMG_0.JPG": ("2026:01:10 09:00:00", DAY), **NIGHT_CAM})  # 13 h before P; A is 10 h
    cal = flag_cal(tmp_path)
    cut(d / A)
    line = planner(Decoding(TO_FLAG), cal).plan(d / P)
    assert (line.status, line.detail["before"]) == ("ok", "IMG_0.JPG")  # A: a rejected try
    assert line.detail["before_tries"] == [[A, 0], ["IMG_0.JPG", 8000]]
    stamps = (d / A).stat().st_mtime_ns, Path(cal["ref_path"]).stat().st_mtime_ns
    assert store.link(str(d / A), cal["ref_path"], "research", lineup.LINK_VERSION, *stamps) == (None, 0, None)
    assert planner(never(), cal).plan(d / P).detail["before"] == "IMG_0.JPG"  # kept: the broken file is not decoded again
    (d / A).write_bytes(shot(*NIGHT_CAM[A]))  # copied again, whole
    st = (d / A).stat()
    os.utime(d / A, ns=(st.st_atime_ns, st.st_mtime_ns + 10**10))
    stub = Decoding(TO_FLAG)
    assert planner(stub, cal).plan(d / P).anchor == A and (A, FLAG) in stub.calls


def test_a_photo_that_was_locked_gives_a_failed_link_that_is_not_kept(tmp_path):
    d = camera(tmp_path, NIGHT_CAM)
    cal = flag_cal(tmp_path)
    line = planner(Locked(A, TO_FLAG), cal).plan(d / P)
    assert (line.status, line.detail["before"]) == ("ok", FLAG)  # the run goes on: the flag photo stands as A
    stub = Stub(TO_FLAG)
    assert planner(stub, cal).plan(d / P).anchor == A and (A, FLAG) in stub.calls  # asked again next run


# --- read just now: day or night, or the folder ------------------------------------------------------------------

def test_a_photo_whose_day_or_night_cannot_be_read_now_is_not_lined_up_at_all(tmp_path, monkeypatch):
    """Not direct (it may be a night photo: that would be a night -> flag link, Q10) and not kept as a day photo:
    UNREAD, so the run keeps no answer and the next run reads it again."""
    d = camera(tmp_path, NIGHT_CAM)
    read = lineup.read_night
    monkeypatch.setattr(lineup, "read_night", lambda q: None if q.name == P else read(q))  # locked, half copied
    stub = Stub(TO_FLAG)
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)
    assert (line.source, line.status, line.H, line.score, line.night) == ("unknown", "unread", None, None, None)
    assert stub.calls == []  # no link at all, so none to the flag photo
    assert store.night(str(d / P), (d / P).stat().st_size, (d / P).stat().st_mtime_ns) == (False, None)  # not kept


def test_a_folder_that_cannot_be_listed_gives_no_answer_and_is_planned_again(tmp_path, monkeypatch):
    d = camera(tmp_path, NIGHT_CAM)
    listing_ = measure.jpegs

    def jpegs(folder):
        if folder == d:
            raise ValueError(f"Could not read {folder}: the share dropped")
        return listing_(folder)

    monkeypatch.setattr(measure, "jpegs", jpegs)
    stub = Stub(TO_FLAG)
    line = planner(stub, flag_cal(tmp_path)).plan(d / P)  # the run goes on
    assert (line.status, line.H, line.detail["why"], line.folder) == ("none", None, "no_folder", lineup.NO_LISTING)
    assert stub.calls == [] and why(line) == [
        "night photo whose folder could not be read to find a day photo to measure through, so no distance "
        "(tried again on the next run)"]
    stored = {**KNOWN, "path": str(d / P), "match_score": None, "alignment_version": lineup.VERSION, "night": 1,
              "align_folder": line.folder}
    assert not measure.current_answer(stored, CAL, "md", "research", lineup.Check())  # out of date: planned again
    monkeypatch.setattr(measure, "jpegs", listing_)
    assert not measure.current_answer(stored, CAL, "md", "research", lineup.Check())


# --- which stored answers are current -------------------------------------------------------------------------

CAL = {"site": "CAM", "image_name": FLAG, "updated_at": "v1"}
KNOWN = {"method": "md", "fidelity": "research", "site": "CAM", "calibration_image": FLAG, "calibration_version": "v1"}


def test_an_answer_from_an_earlier_line_up_version_is_measured_again_only_for_a_night_photo():
    old = {**KNOWN, "match_score": 9000}
    assert measure.current_answer({**old, "night": 0}, CAL, "md", "research")       # a day photo: lined up as before
    assert not measure.current_answer({**old, "night": 1}, CAL, "md", "research")   # a night photo: measured again
    assert not measure.current_answer(old, CAL, "md", "research")  # not read yet: a listing calls it out of date
    assert measure.current_answer({**KNOWN, "match_score": None}, CAL, "md", "research")  # no animal, no line-up
    assert measure.current_answer({**old, "night": 1, "alignment_version": lineup.VERSION}, CAL, "md", "research")
    first = {**KNOWN, "alignment_version": 1}  # the first bracket design (5 px, 5,000 points)
    assert not measure.current_answer({**first, "night": 1, "match_score": None}, CAL, "md", "research")  # "moved"
    assert not measure.current_answer({**first, "night": 1, "match_score": 9000}, CAL, "md", "research")
    assert measure.current_answer({**first, "night": 0, "match_score": 9000}, CAL, "md", "research")
    assert measure.current_answer({**first, "night": None, "match_score": None}, CAL, "md", "research")  # empty frame


def test_a_run_reads_once_whether_an_old_answer_was_a_night_photo_and_keeps_it(tmp_path):
    d = camera(tmp_path, NIGHT_CAM)
    for n in (A, P):
        store.record({"path": str(d / n), "site": "CAM", "captured_at": None, "make": None, "model": None,
                      "calibration_image": FLAG, "held_reason": None, "match_score": 9000,
                      "calibration_version": "v1", "fidelity": "research"}, "md", [])
    known = {p["path"]: p for p in store.photos()}
    chk = lineup.Check(read=True)
    assert measure.current_answer(known[str(d / A)], CAL, "md", "research", chk)
    assert not measure.current_answer(known[str(d / P)], CAL, "md", "research", chk)
    assert {p["path"]: (p["night"], p["alignment_version"]) for p in store.photos()} == \
        {str(d / A): (0, None), str(d / P): (1, None)}  # kept: the next listing knows without opening the photo
    assert measure.current_answer({p["path"]: p for p in store.photos()}[str(d / A)], CAL, "md", "research")


def test_an_old_answer_whose_photo_cannot_be_read_is_not_kept_as_a_day_photo(tmp_path):
    d = camera(tmp_path, {A: NIGHT_CAM[A]})
    whole = (d / A).read_bytes()
    (d / A).write_bytes(b"not a jpeg yet")  # half copied, or locked, when the run looks at it
    store.record({"path": str(d / A), "site": "CAM", "captured_at": None, "make": None, "model": None,
                  "calibration_image": FLAG, "held_reason": None, "match_score": 9000,
                  "calibration_version": "v1", "fidelity": "research"}, "md", [])

    def old():
        return next(p for p in store.photos() if p["path"] == str(d / A))

    assert not measure.current_answer(old(), CAL, "md", "research", lineup.Check(read=True))  # out of date this run
    assert old()["night"] is None  # nothing kept: the next run reads it again
    (d / A).write_bytes(whole)
    assert measure.current_answer(old(), CAL, "md", "research", lineup.Check(read=True))  # a day photo after all
    assert old()["night"] == 0


def test_a_one_sided_answer_is_planned_again_once_its_folder_or_the_flag_photos_change(tmp_path, monkeypatch):
    d = camera(tmp_path, {A: NIGHT_CAM[A], P: NIGHT_CAM[P]})
    line = planner(Stub(), flag_cal(tmp_path)).plan(d / P)
    one = {**KNOWN, "path": str(d / P), "match_score": 8000, "alignment_version": lineup.VERSION,
           "align_folder": line.folder}
    ok = {**one, "align_folder": None}  # a two-sided answer keeps no folder state
    assert measure.current_answer(one, CAL, "md", "research") and measure.current_answer(ok, CAL, "md", "research")
    (d / B).write_bytes(shot(*NIGHT_CAM[B]))  # the next card brings the day photo after it
    assert not measure.current_answer(one, CAL, "md", "research", lineup.Check())
    assert measure.current_answer(ok, CAL, "md", "research", lineup.Check())
    one["align_folder"] = lineup.folder_signature(d, "CAM")
    assert measure.current_answer(one, CAL, "md", "research", lineup.Check())
    later_flag(tmp_path, monkeypatch)  # a service visit's flag photo is synced
    assert not measure.current_answer(one, CAL, "md", "research", lineup.Check())


# --- the whole run on FakeModels --------------------------------------------------------------------------------

SITE, SITE_FLAG = "TON_CAM02", "IMG_5304.JPG"  # the synced flag photo is dated 2026-03-13 (conftest), before RUN_CAM
RUN_CAM = {"IMG_0001.JPG": ("2026:05:01 12:00:00", DAY),
           "IMG_0002.JPG": ("2026:05:01 22:00:00", NIGHT),   # 10 h after IMG_0001, 14 h before IMG_0005
           "IMG_0003.JPG": ("2026:05:02 05:00:00", NIGHT),   # 7 h before IMG_0005
           "IMG_0004.JPG": ("2026:05:02 05:10:00", NIGHT),   # empty
           "IMG_0005.JPG": ("2026:05:02 12:00:00", DAY)}
RUN_NIGHTS = {"IMG_0002.JPG", "IMG_0003.JPG", "IMG_0004.JPG"}
RUN_BOXES = {"IMG_0004.JPG": []}


def fake_models(**kw) -> inference.FakeModels:
    return inference.FakeModels(boxes={**RUN_BOXES, **kw.get("boxes", {})}, links=kw.get("links"),
                                weights=kw.get("weights", "test"))


def links_of(models: inference.FakeModels) -> list[tuple]:
    return [c[1:] for c in models.calls if c[0] == "link"]


def wait(c: TestClient, timeout=10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = c.get("/api/run").json()
        if st["status"] != "running":
            return st
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def run(c: TestClient, d: Path, **more) -> dict:
    r = c.post("/api/run", json={"folder": str(d), "site": SITE, "flag": SITE_FLAG, "method": "md", **more})
    assert r.status_code == 200, r.text
    st = wait(c)
    assert st["status"] == "done", st
    return st


def answers(path: Path) -> dict:
    """What the store says about one photo: the photo row's line-up and every detection's numbers."""
    ph = next(p for p in store.photos() if p["path"] == str(path))
    dets = [{k: d[k] for k in ("distance_m", "q05_m", "q95_m", "match_score")}
            for d in store.detections() if d["path"] == str(path)]
    return {"photo": {k: ph[k] for k in ("calibration_image", "match_score", "alignment_version", "night", "align_source",
                                        "align_status", "anchor", "align_detail", "align_folder")}, "detections": dets}


def detail(path: Path) -> dict:
    return json.loads(answers(path)["photo"]["align_detail"])


def listing(c: TestClient, d: Path) -> dict:
    return {r["name"]: r for r in c.get("/api/folder", params={"path": str(d), "site": SITE, "flag": SITE_FLAG}).json()["rows"]}


def export_rows(c: TestClient, **params) -> list[dict]:
    import csv
    text = c.get("/api/export.csv", params=params).text
    return list(csv.DictReader(l for l in text.splitlines() if not l.startswith("#")))


@pytest.fixture
def full_flag(synced):
    """The synced flag photo at the camera's pixel size (conftest's is 2 x 2 px), so it can stand as day photo A."""
    store.ref_path(SITE, SITE_FLAG).write_bytes(shot("2026:03:13 12:37:33", DAY))
    return synced


def test_the_run_copies_a_day_line_up_for_night_photos_and_never_lines_them_up_with_the_flag_photo(synced, tmp_path, monkeypatch):
    models = fake_models()
    monkeypatch.setattr(inference, "backend", models)
    d = camera(tmp_path, RUN_CAM, SITE)
    run(synced, d)
    stage_two = models.calls.index(("release", True, False))
    assert all(c[0] != "detect" for c in models.calls[stage_two:])  # the detector is never asked back
    assert all(c[0] != "link" for c in models.calls[:stage_two])
    links = links_of(models)
    assert not [x for x in links if x[0] in RUN_NIGHTS or x[1] in RUN_NIGHTS]  # Copy: no night photo is lined up
    assert links.count(("IMG_0001.JPG", SITE_FLAG)) == 1  # the day photo is lined up once for all three
    day, before, after = (answers(d / n) for n in ("IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"))
    assert (day["photo"]["align_source"], day["photo"]["night"]) == ("direct", 0)
    assert (before["photo"]["align_source"], before["photo"]["align_status"], before["photo"]["anchor"]) == \
        ("night", "ok", "IMG_0001.JPG")
    assert after["photo"]["anchor"] == "IMG_0005.JPG" and detail(d / "IMG_0002.JPG")["path"] == "copy"
    assert before["photo"]["match_score"] == day["photo"]["match_score"] == 8000  # the day photo's points
    assert before["detections"][0]["distance_m"] is not None and before["photo"]["align_folder"] is None
    assert before["photo"]["alignment_version"] == lineup.VERSION == 2
    rows = listing(synced, d)
    assert rows["IMG_0002.JPG"]["align_source"] == "night" and rows["IMG_0002.JPG"]["reasons"] == []
    assert not any(r["stale"] for r in rows.values())
    got = {r["photo"]: r for r in export_rows(synced)}
    assert "lineup" not in got["IMG_0002.JPG"] and "check" not in got["IMG_0002.JPG"]  # the check is in the log only


def test_the_researcher_log_records_each_measured_photo_in_the_apps_logs_folder(synced, tmp_path, monkeypatch):
    """One log (user decision 2026-10-11): one line per photo measured, day or night; a night answer carries the
    Night-rule detail under `night`. A run that skips current answers writes nothing more."""
    monkeypatch.setattr(inference, "backend", fake_models())
    d = camera(tmp_path, RUN_CAM, SITE)
    run(synced, d)
    log = store.DATA_DIR / "logs" / lineup.LOG_NAME
    rows = {Path(r["photo"]).name: r for r in map(json.loads, log.read_text().splitlines())}
    assert len(log.read_text().splitlines()) == len(rows) == len(RUN_CAM)  # every photo, once
    r = rows["IMG_0002.JPG"]
    assert (r["camera"], r["status"], r["day_night"], r["distance"], r["animals"], r["reasons"]) == \
        (SITE, "measured", "night", True, 1, [])
    n = r["night"]
    assert (n["path"], n["flag"], n["before"], n["after"], n["anchor"], n["score"]) == \
        ("copy", SITE_FLAG, "IMG_0001.JPG", "IMG_0005.JPG", "IMG_0001.JPG", 8000)
    assert n["move_points"] == 8000 and n["move_px"] is not None and n["before_tries"] == [["IMG_0001.JPG", 8000]]
    day = rows["IMG_0001.JPG"]
    assert (day["day_night"], day["distance"], day["reasons"]) == ("day", True, []) and "night" not in day
    empty = rows["IMG_0004.JPG"]  # an empty night frame: never lined up, its day or night read from the Flash tag
    assert (empty["animals"], empty["distance"], empty["day_night"], empty["reasons"]) == (0, False, "night", [])
    assert "night" not in empty  # no Night-rule detail: it was not lined up
    run(synced, d)  # nothing is out of date: every photo is skipped
    assert len(log.read_text().splitlines()) == len(RUN_CAM)
    assert not list(d.glob("*.jsonl")) and not list(d.parent.glob("*.jsonl"))  # never beside the photos or an export
    launcher = tmp_path / "app" / "logs" / "launcher.log"
    monkeypatch.setenv("CAMTRAP_LAUNCHER_LOG", str(launcher))  # the installed app: its own logs\ folder
    assert lineup.log_dir() == launcher.parent


def test_a_researcher_log_that_cannot_be_written_never_stops_a_run(monkeypatch, capsys):
    def broken():
        raise RuntimeError("no logs folder today")

    monkeypatch.setattr(lineup, "log_dir", broken)
    measure._log_measured(Path("IMG_0002.JPG"), "CAM", {}, [], {"night": True, "status": "ok",
                                                                 "detail": {"path": "copy"}})  # does not raise
    assert "research log not written: no logs folder today" in capsys.readouterr().err


def test_a_day_photo_with_a_reason_gets_a_log_line_with_that_reason(synced, tmp_path, monkeypatch):
    """The reasons are written only to the researcher log (user decision 2026-10-11), as report.reasons words them."""
    monkeypatch.setattr(inference, "backend", fake_models(links={("IMG_0001.JPG", SITE_FLAG): 9}))  # under 15 points
    d = camera(tmp_path, {"IMG_0001.JPG": RUN_CAM["IMG_0001.JPG"]}, SITE)
    run(synced, d)
    [line] = log_lines()
    assert (line["status"], line["day_night"], line["distance"], line["animals"]) == ("measured", "day", True, 1)
    assert line["reasons"] == ["lines up poorly with its flag photo (9 points, needs 15). Wrong camera, or was it moved?"]


def test_a_clean_day_photo_gets_a_log_line_with_no_reasons_and_a_skipped_one_gets_none(synced, tmp_path, monkeypatch):
    monkeypatch.setattr(inference, "backend", fake_models())
    d = camera(tmp_path, {"IMG_0001.JPG": RUN_CAM["IMG_0001.JPG"]}, SITE)
    run(synced, d)
    [line] = log_lines()
    assert (line["photo"], line["camera"], line["day_night"], line["reasons"]) == (str(d / "IMG_0001.JPG"), SITE, "day", [])
    run(synced, d)  # current: skipped, no new line
    assert len(log_lines()) == 1


def test_an_unreadable_file_gets_one_log_line(synced, tmp_path, monkeypatch):
    monkeypatch.setattr(inference, "backend", fake_models())
    d = camera(tmp_path, {"IMG_0001.JPG": RUN_CAM["IMG_0001.JPG"]}, SITE)
    (d / "IMG_0009.JPG").write_bytes(b"not a jpeg")
    assert run(synced, d)["unreadable"] == 1
    bad = [r for r in log_lines() if r["status"] == "unreadable"]
    assert [(Path(r["photo"]).name, r["camera"], r["reasons"]) for r in bad] == \
        [("IMG_0009.JPG", SITE, [report.UNREADABLE])]
    assert [Path(r["photo"]).name for r in log_lines() if r["status"] == "measured"] == ["IMG_0001.JPG"]


def test_a_night_photo_between_day_photos_that_moved_is_chained_through_the_winning_day_photo(synced, tmp_path, monkeypatch):
    moved = {("IMG_0005.JPG", "IMG_0001.JPG"): (9000, 0.0, 30.0),  # the camera dropped 30 px during the night
             ("IMG_0002.JPG", "IMG_0001.JPG"): (6000, 0.0, 2.0), ("IMG_0002.JPG", "IMG_0005.JPG"): (3000, 0.0, -28.0),
             ("IMG_0003.JPG", "IMG_0001.JPG"): 500, ("IMG_0003.JPG", "IMG_0005.JPG"): 1500}
    models = fake_models(links=moved)
    monkeypatch.setattr(inference, "backend", models)
    d = camera(tmp_path, RUN_CAM, SITE)
    run(synced, d)
    links = links_of(models)
    no_night_to_flag(links, RUN_NIGHTS, {SITE_FLAG})
    assert ("IMG_0004.JPG", "IMG_0001.JPG") not in links  # an empty frame is never lined up
    chained, fell = answers(d / "IMG_0002.JPG"), answers(d / "IMG_0003.JPG")
    assert (detail(d / "IMG_0002.JPG")["path"], chained["photo"]["anchor"], chained["photo"]["match_score"]) == \
        ("chain", "IMG_0001.JPG", 6000)
    assert (detail(d / "IMG_0003.JPG")["path"], fell["photo"]["anchor"]) == ("fallback", "IMG_0005.JPG")  # nearer
    assert chained["detections"][0]["distance_m"] is not None and fell["detections"][0]["distance_m"] is not None
    rows = listing(synced, d)
    assert rows["IMG_0003.JPG"]["reasons"] == [] and not any(r["stale"] for r in rows.values())  # no UI mark
    log = {Path(r["photo"]).name: r["night"] for r in log_lines() if "night" in r}
    assert {n: (r["checks"], r["path"], r["side"], r["anchor"]) for n, r in log.items()} == \
        {"IMG_0002.JPG": ([], "chain", "A", "IMG_0001.JPG"), "IMG_0003.JPG": (["moved"], "fallback", "B", "IMG_0005.JPG")}
    got = export_rows(synced)
    assert {r["photo"] for r in got} == {"IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG", "IMG_0005.JPG"}
    assert "check" not in got[0]  # the camera move is in the researcher log only (user decision 2026-10-11)


def test_with_the_flag_photo_as_day_photo_a_the_run_still_never_links_a_night_photo_to_it(full_flag, tmp_path, monkeypatch):
    models = fake_models(links={("IMG_0005.JPG", SITE_FLAG): (9000, 25.0, 0.0)})  # moved since the flag photo
    monkeypatch.setattr(inference, "backend", models)
    d = camera(tmp_path, {n: v for n, v in RUN_CAM.items() if n != "IMG_0001.JPG"}, SITE)  # the deployment's start
    run(full_flag, d)
    no_night_to_flag(links_of(models), RUN_NIGHTS, {SITE_FLAG})
    got = detail(d / "IMG_0002.JPG")
    assert (got["before"], got["after"], got["path"], got["vote"]) == \
        (SITE_FLAG, "IMG_0005.JPG", "chain", {"B": [8000, got["vote"]["B"][1]]})


def test_a_night_photo_that_copies_the_flag_photo_itself_is_exported_and_its_check_is_only_in_the_log(
        full_flag, tmp_path, monkeypatch):
    """Follow-up F, after the user decisions of 2026-10-11 (the window's "Lines up" line and the export's `check`
    column are gone). The flag photo's own line-up is the identity, so the night photo has a distance but no points of
    its own (match_score empty, review fix 10). The export writes the number; what to check by eye (only one day
    photo, so the camera move was not checked) is in the researcher log and nowhere else."""
    monkeypatch.setattr(inference, "backend", fake_models())
    d = camera(tmp_path, {n: RUN_CAM[n] for n in ("IMG_0002.JPG", "IMG_0003.JPG")}, SITE)  # no day photo: flag is A
    run(full_flag, d)
    row = {r["photo"]: r for r in export_rows(full_flag)}["IMG_0002.JPG"]
    assert row["distance_m"] != "" and "check" not in row
    assert listing(full_flag, d)["IMG_0002.JPG"]["match_score"] is None  # no points of its own, not a failed line-up
    r = next(r["night"] for r in log_lines() if r["photo"].endswith("IMG_0002.JPG"))
    assert (r["checks"], r["path"], r["side"], r["anchor"], r["score"]) == (["unchecked"], "one_side", "A", SITE_FLAG, None)


def test_a_night_photo_with_no_answer_is_exported_without_a_distance_and_empty_frames_are_not_rows(synced, tmp_path,
                                                                                                 monkeypatch):
    """Follow-up F, option (a), after the user decisions of 2026-10-11: the export holds every result row. A night
    photo with no day photo on either side is a row with an empty distance. A photo with no animal (day or night)
    is no row at all; the window lists it as measured with no animal (`detections` empty)."""
    monkeypatch.setattr(inference, "backend", fake_models(boxes={"IMG_0001.JPG": []},
                                                          links={("IMG_0001.JPG", SITE_FLAG): 100}))  # too few for A
    d = camera(tmp_path, {n: RUN_CAM[n] for n in ("IMG_0001.JPG", "IMG_0002.JPG", "IMG_0004.JPG")}, SITE)
    run(synced, d)
    rows = listing(synced, d)
    for empty in ("IMG_0001.JPG", "IMG_0004.JPG"):  # a day and a night photo with no animal
        assert (rows[empty]["measured"], rows[empty]["detections"]) == (True, [])
    got = export_rows(synced)  # no day photo before IMG_0002 (100 points) or after it: no distance
    assert [(r["photo"], r["distance_m"], r["q05_m"], r["q95_m"]) for r in got] == [("IMG_0002.JPG", "", "", "")]


def test_a_day_photo_arriving_later_gives_the_one_sided_night_photos_a_checked_answer(synced, tmp_path, monkeypatch):
    first = fake_models()
    monkeypatch.setattr(inference, "backend", first)
    d = camera(tmp_path, {n: v for n, v in RUN_CAM.items() if n != "IMG_0005.JPG"}, SITE)  # the card copied in part
    run(synced, d)
    assert answers(d / "IMG_0002.JPG")["photo"]["align_status"] == "ok"
    assert detail(d / "IMG_0002.JPG")["path"] == "one_side"
    assert [(r["night"]["checks"], r["night"]["path"]) for r in log_lines() if r["photo"].endswith("IMG_0003.JPG")] == \
        [(["unchecked"], "one_side")]
    assert listing(synced, d)["IMG_0002.JPG"]["stale"] is False
    (d / "IMG_0005.JPG").write_bytes(shot(*RUN_CAM["IMG_0005.JPG"]))  # the rest of the card
    assert listing(synced, d)["IMG_0002.JPG"]["stale"] is True
    second = fake_models()
    monkeypatch.setattr(inference, "backend", second)
    st = run(synced, d)  # not a rerun: only what is out of date is measured
    measured = {c[1] for c in second.calls if c[0] == "detect"}
    assert measured == {"IMG_0002.JPG", "IMG_0003.JPG", "IMG_0005.JPG"} and st["skipped"] == 2  # IMG_0001, IMG_0004
    assert [answers(d / n)["photo"]["anchor"] for n in ("IMG_0002.JPG", "IMG_0003.JPG")] == ["IMG_0001.JPG", "IMG_0005.JPG"]
    assert all(detail(d / n)["path"] == "copy" for n in ("IMG_0002.JPG", "IMG_0003.JPG"))


def test_old_answers_measure_again_once_for_night_photos_and_never_for_day_photos(synced, tmp_path, monkeypatch):
    d = camera(tmp_path, RUN_CAM, SITE)
    cal = next(c for c in store.calibrations() if c["site"] == SITE)
    base = {"site": SITE, "captured_at": None, "make": None, "model": None, "calibration_image": SITE_FLAG,
            "held_reason": None, "calibration_version": cal["updated_at"], "fidelity": "research",
            "fit_version": cal["fit_version"]}
    for n in ("IMG_0001.JPG", "IMG_0002.JPG"):  # measured before ticket 33: no line-up fields at all
        store.record({**base, "path": str(d / n), "match_score": 37}, "md", [])
    # measured by the first bracket design (line-up version 1): a day photo, and a night photo it called "moved"
    store.record({**base, "path": str(d / "IMG_0005.JPG"), "match_score": 9000, "alignment_version": 1, "night": 0,
                  "align_source": "direct", "align_status": "ok"}, "md", [])
    store.record({**base, "path": str(d / "IMG_0003.JPG"), "match_score": None, "alignment_version": 1, "night": 1,
                  "align_source": "bracket", "align_status": "none", "align_detail": json.dumps({"why": "moved"})}, "md", [])
    models = fake_models()
    monkeypatch.setattr(inference, "backend", models)
    run(synced, d)
    assert {c[1] for c in models.calls if c[0] == "detect"} == {"IMG_0002.JPG", "IMG_0003.JPG", "IMG_0004.JPG"}
    day, night, v1 = answers(d / "IMG_0001.JPG"), answers(d / "IMG_0002.JPG"), answers(d / "IMG_0003.JPG")
    assert (day["photo"]["match_score"], day["photo"]["alignment_version"], day["photo"]["night"]) == (37, None, 0)
    assert (night["photo"]["align_source"], night["photo"]["alignment_version"]) == ("night", lineup.VERSION)
    assert (v1["photo"]["align_source"], v1["photo"]["align_status"], v1["photo"]["alignment_version"]) == \
        ("night", "ok", lineup.VERSION)  # the first design's "no distance" now has an answer
    assert answers(d / "IMG_0005.JPG")["photo"]["alignment_version"] == 1  # a version-1 day answer is kept
    monkeypatch.setattr(inference, "backend", fake_models())
    assert run(synced, d)["skipped"] == len(RUN_CAM)  # once only


def test_a_day_photo_that_will_not_decode_does_not_stop_the_run(full_flag, tmp_path, monkeypatch):
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)  # Pillow's default
    models = fake_models()
    monkeypatch.setattr(inference, "backend", models)
    d = camera(tmp_path, RUN_CAM, SITE)
    cut(d / "IMG_0001.JPG")
    run(full_flag, d, photos=[str(d / "IMG_0002.JPG")])  # the run finishes ("done"); the broken photo is a try only
    got = detail(d / "IMG_0002.JPG")
    assert (got["before"], got["after"], got["path"]) == (SITE_FLAG, "IMG_0005.JPG", "copy")  # the flag photo stands as A
    assert got["before_tries"][0] == ["IMG_0001.JPG", 0]
    assert answers(d / "IMG_0002.JPG")["detections"][0]["distance_m"] is not None
    assert ("link", "IMG_0001.JPG", SITE_FLAG) not in models.calls  # it never decoded, so RoMa was never asked


def test_a_night_photo_whose_day_or_night_cannot_be_read_now_keeps_no_answer_and_is_measured_next_run(synced, tmp_path,
                                                                                                    monkeypatch):
    read = lineup.read_night
    monkeypatch.setattr(lineup, "read_night", lambda q: None if q.name == "IMG_0002.JPG" else read(q))
    models = fake_models()
    monkeypatch.setattr(inference, "backend", models)
    d = camera(tmp_path, RUN_CAM, SITE)
    st = run(synced, d)
    assert st["unreadable"] == 1
    assert not [x for x in links_of(models) if "IMG_0002.JPG" in x]  # neither a direct nor a flag link
    assert str(d / "IMG_0002.JPG") not in {p["path"] for p in store.photos()}  # no answer kept, not night=0
    assert listing(synced, d)["IMG_0002.JPG"]["measured"] is False
    monkeypatch.setattr(lineup, "read_night", read)  # readable again
    monkeypatch.setattr(inference, "backend", fake_models())
    st = run(synced, d)
    assert st["skipped"] == len(RUN_CAM) - 1 and answers(d / "IMG_0002.JPG")["photo"]["align_source"] == "night"


def test_measure_again_after_a_weights_update_lines_the_photos_up_again(synced, tmp_path, monkeypatch):
    d = camera(tmp_path, RUN_CAM, SITE)
    monkeypatch.setattr(inference, "backend", fake_models())
    run(synced, d)
    same = fake_models()
    monkeypatch.setattr(inference, "backend", same)
    run(synced, d, rerun=True)
    assert not links_of(same)  # Measure again, the same weights: the kept links
    new = fake_models(weights="v2")
    monkeypatch.setattr(inference, "backend", new)
    run(synced, d, rerun=True)
    assert sorted(links_of(new)) == sorted(
        [("IMG_0001.JPG", SITE_FLAG), ("IMG_0005.JPG", SITE_FLAG), ("IMG_0005.JPG", "IMG_0001.JPG")])


def snapshot(src: Path, dst: Path) -> None:
    """A copy of the store as it was after Sync: each path starts with no links kept."""
    dst.mkdir()
    shutil.copy(src / "camtrap.db", dst / "camtrap.db")
    shutil.copytree(src / "refs", dst / "refs")


def test_a_night_photo_measured_alone_gets_the_answer_it_gets_with_its_folder(synced, tmp_path, monkeypatch):
    synced_dir = store.DATA_DIR
    d = camera(tmp_path, RUN_CAM, SITE)
    pick = d / "IMG_0003.JPG"
    got = {}
    for i, photos in enumerate((None, [str(pick)])):
        fresh = tmp_path / f"store{i}"
        snapshot(synced_dir, fresh)
        monkeypatch.setattr(store, "DATA_DIR", fresh)
        batch.SCANS.clear(), batch.CHOICES.clear(), batch._EXIF.clear()
        monkeypatch.setattr(inference, "backend", fake_models())
        run(TestClient(api.app), d, **({"photos": photos} if photos else {}))
        got[i] = answers(pick)
    assert got[0] == got[1] and got[0]["photo"]["anchor"] == "IMG_0005.JPG"
