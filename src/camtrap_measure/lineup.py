"""How each photo is lined up with its flag photo before the distance model reads it: the Night rule (ADR 0001) and
the day rule (ADR 0002).

A day photo lines up with the flag photo directly when its own line-up has a homography and DAY_WEAK points or more,
as before. A weaker day photo follows the day rule (below). A night IR photo does not: against the daytime colour
flag photo it gets a few dozen matching points (MAS_CAM07 IMG_0215: 34, where a day photo gets 9,465), and two frames
of one still deer read 6.6 m and 9.9 m. So a night photo is never lined up with the flag photo. It uses a day photo of
its camera instead:

1. Day photo A (before) and B (after): the nearest day photo on each side, in the same camera folder, whose line-up to
   the job's flag photo has DAY_MIN points or more (TRIES tries a side; a burst mate within BURST_S of a rejected try
   is skipped; no time limit). The camera's flag photos take part at their capture times: the job's flag photo is its
   own line-up (identity), and a later flag photo of the camera needs DAY_MIN points to the job's flag photo, like a
   day photo. So at the start of a deployment the flag photo is A, and at the end the next flag photo is B.
2. Both found: line B up onto A (the move check). Shift p95 <= SAME_PX with LINK_OK points or more: **Copy** the line-up
   of the nearer day photo (a tie goes to A).
3. Otherwise the camera moved: line the night photo up to A and to B; the side with more points wins (a tie goes to the
   nearer). If that night -> day line-up has CHAIN_MIN points or more and a shift p95 under CHAIN_PX: **Chain**,
   H(night -> flag) = H(day -> flag) . H(night -> day). Otherwise **Fallback**: copy the nearer day photo.
4. Only one found: Copy it. None found: no distance.

The day rule (ADR 0002, decided 2026-10-12) borrows the same way. A day photo whose own line-up has no
homography or fewer than DAY_WEAK points finds A and B as above (the photo itself is never its own neighbour), with
two changes (review, 2026-10-12): its own burst (photos within BURST_S of it) is tried first on each side, with no
burst-mate skip; and a flag photo stands as A or B only when the other side is a real day photo (the wrong-camera
guard). Both found: the move check, then Copy the nearer; on a move (or B -> A too weak to tell) there is no vote
and no Chain ("no chain"): Fallback, copy the nearer, with the check "moved". One found: Copy it. None found: keep the photo's own
line-up when it has a homography and DAY_KEEP points or more, else no distance. Why: a frame-filling animal hides the
background, and its own line-up breaks (8 verified weak frame-filling day photos, 86-2,339 points, shifted 400-5,300 px
against 20-120 px for strong neighbours; TON_CAM04 IMG_0982 / IMG_0981 read 9.30 / 10.48 m where their burst mates
read 11.18-11.40 m). 3.5% of 1,087 day animal photos are under 4,000 points (14% at a 50% box share or more), and 99.3%
of frame-filling day photos have a clearer photo within 120 s. Small animals at dawn or dusk with 1,122-4,000 points
were usually right (within about 30 px of strong neighbours), so with no neighbour an own line-up of 2,500 points or
more is kept. On a wrong camera (54-276 points) the neighbours fail too: no distance instead of a wrong one.

Every rule and threshold is from ../distance_estimation, experiments/refnet, and the design review of 2026-10-10/11
(its questions are cited as Q1-Q13 below; the decisions are in docs/adr/0001 for the Night rule and docs/adr/0002 for
the day rule):
  43_bracket_rule         Copy against the research night chain (Q1 median 0.017 m, p95 0.090 m)
  38_fleet_anchor_chain   the day-photo search (tries, burst mates) and the shift grid
  59_anchor_threshold     DAY_MIN 4,000 (Q6)
  60_vote_check           the vote, the Chain gate (2,000 points, 300 px) and the Fallback (Q8, Q9): with Chain +
                          Fallback, 0 of 896 box points with a strong reference are over 1 m.

Torch-free. The planner is handed the one model call it needs, `link(target, reference) -> (H, inliers)`, so the rules
are tested with stand-ins (tests/test_lineup.py) and the real backend supplies RoMa (inference.Real). Links are kept in
the store, so a later run, or one photo measured again, reuses them and gets the same answer.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from . import distance, store

VERSION = 2  # how photos are lined up; a stored answer from another version is measured again once (`current`).
             # 1 (2026-10-10): night photos borrowed a day photo's line-up when the day photos agreed within 5 px.
             # 2 (2026-10-11): the Night rule: 4,000 points, 20 px, Chain on a move, flag photos as day photos, no
             # "no distance" for a moved camera or a missing side. Day answers are the same under 1 and 2: kept.
             # Not bumped for the day rule (2026-10-12): a bump would measure every night answer again. The day
             # rule changes only a day answer lined up directly with fewer than DAY_WEAK points, and `current` calls
             # exactly those out of date, under any version.
LINK_VERSION = 1  # how one link is measured (seeded RoMa + MAGSAC, target -> reference, both banner-cropped; shift
                  # p95 over the target's cropped frame). Apart from VERSION: a link is a fact about two files, the
                  # same under any rule that uses it, so a rule change re-plans from the stored links.
DAY_MIN = 4000     # a day photo is A or B when it lines up with the flag photo this well (folder 59, Q6; was 5,000)
DAY_WEAK = DAY_MIN  # a day photo keeps its own line-up (direct) with a homography and this many points; else day rule
DAY_KEEP = 2500    # day rule, no A or B: the photo's own line-up is kept with a homography and this many points
SAME_PX = 20.0     # B onto A shifts by at most this (p95): the camera did not move between A and B (Q3a; was 5)
LINK_OK = 1000     # below this the B -> A shift is a guess (folder 38 sub-test D); read as "moved" (never seen, folder 58)
CHAIN_MIN = 2000   # a night -> day line-up the Chain may use has this many points or more (folder 60, Q8)
CHAIN_PX = 300.0   # ... and shifts the night photo by less than this (p95): more is a broken homography (folder 60)
TRIES = 3          # photos tried per side for a day photo
BURST_S = 120      # a photo this close in time to a rejected one is the same burst: skipped, not tried again
GREY_SAT = 0.05    # no Flash tag: a photo whose mean colour saturation is below this is a night IR photo
_FLASH, _EXIF_IFD = 0x9209, 0x8769
UNREADABLE = (OSError, ValueError, SyntaxError)  # what Pillow raises for a photo cut short by a copy, or corrupt
_UNREACHED = (FileNotFoundError, PermissionError)  # the file was not there or was locked: about the moment, not the file

DIRECT, NIGHT, UNKNOWN = "direct", "night", "unknown"  # Line.source: a day photo's own line-up; a night photo by the
                                                       # Night rule; neither, day or night could not be read just now
DAY_BORROW = "day_borrow"  # Line.source: a day photo by the day rule (its own line-up under DAY_WEAK points)
OK, NONE, UNREAD = "ok", "none", "unread"  # Line.status; UNREAD: not measurable this run, no answer kept (measure._job)
COPY, CHAIN, FALLBACK, ONE_SIDE = "copy", "chain", "fallback", "one_side"  # Line.detail["path"] of a borrowed answer
OWN = "own"  # Line.detail["path"] of a day-rule answer that kept its own line-up (no A or B, DAY_KEEP points or more)
NO_DAY, UNPLACED, NO_FOLDER = "no_day", "unplaced", "no_folder"  # Line.detail["why"]: no A or B was found or looked for
NO_LISTING = "unreadable"  # Line.folder of a NO_FOLDER answer: folder_signature never gives it, so it is planned again
# what a night answer asks a researcher to check by eye (Line.detail["checks"]); only the researcher log carries them
MOVED, UNCHECKED, UNDATED = "moved", "unchecked", "undated"
LOG_NAME = "research-log.jsonl"  # the one researcher log (Q12; a line per photo since 2026-10-11), in logs/


# --- facts about one photo ----------------------------------------------------------------------------------

def is_night(flash: int | None) -> bool | None:
    """EXIF Flash bit 0: the flash (the IR lamp on a trail camera) fired. Browning writes 13 at night, 16 by day."""
    return None if flash is None else bool(int(flash) & 1)


def grey(im: Image.Image) -> bool:
    """Is this picture without colour? A night IR photo is grey; daylight has colour even in snow."""
    hsv = np.asarray(im.convert("RGB").resize((64, 36)).convert("HSV"), np.float32)
    return float(hsv[..., 1].mean()) / 255 < GREY_SAT


def read_night(path: Path) -> bool | None:
    """Night (True) or day (False) from the EXIF Flash tag, else from the colour of a small thumbnail.
    None when the file cannot be read."""
    try:
        with Image.open(path) as im:
            flash = is_night(im.getexif().get_ifd(_EXIF_IFD).get(_FLASH))
            if flash is not None:
                return flash
            im.draft("RGB", (160, 90))  # a JPEG decodes at 1/8 size for this: a few ms, not the whole frame
            return grey(im)
    except Exception:
        return None


def shift_p95(Hm: np.ndarray, width: int, height: int) -> float:
    """How far a homography moves the photo: p95 of |H(p) - p| in px over a 40 px grid starting 20 px in, over the
    target's banner-cropped frame (folder 38 grid_disp; folders 43, 46 and 60 measured every shift this way)."""
    # ponytail: a photo under 40 px (a test stub) gets its centre
    us, vs = np.meshgrid(np.arange(min(20, width / 2), width, 40, dtype=float),
                         np.arange(min(20, height / 2), height, 40, dtype=float))
    p = np.stack([us.ravel(), vs.ravel(), np.ones(us.size)])
    q = Hm @ p
    return float(np.percentile(np.hypot(q[0] / q[2] - p[0], q[1] / q[2] - p[1]), 95))


