"""How each photo is lined up with its flag photo before the distance model reads it: the Night rule (ticket 33).

A day photo lines up with the flag photo directly, as before. A night IR photo does not: against the daytime colour
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

Every rule and threshold is from ../distance_estimation, experiments/refnet, and the design grilling
(.scratch/app/issues/33-night-bracket-grilling.md, Q1-Q13):
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
LINK_VERSION = 1  # how one link is measured (seeded RoMa + MAGSAC, target -> reference, both banner-cropped; shift
                  # p95 over the target's cropped frame). Apart from VERSION: a link is a fact about two files, the
                  # same under any rule that uses it, so a rule change re-plans from the stored links.
DAY_MIN = 4000     # a day photo is A or B when it lines up with the flag photo this well (folder 59, Q6; was 5,000)
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
OK, NONE, UNREAD = "ok", "none", "unread"  # Line.status; UNREAD: not measurable this run, no answer kept (measure._job)
COPY, CHAIN, FALLBACK, ONE_SIDE = "copy", "chain", "fallback", "one_side"  # Line.detail["path"] of a night answer
NO_DAY, UNPLACED, NO_FOLDER = "no_day", "unplaced", "no_folder"  # Line.detail["why"] of a night photo with no distance
NO_LISTING = "unreadable"  # Line.folder of a NO_FOLDER answer: folder_signature never gives it, so it is planned again
# what the export's `check` column asks the reader to look at (Line.detail["checks"]); report.check_text words them
MOVED, UNCHECKED, UNDATED = "moved", "unchecked", "undated"
LOG_NAME = "night-rule.jsonl"  # the researcher log (Q12), in the app's own logs folder


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
    """How one photo lands in its flag photo. `score` = the points of the line-up used: the photo's own by day; at
    night the weakest link of what it uses (the day photo's points, or the Chain's lower one), None when it copies the
    flag photo itself or has no line-up. `detail` holds what the researcher log and the export's `check` read.
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
            self.links[key] = Link(*got)
        return self.links[key]

    # the rules
    def direct(self, p: Path) -> Line:
        """A day photo's own line-up. One that found no homography is status NONE, with its points as the score (the
        "lines up poorly" reason quotes them), as before ticket 33."""
        L = self.link(p, self.ref)
        return Line(DIRECT, NONE if L.H is None else OK, L.H, L.inliers, night=False)

    def find_day(self, cam: Camera, p: Path, step: int) -> tuple[Path | None, Link | None, list]:
        """Day photo A (step -1) or B (+1) of night photo p: the first day photo or flag photo in this direction that
        lines up with the job's flag photo with DAY_MIN points or more, its link, and every try [name, points]. The
        job's flag photo is its own line-up and always passes. TRIES photos at most; one within BURST_S of a rejected
        one is the same burst and is skipped (photos with no capture time are never burst mates).

        A flag photo of another pixel size than p is passed over, not tried: its line-up (the identity for the job's
        flag photo) maps its own pixels, not p's, and the only other way to use it would be a link from the night
        photo to a flag photo (Q10)."""
        rejected, tries = [], []
        for g in cam.step(p, step):
            if g in cam.flags and not self.same_size(g, p):
                continue
            if g == self.ref:
                tries.append([g.name, None])
                return g, IDENTITY, tries
            if g not in cam.flags and self.night(g) is not False:
                continue
            if any(cam.at[g] is not None and cam.at[r] is not None and abs(cam.at[g] - cam.at[r]) <= BURST_S
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

    def night_rule(self, p: Path) -> Line:
        """A night photo: Copy, Chain or Fallback through day photos A and B (module docstring). Never a link from the
        night photo to a flag photo: a flag photo standing as A or B takes no part in the vote."""
        cam = self.camera(p)
        if cam.unread:  # the folder could not be listed just now: no day photo to find; planned again next run
            return Line(NIGHT, NONE, night=True, folder=NO_LISTING, detail={"why": NO_FOLDER, "error": cam.unread})
        if p not in cam.idx:  # the date scan could not open it, yet it reads as night now: not placed in time
            return Line(NIGHT, NONE, night=True, detail={"why": UNPLACED})
        a, to_a, tries_a = self.find_day(cam, p, -1)
        b, to_b, tries_b = self.find_day(cam, p, +1)
        # placed by file number or file time (Q13): the night photo, or a day photo it used (flag photos are dated)
        undated = cam.at[p] is None or any(x is not None and cam.at[x] is None for x in (a, b))
        detail = {"flag": self.ref.name, "order": cam.placed[p], "before": a and a.name, "after": b and b.name,
                  "before_tries": tries_a, "after_tries": tries_b}
        checks = [UNDATED] if undated else []
        if a is None and b is None:
            return Line(NIGHT, NONE, night=True, folder=cam.signature,
                        detail={**detail, "why": NO_DAY, "needs": DAY_MIN, "tries": TRIES, "checks": checks})
        if a is None or b is None:
            x, to_x = (a, to_a) if a is not None else (b, to_b)
            return Line(NIGHT, OK, to_x.H, to_x.inliers, True, x.name,
                        {**detail, "path": ONE_SIDE, "side": "A" if x is a else "B", "checks": [UNCHECKED, *checks]},
                        folder=cam.signature)
        day = {"A": (a, to_a), "B": (b, to_b)}
        gap_a, gap_b, unit = cam.gaps(p, a, b)
        near = "A" if gap_a <= gap_b else "B"
        move = self.link(b, a)  # B onto A; when A is the job's flag photo this is B's own line-up to it
        detail.update(gap_A=round(gap_a), gap_B=round(gap_b), gap_unit=unit, near=near,
                      move_points=move.inliers, move_px=_px(move))
        if move.H is not None and move.inliers >= LINK_OK and move.shift <= SAME_PX:
            x, to_x = day[near]
            return Line(NIGHT, OK, to_x.H, to_x.inliers, True, x.name, {**detail, "path": COPY, "side": near,
                                                                        "checks": checks})
        # moved (or B -> A too weak to tell, read as moved): the vote, among the sides that are not flag photos
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
                            {**detail, "path": CHAIN, "side": win, "checks": checks})
            detail["voted"] = win
        x, to_x = day[near]
        return Line(NIGHT, OK, to_x.H, to_x.inliers, True, x.name,
                    {**detail, "path": FALLBACK, "side": near, "checks": [MOVED, *checks]})

    def plan(self, p: Path) -> Line:
        """p's line-up by the rules: direct by day, the Night rule at night. Kept, so photos of one night ask the store
        once. When day or night cannot be read just now (the file locked or half copied), neither rule runs: the
        direct line-up might be a night photo's link to the flag photo (Q10), and a guess would be kept as a day photo
        for good. The line is UNREAD: measure._job keeps no answer, so the next run reads the photo again."""
        if p not in self.lines:
            night = self.night(p)
            self.lines[p] = (Line(UNKNOWN, UNREAD) if night is None else
                             self.night_rule(p) if night else self.direct(p))
        return self.lines[p]