def _seconds(at: str) -> float:
    """Capture time on one fixed clock: the camera's time has no zone, and only differences are read from it."""
    return (datetime.fromisoformat(at) - datetime(1970, 1, 1)).total_seconds()


def counter(name: str) -> int | None:
    """The camera's photo counter in a file name: the last run of digits (IMG_0215.JPG -> 215); None without one."""
    digits = re.findall(r"\d+", Path(name).stem)
    return int(digits[-1]) if digits else None


def flag_photos(site: str) -> list[dict]:
    """The camera's flag photos that can take part in the Night rule: usable calibrations with a capture time and their
    flag photo on this computer, each with its `ref_path`."""
    out = []
    for c in store.calibrations():
        if c["site"] == site and c["ok"] and c["captured_at"]:
            p = store.ref_path(c["site"], c["image_name"])
            if p.exists():
                out.append({**c, "ref_path": str(p)})
    return out


def folder_signature(folder: Path, site: str | None = None) -> str:
    """The photos of a folder as they are now (how many, the newest modification time) and the camera's flag photos.
    A photo added, removed or changed, or a flag photo synced, gives another signature; "" when the folder cannot be
    read. Kept on an answer that lacks a day photo on a side, so one arriving later re-plans it."""
    from . import measure  # measure imports this module

    try:
        files = measure.jpegs(folder)
    except ValueError:
        return ""
    stamps = []
    for p in files:
        try:
            stamps.append(p.stat().st_mtime_ns)
        except OSError:
            pass
    flags = ",".join(sorted(c["image_name"] for c in flag_photos(site))) if site else ""
    return f"{len(files)}:{max(stamps, default=0)}|{flags}"


# --- a camera folder, in time order -------------------------------------------------------------------------

class Camera:
    """The photos of one camera folder on disk, in time order, with the camera's flag photos at their capture times:
    what A and B are looked for among, whichever photos the run was asked for. Capture dates come from the store's
    photo_dates cache (read once per file, as the site-folder scan reads them).

    Order (Q13): the dated photos always by capture time; one undated photo never reorders them. Each undated photo is
    placed alone between two dated neighbours: by the camera counter in its file name, between the dated photo with
    the next lower number and the one with the next higher number, when those two are neighbours in time; when the
    number cannot place it (no number, a number shared, a counter restart between those two), after the dated photo
    with the latest file modification time not after its own. In one gap, photos placed by number come first, in
    number order, then those placed by file time. A flag photo goes before the first dated photo taken after it. A
    folder photo with a flag photo's capture time is that flag photo, whatever its name: a renamed copy must not stand
    as a day photo, or the vote would line a night photo up with it (Q10). `at` is the capture time in seconds, None
    when the photo has none; `placed` says how each photo got its place ("time", "number" or "mtime"). `unread` is
    the error when the folder could not be listed (a share that dropped): no photos then, and no day photo."""

    def __init__(self, folder: Path, flags: list[dict] = (), site: str | None = None):
        from . import batch, measure  # batch imports inference, which imports this module

        self.signature = folder_signature(folder, site)
        self.unread = None
        try:
            files = measure.jpegs(folder)
        except ValueError as e:
            files, self.unread = [], str(e)
        flag_times = {f["captured_at"] for f in flags if f["captured_at"]}
        shots = [{"path": p, "name": p.name, "captured_at": None, "ok": None} for p in files]
        batch.fill_dates(shots)
        shots = [s for s in shots if s["ok"] and s["captured_at"] not in flag_times]
        dated = sorted((s for s in shots if s["captured_at"]), key=lambda s: (s["captured_at"], s["name"]))
        self.placed = {s["path"]: "time" for s in dated}
        seq = self._place(dated, [s for s in shots if not s["captured_at"]])
        self.flags: set[Path] = set()
        for f in sorted(flags, key=lambda f: f["captured_at"]):
            t = f["captured_at"]
            i = next((k for k, s in enumerate(seq) if s["captured_at"] and s["captured_at"] > t), len(seq))
            seq.insert(i, {"path": Path(f["ref_path"]), "name": f["image_name"], "captured_at": t})
            self.flags.add(Path(f["ref_path"]))
            self.placed[Path(f["ref_path"])] = "time"
        self.order = [s["path"] for s in seq]
        self.at = {s["path"]: _seconds(s["captured_at"]) if s["captured_at"] else None for s in seq}
        self.idx = {p: i for i, p in enumerate(self.order)}

    def _place(self, dated: list[dict], undated: list[dict]) -> list[dict]:
        """The dated photos with each undated photo put into the gap the class docstring gives it."""
        nums = Counter(counter(s["name"]) for s in dated + undated)
        by_num = {k: i for i, k in enumerate(counter(s["name"]) for s in dated) if k is not None and nums[k] == 1}
        shared = {counter(s["name"]) for s in dated} - set(by_num) - {None}  # numbers a restart gave twice
        mtimes = [self._mtime(s["path"]) for s in dated]
        gaps = defaultdict(list)  # gap i: just before dated[i]
        for s in undated:
            n, gap = counter(s["name"]), None
            if n is not None and nums[n] == 1:
                lo = max((k for k in by_num if k < n), default=None)
                hi = min((k for k in by_num if k > n), default=None)
                i_lo, i_hi = (-1 if lo is None else by_num[lo]), (len(dated) if hi is None else by_num[hi])
                restart = any((lo is None or lo < k) and (hi is None or k < hi) for k in shared)
                if i_hi == i_lo + 1 and not restart:
                    gap, key = i_hi, (0, n, s["name"])
                    self.placed[s["path"]] = "number"
            if gap is None:  # the number cannot place it: by file time, among the dated photos' file times
                m = self._mtime(s["path"])
                before = [(t, i) for i, t in enumerate(mtimes) if t <= m]
                gap, key = (max(before)[1] + 1 if before else 0), (1, m, s["name"])
                self.placed[s["path"]] = "mtime"
            gaps[gap].append((key, s))
        seq = []
        for i in range(len(dated) + 1):
            seq += [s for _, s in sorted(gaps[i], key=lambda x: x[0])]
            if i < len(dated):
                seq.append(dated[i])
        return seq

    @staticmethod
    def _mtime(p: Path) -> int:
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return 0

    def step(self, p: Path, step: int):
        """The photos going backward (-1) or forward (+1) in time from p."""
        i = self.idx[p] + step
        while 0 <= i < len(self.order):
            yield self.order[i]
            i += step

    def gaps(self, p: Path, a: Path, b: Path) -> tuple[float, float, str]:
        """How far A and B are from p: seconds when all three have a capture time, else photos along the order."""
        if None not in (self.at[p], self.at[a], self.at[b]):
            return abs(self.at[p] - self.at[a]), abs(self.at[b] - self.at[p]), "s"
        return abs(self.idx[p] - self.idx[a]), abs(self.idx[b] - self.idx[p]), "photos"