# --- the researcher log (Q12) ----------------------------------------------------------------------------------

def log_dir() -> Path:
    """The app's own logs folder: where the launcher keeps launcher.log (logs\\ in the app folder), else (a developer's
    run, the tests) logs/ in the data folder. Never beside an export: general users do not see it."""
    launcher = os.environ.get("CAMTRAP_LAUNCHER_LOG")
    return Path(launcher).parent if launcher else store.DATA_DIR / "logs"


def log_night(photo: Path, alignment: dict) -> None:
    """One line of JSON per night answer: the photo, the flag photo, Copy / Chain / Fallback / one side, the day photos
    with their points, the move check and the vote. A log that cannot be written, for whatever reason, never stops a
    run.

    Written only when an answer is measured (measure._job, for each result it stores), so a run that skips current
    answers adds no lines. "Measure again", or a one-sided answer planned again, adds a new line for the photo; each
    line carries its time, and the last one per photo is the answer in the store. The file is never trimmed
    (ticket 33 follow-up)."""
    try:
        row = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "photo": str(photo),
               "status": alignment.get("status"), "anchor": alignment.get("anchor"), "score": alignment.get("score"),
               **(alignment.get("detail") or {})}
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        print(f"night-rule log not written: {e}", file=sys.stderr, flush=True)


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


def current(known: dict, check: Check | None = None) -> bool:
    """Is this stored answer's line-up the one these rules give? measure.current_answer asks this last.

    - Under this VERSION: yes, unless a side had no day photo and the folder or the camera's flag photos have changed
      since; then a day photo may have arrived (a card copied in two goes, a service visit synced), so it is planned
      again.
    - Under an earlier line-up version: the row says day or night. A day photo's answer stands (day photos line up as
      before), and so does a row that needed no line-up (no animal); a night photo is measured again, once.
    - From before line-up versions: an answer with no line-up (no animal, so no match score) stands, and so does a
      day photo's. A night photo is measured again, once. A listing that has not read the photo yet calls it out of
      date; the next run reads it and keeps a day photo's answer. A photo the run cannot read is out of date for that
      run and nothing is kept, so the next run reads it again."""
    check = check or Check()
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