# --- one photo's line-up ------------------------------------------------------------------------------------

@dataclass
class Link:
    H: np.ndarray | None  # target -> reference pixels
    inliers: int | None   # None only for the flag photo's line-up to itself, which is not measured
    shift: float | None   # p95 px; None when there is no homography


IDENTITY = Link(np.eye(3), None, 0.0)  # the flag photo lined up with itself


@dataclass
class Line:
    """How one photo lands in its flag photo. `score` = the points of the line-up used: the photo's own by day (also
    when the day rule keeps it, or gives no distance); when borrowed (night, or the day rule) the weakest link of what
    it uses (the day photo's points, or the Chain's lower one), None when it copies the flag photo itself or a night
    photo has no line-up. `detail` holds what the researcher log keeps (`rule_detail`).
    `folder` is set only when a side had no day photo: the folder's signature then, so a photo arriving later re-plans
    it."""
    source: str
    status: str
    H: np.ndarray | None = None
    score: int | None = None
    night: bool | None = None
    anchor: str | None = None
    detail: dict = field(default_factory=dict)
    folder: str | None = None

    def public(self) -> dict:
        """What the run stores per photo (no homography; that stays in the store's links table)."""
        return {"source": self.source, "status": self.status, "score": self.score, "night": self.night,
                "anchor": self.anchor, "detail": self.detail, "folder": self.folder}


def _size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def _px(L: Link) -> float | None:
    return None if L.shift is None else round(L.shift, 2)


def _weakest(*links: Link) -> int | None:
    got = [L.inliers for L in links if L.inliers is not None]
    return min(got) if got else None


class Planner:
    """Line-ups for the photos of one run job: the job's flag photo `flag` (a calibration row with `ref_path`, the
    date rule's for every photo of the job, as folder 45 kept it) and the one model call. One planner per job; what it
    learns about links is written to the store as it goes, and what it finds about a night is kept for the next photo
    of the same night. `setting` names what a link is measured under beyond its two files (inference.Real.link_setting:
    fidelity, RoMa's refinement resolution, weights version); a link stored under another setting is measured again.
    The camera's other flag photos come from the store (`flag_photos`)."""

    def __init__(self, link, flag: dict, setting: str):
        self._link = link
        self.flag, self.ref, self.setting = flag, Path(flag["ref_path"]), setting
        others = [c for c in flag_photos(flag["site"]) if c["image_name"] != flag["image_name"]]
        self.flags = others + ([flag] if flag.get("captured_at") else [])
        self.links: dict[tuple[str, str], Link] = {}
        self.nights: dict[Path, bool | None] = {}
        self.lines: dict[Path, Line] = {}
        self.cams: dict[Path, Camera] = {}
        self.sizes: dict[Path, tuple[int, int]] = {}
        self.unreached: set[tuple[str, str]] = set()  # links that failed for the moment (a file gone or locked)

    # facts, each read once and kept
    def camera(self, p: Path) -> Camera:
        if p.parent not in self.cams:
            self.cams[p.parent] = Camera(p.parent, self.flags, self.flag["site"])
        return self.cams[p.parent]

    def size(self, p: Path) -> tuple[int, int]:
        if p not in self.sizes:
            self.sizes[p] = _size(p)
        return self.sizes[p]

    def same_size(self, a: Path, b: Path) -> bool:
        """Do two photos have the same pixel size? False when either cannot be opened."""
        try:
            return self.size(a) == self.size(b)
        except UNREADABLE:
            return False

    def night(self, p: Path) -> bool | None:
        if p not in self.nights:
            try:
                st = p.stat()
            except OSError:  # gone since the folder was listed: not known, so never a day photo, and nothing kept
                self.nights[p] = None
                return None
            found, value = store.night(str(p), st.st_size, st.st_mtime_ns)
            if not found:
                value = read_night(p)
                store.save_night(str(p), st.st_size, st.st_mtime_ns, value)
            self.nights[p] = value
        return self.nights[p]

    def link(self, target: Path, reference: Path) -> Link:
        """One measured line-up target -> reference (seeded in the backend, so the same pair always gives the same
        answer), from memory, the store, or the model.

        A photo that will not decode (cut short by a copy, corrupt) gives a failed link: no homography, 0 points. It
        does not stop the run: the day-photo search counts it as a rejected try, the move check reads it as moved, the
        vote as 0 points. It is kept like any link, so a broken file is not decoded again every run; once the file is
        rewritten its mtime differs and it is tried again. A file that was gone or locked is a fact about the moment:
        not kept."""
        key = (str(target), str(reference))
        if key not in self.links:
            stamps = None
            try:
                stamps = target.stat().st_mtime_ns, reference.stat().st_mtime_ns
                got = store.link(*key, self.setting, LINK_VERSION, *stamps)
                if got is None:
                    Hm, inliers = self._link(target, reference)
                    w, h = self.size(target)
                    shift = None if Hm is None else shift_p95(Hm, w, int(round(h * distance.BANNER_Y / 1080)))
                    got = (None if Hm is None else np.asarray(Hm, float), int(inliers), shift)
                    store.save_link(*key, self.setting, LINK_VERSION, *stamps, *got)
            except UNREADABLE as e:
                got = (None, 0, None)
                if stamps and not isinstance(e, _UNREACHED):
                    store.save_link(*key, self.setting, LINK_VERSION, *stamps, *got)
                else:  # about the moment: the day rule keeps no answer on it (day_rule)
                    self.unreached.add(key)
            self.links[key] = Link(*got)
        return self.links[key]

    # the rules
    def day_rule(self, p: Path) -> Line:
        """A day photo. Its own line-up with a homography and DAY_WEAK points or more: direct, as before. Otherwise the
        day rule (module docstring): Copy or Fallback through day photos A and B, never a vote or a Chain; with no A
        or B, its own line-up when it has a homography and DAY_KEEP points or more, else no distance. Every day-rule
        answer is source DAY_BORROW and keeps the own line-up's points in its detail.

        When the own line-up failed only for the moment (the photo or the flag photo gone or locked: a link not
        kept), no rule runs: the line is UNREAD, as when day or night cannot be read, so no answer is kept and the next
        run tries again."""
        own = self.link(p, self.ref)
        if (str(p), str(self.ref)) in self.unreached:
            return Line(UNKNOWN, UNREAD)
        if own.H is not None and own.inliers >= DAY_WEAK:
            return Line(DIRECT, OK, own.H, own.inliers, night=False)
        mine = {"own_points": own.inliers, "own_px": _px(own)}
        cam = self.camera(p)
        if cam.unread:  # the folder could not be listed just now: no A or B to look for; planned again next run
            return self._own_or_none(own, {"flag": self.ref.name, **mine, "why": NO_FOLDER, "error": cam.unread},
                                     NO_LISTING)
        if p not in cam.idx:  # the date scan could not open it, yet it reads as day now: not placed in time
            return self._own_or_none(own, {"flag": self.ref.name, **mine, "why": UNPLACED}, None)
        line, detail, checks = self._borrow(cam, p, DAY_BORROW, mine)
        if line is not None:
            return line
        return self._own_or_none(own, {**detail, "why": NO_DAY, "needs": DAY_MIN, "tries": TRIES, "keeps": DAY_KEEP,
                                       "checks": checks}, cam.signature)

    @staticmethod
    def _own_or_none(own: Link, detail: dict, folder: str | None) -> Line:
        """A day photo with no A or B: its own line-up when it has a homography and DAY_KEEP points or more (path OWN),
        else no distance (status NONE, no homography; the score is its own points, which the reason may quote)."""
        if own.H is not None and own.inliers >= DAY_KEEP:
            return Line(DAY_BORROW, OK, own.H, own.inliers, False, None, {**detail, "path": OWN}, folder)
        return Line(DAY_BORROW, NONE, None, own.inliers, False, None, detail, folder)

    def find_day(self, cam: Camera, p: Path, step: int, photos: list[Path] | None = None, tries: list | None = None,
                 mates: bool = True) -> tuple[Path | None, Link | None, list]:
        """Day photo A (step -1) or B (+1) of photo p: the first day photo or flag photo in this direction that
        lines up with the job's flag photo with DAY_MIN points or more, its link, and every try [name, points]. The
        job's flag photo is its own line-up and always passes. TRIES photos at most; one within BURST_S of a rejected
        one is the same burst and is skipped (photos with no capture time are never burst mates).

        A flag photo of another pixel size than p is passed over, not tried: its line-up (the identity for the job's
        flag photo) maps its own pixels, not p's, and the only other way to use it would be a link from the night
        photo to a flag photo (Q10). p itself is never tried: the walk starts at its neighbour.

        The Night rule calls it with p and the step only. The day rule (`find_near`) also hands it the `photos` to
        walk, the `tries` so far, and `mates` False for p's own burst, where no try is skipped as a burst mate."""
        rejected, tries = [], ([] if tries is None else tries)
        for g in (cam.step(p, step) if photos is None else photos):
            if g in cam.flags and not self.same_size(g, p):
                continue
            if g == self.ref:
                tries.append([g.name, None])
                return g, IDENTITY, tries
            if g not in cam.flags and self.night(g) is not False:
                continue
            if mates and any(cam.at[g] is not None and cam.at[r] is not None and abs(cam.at[g] - cam.at[r]) <= BURST_S
                             for r in rejected):
                continue
            L = self.link(g, self.ref)
            tries.append([g.name, L.inliers])
            if L.H is not None and L.inliers >= DAY_MIN:
                return g, L, tries
            rejected.append(g)
            if len(rejected) >= TRIES:
                break
        return None, None, tries

    def find_near(self, cam: Camera, p: Path, step: int) -> tuple[Path | None, Link | None, list]:
        """Day photo A (step -1) or B (+1) of a weak day photo p: burst first (review M1, 2026-10-12). A weak day
        photo is usually one frame of a burst whose other frames show more background. So first every photo of p's
        own burst on this side (the dated photos within BURST_S of p, nearest first, up to the first that is not) is
        tried, with no burst-mate skip: a rejected frame must not hide a strong frame a few seconds away. Then the
        normal search (`find_day`) goes on beyond the burst, with its own TRIES and burst-mate skip.

        The burst has a TRIES budget of its own, and its rejected tries neither count against the normal search's
        TRIES nor make its photos burst mates of what lies beyond: the burst is p's burst, not a rejected anchor's.
        At most 2 x TRIES links to the flag photo a side, each kept in the store like any link. An undated p has no
        burst: the normal search alone."""
        side = list(cam.step(p, step))
        k = 0
        if cam.at[p] is not None:
            while k < len(side) and cam.at[side[k]] is not None and abs(cam.at[side[k]] - cam.at[p]) <= BURST_S:
                k += 1
        g, L, tries = self.find_day(cam, p, step, side[:k], mates=False)
        if g is not None:
            return g, L, tries
        return self.find_day(cam, p, step, side[k:], tries)

    def night_rule(self, p: Path) -> Line:
        """A night photo: Copy, Chain or Fallback through day photos A and B (module docstring). Never a link from the
        night photo to a flag photo: a flag photo standing as A or B takes no part in the vote."""
        cam = self.camera(p)
        if cam.unread:  # the folder could not be listed just now: no day photo to find; planned again next run
            return Line(NIGHT, NONE, night=True, folder=NO_LISTING, detail={"why": NO_FOLDER, "error": cam.unread})
        if p not in cam.idx:  # the date scan could not open it, yet it reads as night now: not placed in time
            return Line(NIGHT, NONE, night=True, detail={"why": UNPLACED})
        line, detail, checks = self._borrow(cam, p, NIGHT)
        if line is not None:
            return line
        return Line(NIGHT, NONE, night=True, folder=cam.signature,
                    detail={**detail, "why": NO_DAY, "needs": DAY_MIN, "tries": TRIES, "checks": checks})

    def _borrow(self, cam: Camera, p: Path, source: str, extra: dict | None = None) -> tuple[Line | None, dict, list]:
        """What the Night rule and the day rule share, for photo p placed in `cam`: find day photos A and B, then one
        side (Copy it), the move check (Copy the nearer), or a move. On a move the Night rule (source NIGHT) votes and
        may Chain; the day rule (DAY_BORROW) never does ("no chain"): Fallback, copy the nearer. -> (the line, or None
        when neither A nor B was found, for the caller to answer; the detail so far; the checks by eye so far).
        `extra` goes into the detail after the tries (the day rule's own points).

        By day A and B come from `find_near` (burst first), and a flag photo stands as A or B only when the other side
        is a real day photo (DAY_MIN points to the flag photo): the wrong-camera guard (review, 2026-10-12). On a wrong
        camera no day photo passes, and a flag photo alone would hand its identity line-up to every photo near it. The
        flag photos found but not used are in the detail's `flag_only`."""
        night = source == NIGHT
        find = self.find_day if night else self.find_near
        a, to_a, tries_a = find(cam, p, -1)
        b, to_b, tries_b = find(cam, p, +1)
        unused = []
        if not night and not any(x is not None and x not in cam.flags for x in (a, b)):
            unused = [x.name for x in (a, b) if x is not None]  # flag photos only, or nothing: no A and no B
            a = to_a = b = to_b = None
        # placed by file number or file time (Q13): the photo, or a day photo it used (flag photos are dated)
        undated = cam.at[p] is None or any(x is not None and cam.at[x] is None for x in (a, b))
        detail = {"flag": self.ref.name, "order": cam.placed[p], "before": a and a.name, "after": b and b.name,
                  "before_tries": tries_a, "after_tries": tries_b, **(extra or {})}
        if unused:
            detail["flag_only"] = unused
        checks = [UNDATED] if undated else []
        if a is None and b is None:
            return None, detail, checks
        if a is None or b is None:
            x, to_x = (a, to_a) if a is not None else (b, to_b)
            return Line(source, OK, to_x.H, to_x.inliers, night, x.name,
                        {**detail, "path": ONE_SIDE, "side": "A" if x is a else "B", "checks": [UNCHECKED, *checks]},
                        folder=cam.signature), detail, checks
        day = {"A": (a, to_a), "B": (b, to_b)}
        gap_a, gap_b, unit = cam.gaps(p, a, b)
        near = "A" if gap_a <= gap_b else "B"
        move = self.link(b, a)  # B onto A; when A is the job's flag photo this is B's own line-up to it
        detail.update(gap_A=round(gap_a), gap_B=round(gap_b), gap_unit=unit, near=near,
                      move_points=move.inliers, move_px=_px(move))
        if move.H is not None and move.inliers >= LINK_OK and move.shift <= SAME_PX:
            x, to_x = day[near]
            return Line(source, OK, to_x.H, to_x.inliers, night, x.name, {**detail, "path": COPY, "side": near,
                                                                          "checks": checks}), detail, checks
        # moved (or B -> A too weak to tell, read as moved). At night: the vote, among the sides that are not flag
        # photos. By day: no vote and no Chain, straight to the Fallback.
        if night:
            votes = {s: self.link(p, x) for s, (x, _) in day.items() if x not in cam.flags}
            detail["vote"] = {s: [L.inliers, _px(L)] for s, L in votes.items()}
            if votes:
                top = max(L.inliers for L in votes.values())
                best = [s for s, L in votes.items() if L.inliers == top]
                win = near if near in best else best[0]
                L = votes[win]
                if L.H is not None and L.inliers >= CHAIN_MIN and L.shift is not None and L.shift < CHAIN_PX:
                    x, to_x = day[win]
                    return Line(NIGHT, OK, to_x.H @ L.H, _weakest(L, to_x), True, x.name,
                                {**detail, "path": CHAIN, "side": win, "checks": checks}), detail, checks
                detail["voted"] = win
        x, to_x = day[near]
        return Line(source, OK, to_x.H, to_x.inliers, night, x.name,
                    {**detail, "path": FALLBACK, "side": near, "checks": [MOVED, *checks]}), detail, checks

    def plan(self, p: Path) -> Line:
        """p's line-up by the rules: the day rule by day (direct when its own line-up is strong), the Night rule at
        night. Kept, so photos of one night ask the store once. When day or night cannot be read just now (the file
        locked or half copied), neither rule runs: the direct line-up might be a night photo's link to the flag photo
        (Q10), and a guess would be kept as a day photo for good. The line is UNREAD: measure._job keeps no answer, so
        the next run reads the photo again."""
        if p not in self.lines:
            night = self.night(p)
            self.lines[p] = (Line(UNKNOWN, UNREAD) if night is None else
                             self.night_rule(p) if night else self.day_rule(p))
        return self.lines[p]


# --- the researcher log (Q12; one log for every photo since 2026-10-11) --------------------------------------------

def log_dir() -> Path:
    """The app's own logs folder: where the launcher keeps launcher.log (logs\\ in the app folder), else (a developer's
    run, the tests) logs/ in the data folder. Never beside an export: general users do not see it."""
    launcher = os.environ.get("CAMTRAP_LAUNCHER_LOG")
    return Path(launcher).parent if launcher else store.DATA_DIR / "logs"


def rule_detail(alignment: dict) -> dict:
    """What the researcher log keeps about how a night photo (the Night rule) or a weak day photo (the day rule) was
    measured: its status, the day photo it used (anchor), the score, and the rule's detail (Copy / Chain / Fallback /
    one side / own, the day photos with their tries and points, the gaps, the move check, the vote, the day photo's
    own points, why there is no answer, and the checks by eye)."""
    return {"status": alignment.get("status"), "anchor": alignment.get("anchor"), "score": alignment.get("score"),
            **(alignment.get("detail") or {})}


def log_research(line: dict) -> None:
    """Append one line of JSON, stamped with its time, to the researcher log (LOG_NAME). measure._job writes one line
    per photo it measures, day or night, and one per unreadable file it meets. A log that cannot be written, for
    whatever reason, never stops a run.

    A run that skips current answers adds no lines. "Measure again" adds a new line for the photo; each line carries
    its time, and the last one per photo is the answer in the store. The file is never trimmed (a Night-rule follow-up
    G); it grows by about one line per photo measured."""
    try:
        row = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), **line}
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        print(f"research log not written: {e}", file=sys.stderr, flush=True)


# --- is a stored answer still current under these rules? ------------------------------------------------------

class Check:
    """What the skip rule asks of the disk, once per listing or run: folder signatures, and (`read`) whether an answer
    stored before line-up versions existed was a day or a night photo. A listing does not read photos (`read` off); a
    run does, once per such answer, and keeps it on the answer's row."""

    def __init__(self, read: bool = False):
        self.read, self.sigs = read, {}

    def signature(self, folder: Path, site: str | None) -> str:
        if (folder, site) not in self.sigs:
            self.sigs[(folder, site)] = folder_signature(folder, site)
        return self.sigs[(folder, site)]


def weak_direct(known: dict) -> bool:
    """Was this stored answer lined up directly with fewer than DAY_WEAK points? The day rule (ADR 0002) answers such
    a day photo another way, so it is measured again, once: the new answer is a day-rule one, or direct with DAY_WEAK
    points or more, and never weak direct again. Rows from before line-up versions were all lined up directly. A
    night answer (source NIGHT), a day-rule answer, an answer with no line-up (no animal, no score) and a stand-in
    backend's row (no source) are never weak direct."""
    direct = known.get("align_source") == DIRECT or known.get("alignment_version") is None
    score = known.get("match_score")
    return direct and score is not None and score < DAY_WEAK


def current(known: dict, check: Check | None = None) -> bool:
    """Is this stored answer's line-up the one these rules give? measure.current_answer asks this last.

    - Under any version: a day answer lined up directly with fewer than DAY_WEAK points (`weak_direct`) is measured
      again, once, by the day rule (2026-10-12). Night answers are not touched by this, so VERSION stays 2.
    - Under this VERSION: yes, unless a side had no day photo and the folder or the camera's flag photos have changed
      since; then a day photo may have arrived (a card copied in two goes, a service visit synced), so it is planned
      again. A day-rule answer with no A or B keeps the folder too.
    - Under an earlier line-up version: the row says day or night. A day photo's answer stands (when not weak direct),
      and so does a row that needed no line-up (no animal); a night photo is measured again, once.
    - From before line-up versions: an answer with no line-up (no animal, so no match score) stands, and so does a
      day photo's with DAY_WEAK points or more. A night photo is measured again, once. A listing that has not read the
      photo yet calls it out of date; the next run reads it and keeps a strong day photo's answer. A photo the run
      cannot read is out of date for that run and nothing is kept, so the next run reads it again."""
    check = check or Check()
    if weak_direct(known):  # day or night alike: measured again either way, so the photo need not be read
        return False
    version = known.get("alignment_version")
    if version == VERSION:
        folder = known.get("align_folder")
        return not folder or check.signature(Path(known["path"]).parent, known.get("site")) == folder
    if version is not None:
        return not known.get("night")
    if known.get("match_score") is None:
        return True
    night = known.get("night")
    if night is None and check.read and known.get("path"):
        found = read_night(Path(known["path"]))
        if found is None:  # unreadable now (locked, half copied): not a day photo for good, only not known yet
            return False
        night = int(found)
        store.save_photo_night(known["path"], night)
        known["night"] = night
    return night is not None and not night
