"""A site folder: the camera folders inside it, each matched to its camera by name, checked against the camera
name the photos carry, and every photo given its flag photo by date. Then one queue measures them (ticket 27).

A folder is a *site folder* when it holds no JPEGs itself and its subfolders do. A folder with JPEGs directly in
it is one camera's card, as before, and none of this applies.

The page only renders what `plan()` returns and posts clicks: which camera a row is, whether its flag photo is
chosen by date, whether it is ticked. Those choices live here, per site folder, for as long as the engine runs.
Reading a photo's capture date takes tens of milliseconds on a cold disk, and a site folder holds thousands, so only
the dates the plan needs are read (`_needed`), in a thread while the page polls, and kept in the store's photo_dates
table: a folder is read once, and only a new or changed photo is read again.
"""

import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

from PIL import Image

from . import calibration, inference, measure, store

DEPTH = 3  # levels below a camera folder searched for its photos (MAS_CAM07\filtered\ is one)
STAMP_SAMPLES = 5  # photos per folder whose camera stamp is read: enough to outvote one odd file
DEFAULT_PACE_S = 1.9  # seconds per photo on the dept card (RTX 2060 SUPER, published settings), until one is measured
# The Compare dialog's "lines up well". RoMa samples 10,000 matches per photo; the right camera lined up 8,600 to
# 9,100 of them on the dev store, the wrong one (MAS_CAM14 photos against MAS_CAM04) 54 to 276. The run's own
# alarm, distance.MIN_INLIERS = 15, is the published gate for a moved camera and is not changed here.
COMPARE_GOOD = 1000
_USER_COMMENT, _EXIF_IFD = 0x9286, 0x8769
_STAMP = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,8})(\d{1,4})(?![A-Za-z0-9])")


# --- names --------------------------------------------------------------------------------------------------

def _key(name: str) -> tuple[str, set[int]]:
    """A name as one lower-case string with separators gone and leading zeros dropped, plus the positions
    where a word or a number starts or ends. "MAS_CAM07 deer" -> ("mascam7deer", {0, 3, 6, 7, 11})."""
    key, cuts = "", {0}
    for part in re.findall(r"[A-Za-z]+|\d+", name):
        key += part.lower() if part.isalpha() else str(int(part))
        cuts.add(len(key))
    return key, cuts


def norm(name: str) -> str:
    """Case, spaces, _ and - and leading zeros do not count: "mas cam 2" == "MAS_CAM02"."""
    return _key(name)[0]


def matches(folder_name: str, cameras: list[str]) -> list[str]:
    """Every camera whose name appears in the folder name as whole words and whole numbers, so MAS_CAM07 is in
    "2026_MAS_CAM07_filtered" but MAS_CAM1 is not in "MAS_CAM14"."""
    key, cuts = _key(folder_name)
    out = []
    for cam in cameras:
        ck = norm(cam)
        i = key.find(ck) if ck else -1
        while i != -1:
            if i in cuts and i + len(ck) in cuts:
                out.append(cam)
                break
            i = key.find(ck, i + 1)
    return out


def _number(camera: str) -> int | None:
    m = re.search(r"(\d+)\D*$", camera)
    return int(m.group(1)) if m else None


# --- camera stamps ------------------------------------------------------------------------------------------

def read_stamp(path) -> str | None:
    """The text a camera writes into EXIF UserComment (Browning: "C[P] R0S1 T25F:P0000 MAS01   M1"); None when
    there is none. The first 8 bytes of the field name its character set."""
    try:
        with Image.open(path) as im:
            raw = im.getexif().get_ifd(_EXIF_IFD).get(_USER_COMMENT)
    except Exception:  # truncated file, odd EXIF: no stamp, no check
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        head, body = raw[:8], raw[8:]
        if head.startswith(b"UNICODE"):
            text = body.decode("utf-16", "ignore")
        elif head.startswith((b"ASCII", b"JIS", b"\0" * 8)):
            text = body.decode("latin-1")
        else:
            text = raw.decode("latin-1")
    else:
        text = str(raw)
    return " ".join(text.replace("\0", " ").split()) or None


def parse_stamp(text: str | None, sites: set[str]) -> tuple[str, int, str] | None:
    """The SITE+number token of a stamp, when its letters are one of the survey sites: "MAS01" -> ("MAS", 1, "MAS01").
    Other brands write other things there; a stamp with no such token is no stamp."""
    for m in _STAMP.finditer(text or ""):
        if m.group(1).upper() in sites:
            return m.group(1).upper(), int(m.group(2)), m.group(0)
    return None


def _site_of(camera: str) -> str:
    from .report import site_of  # report imports measure; asked late to keep the import order simple

    return site_of(camera)


def stamp_camera(stamp: tuple[str, int, str], cameras: list[str]) -> str | None:
    """The camera a stamp names: same site, same number. MAS14 -> MAS_CAM14."""
    return next((c for c in cameras if _site_of(c) == stamp[0] and _number(c) == stamp[1]), None)


def _same_camera(camera: str, stamp: tuple[str, int, str]) -> bool:
    return _site_of(camera) == stamp[0] and _number(camera) == stamp[1]


# --- flag photo by date -------------------------------------------------------------------------------------

def assign(times: dict[str, str | None], cals: list[dict]) -> dict[str, dict]:
    """Each photo (key -> capture time) gets the usable flag photo with the latest capture time on or before its
    own. Before the first flag photo: the earliest. Undated: the one the first dated photo got. A camera whose
    flag photos carry no date gives every photo its first one by name, as the single-folder default does."""
    dated = sorted((c for c in cals if c["captured_at"]), key=lambda c: c["captured_at"])
    if not dated:
        first = sorted(cals, key=lambda c: calibration._name_key(c["image_name"]))[0]
        return {k: first for k in times}

    def pick(t: str) -> dict:
        return next((c for c in reversed(dated) if c["captured_at"] <= t), dated[0])

    known = sorted(t for t in times.values() if t)
    undated = pick(known[0]) if known else dated[0]
    return {k: pick(t) if t else undated for k, t in times.items()}


# --- reading a site folder ----------------------------------------------------------------------------------

_lock = threading.Lock()
SCANS: dict[Path, dict] = {}  # site folder -> {status, done, total, folders, empty}
CHOICES: dict[Path, dict[str, dict]] = {}  # site folder -> row folder -> {camera, keep, flag, tick}
_EXIF: dict[tuple, tuple] = {}  # (path, size, mtime_ns) -> (captured_at, readable): this engine's copy of
# the store's photo_dates cache, which keeps them across restarts
FLUSH = 200  # photos read between writes to the store's cache
PROGRESS_S = 0.25  # seconds between progress updates while dates are read (the page polls every 0.7 s)


def _dirs(d: Path) -> list[Path]:
    """The folders inside `d` a person put there: not ".git", "$RECYCLE.BIN" or a hidden or system folder
    ("System Volume Information" on a card)."""
    try:
        with os.scandir(d) as entries:
            subs = [Path(e.path) for e in entries if e.is_dir() and not e.name.startswith((".", "$"))
                    and not getattr(e.stat(), "st_file_attributes", 0) & measure.HIDDEN]
    except OSError:  # a folder this account may not read: as if empty
        return []
    return sorted(subs, key=lambda p: calibration._name_key(p.name))


def _jpegs(d: Path) -> list[Path]:
    try:
        return measure.jpegs(d)
    except ValueError:
        return []


def _below(d: Path, depth: int) -> list[tuple[Path, list[Path]]]:
    found = [(d, j)] if (j := _jpegs(d)) else []
    if depth > 0:
        for sub in _dirs(d):
            found += _below(sub, depth - 1)
    return found


def walk(root: Path) -> tuple[list[tuple[Path, list[Path]]], list[str]] | None:
    """(every folder below `root` that holds JPEGs, with them; the subfolders that hold none), or None when
    `root` is not a site folder: it holds JPEGs itself, or nothing below it does."""
    if _jpegs(root):
        return None
    found, empty = [], []
    for sub in _dirs(root):
        inside = _below(sub, DEPTH)
        found += inside
        if not inside:
            empty.append(sub.name)
    return (found, empty) if found else None


def _samples(photos: list[Path]) -> list[Path]:
    if len(photos) <= STAMP_SAMPLES:
        return list(photos)
    step = (len(photos) - 1) / (STAMP_SAMPLES - 1)
    return [photos[round(i * step)] for i in range(STAMP_SAMPLES)]


def _list(root: Path) -> dict | None:
    """The site folder as found, nothing read yet: each photo's captured_at and ok stay None until its date is
    read (`_pending`, `_read_dates`), and a folder's stamps None until they are. None when `root` is not a site
    folder."""
    w = walk(root)
    if w is None:
        return None
    found, empty = w
    folders = []
    for d, jpegs in found:
        samples = _samples(jpegs)
        folders.append({"path": d, "rel": str(d.relative_to(root)), "stamps": None, "samples": samples,
                        "sample": samples[len(samples) // 2],
                        "photos": [{"path": p, "name": p.name, "captured_at": None, "ok": None} for p in jpegs]})
    return {"status": "ready", "folders": folders, "empty": empty}


def _camera(root: Path, folder: Path, cameras: list[str], pick: dict) -> tuple[str | None, str | None, str | None, list]:
    """(camera, chosen, matched_from, candidates) of one row: the camera the user chose, else the one camera its
    name, or the nearest folder above it that names one, fits."""
    matched_from, candidates = None, []
    for d in [folder, *folder.parents]:  # the folder itself, then the nearest folder above it
        if d == root:
            break
        if found := matches(d.name, cameras):
            matched_from, candidates = d.name, found
            break
    chosen = pick.get("camera") if pick.get("camera") in cameras else None
    return chosen or (candidates[0] if len(candidates) == 1 else None), chosen, matched_from, candidates


def _needed(root: Path, folders: list[dict], cameras: list[str], cals: list[dict]) -> list[dict]:
    """The folders whose capture dates decide something. Dates choose between a camera's flag photos and find two
    folders of one camera with the same photos, so a folder needs them only when its camera has two or more
    usable flag photos with a date (`assign` chooses among dated ones only), or another folder is the same
    camera. A folder with no camera, or whose camera has one flag photo, needs none: every photo gets that one."""
    picks = CHOICES.get(root, {})
    dated = Counter(c["site"] for c in cals if c["ok"] and c["captured_at"])
    cams = [_camera(root, f["path"], cameras, picks.get(str(f["path"]), {}))[0] for f in folders]
    per_camera = Counter(c for c in cams if c)
    return [f for f, cam in zip(folders, cams) if cam and (dated[cam] >= 2 or per_camera[cam] >= 2)]


def _pending(photos: list[dict]) -> list[tuple[dict, tuple]]:
    """Fill in the photos whose date is known (this engine read it, or the store's cache has it for the same
    size and modification time) and return the rest, each with its (path, size, mtime_ns) key, to be read."""
    ask = []
    for ph in photos:
        if ph["ok"] is not None:
            continue
        try:
            st = ph["path"].stat()
        except OSError:  # gone since the walk: as unreadable
            ph["captured_at"], ph["ok"] = None, False
            continue
        key = (str(ph["path"]), st.st_size, st.st_mtime_ns)
        if key in _EXIF:
            ph["captured_at"], ph["ok"] = _EXIF[key]
        else:
            ask.append((ph, key))
    cached = store.photo_dates([key for _, key in ask]) if ask else {}
    todo = []
    for ph, key in ask:
        if key[0] in cached:
            ph["captured_at"], ph["ok"] = _EXIF[key] = cached[key[0]]
        else:
            todo.append((ph, key))
    return todo


def _read_dates(todo: list[tuple[dict, tuple]], progress=None) -> None:
    """Open each photo once (does it open, and its capture date), keep the answer in memory, and write it to the
    store's cache every FLUSH photos. Progress is told at most every PROGRESS_S seconds, and at the end."""
    rows, told = [], 0.0
    try:
        for i, (ph, key) in enumerate(todo, 1):
            got = calibration.read_exif(ph["path"], readable=True)
            ph["captured_at"], ph["ok"] = _EXIF[key] = (got["captured_at"], got["readable"])
            rows.append((*key, got["captured_at"], got["readable"]))
            if len(rows) >= FLUSH:
                store.save_photo_dates(rows)
                rows = []
            if progress and (i == len(todo) or time.monotonic() - told >= PROGRESS_S):
                progress(i, len(todo))
                told = time.monotonic()
    finally:  # stopped part way (a share that vanished): what was read is still kept
        store.save_photo_dates(rows)


def _finish(scan_: dict, todo: list[tuple[dict, tuple]], progress=None) -> dict:
    """Read what the scan still lacks: a few camera stamps per folder, then the dates in `todo`."""
    for f in scan_["folders"]:
        if f["stamps"] is None:
            f["stamps"] = [t for t in map(read_stamp, f["samples"]) if t]
    _read_dates(todo, progress)
    return scan_


def _todo(root: Path, scan_: dict) -> list[tuple[dict, tuple]]:
    """The photos whose dates the plan needs (`_needed`) and that are not known yet."""
    need = _needed(root, scan_["folders"], store.sites(), store.calibrations())
    return _pending([p for f in need for p in f["photos"]])


def fill_dates(photos: list[dict]) -> None:
    """Make sure these scanned photos carry their date and whether they open: from the caches, else read now."""
    _read_dates(_pending(photos))


def read(root: Path, progress=None) -> dict:
    """Walk the site folder and read what the plan needs: a few camera stamps per folder, and the capture dates
    of the folders that need them. Synchronous. -> {status: "ready", folders, empty} or {status: "single"}; a
    single folder reads nothing."""
    scan_ = _list(root)
    if scan_ is None:
        return {"status": "single"}
    return _finish(scan_, _todo(root, scan_), progress)


def scan(path: str, refresh: bool = False) -> dict:
    """What GET /api/site answers: reading progress, "single" (not a site folder), or the scan. Dates still to be
    read (the first time a folder is opened) are read in a thread while the page polls {status: "reading", done,
    total}; with none to read the scan is ready at once. Raises ValueError with the message."""
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Folder not found: {root}")
    with _lock:
        s = SCANS.get(root)
        if s and (s["status"] == "reading" or not refresh):
            return s
        scan_ = _list(root)
        if scan_ is None:
            SCANS[root] = {"status": "single"}
            return SCANS[root]
        todo = _todo(root, scan_)
        if not todo:
            SCANS[root] = _finish(scan_, todo)
            return SCANS[root]
        s = SCANS[root] = {"status": "reading", "done": 0, "total": len(todo)}

    def work():
        def tick(done, total):
            s["done"], s["total"] = done, total
        try:
            got = _finish(scan_, todo, tick)
        except Exception as e:  # a share that vanished mid-read: say so, do not leave it "reading" for ever
            got = {"status": "error", "error": f"Could not read {root}: {e}"}
        SCANS[root] = got

    threading.Thread(target=work, daemon=True).start()
    return s


def ready_scan(root: Path) -> dict:
    """The scan of a site folder, read now if it has not been (tests, and a listing asked for before the page
    polled)."""
    s = SCANS.get(root)
    if not s or s["status"] != "ready":
        s = SCANS[root] = read(root)
    return s


# --- the plan: one row per camera folder --------------------------------------------------------------------

def choose(path: str, folder: str, **change) -> None:
    """Remember a click on one row: camera, keep (the camera the user kept against its stamp), flag ("" = by date),
    tick. A new camera forgets the old keep and flag, which belonged to the old camera."""
    root = Path(path).expanduser().resolve()
    row = CHOICES.setdefault(root, {}).setdefault(str(Path(folder).expanduser().resolve()), {})
    if "camera" in change and change["camera"] != row.get("camera"):
        row.pop("keep", None)
        row.pop("flag", None)
    row.update(change)


def tick_all(path: str, on: bool) -> None:
    """Tick all / Tick none: every Ready row."""
    root = Path(path).expanduser().resolve()
    for r in _build(root)[0]:
        if r["group"] == "ready" and r["tickable"]:
            choose(str(root), r["folder"], tick=on)


def pace() -> float:
    """Seconds per photo for the time estimate: the last real run's, else the dept card's."""
    try:
        return float(store.meta("pace_s_per_photo") or DEFAULT_PACE_S)
    except ValueError:
        return DEFAULT_PACE_S


def plan(path: str, method: str = inference.DEFAULT_METHOD) -> dict:
    """The confirmation table: every camera folder as a row with its camera, its flag photos by date, its checks
    and its tick; the skipped folders; and what the ticked rows add up to. Raises ValueError with the message."""
    root = Path(path).expanduser().resolve()
    rows, empty = _build(root, method)
    rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    ticked = [r for r in rows if r["ticked"]]
    return {
        "status": "ready", "folder": str(root), "rows": rows,
        "skipped": [{"name": n, "why": "no photos inside"} for n in empty],
        "counts": {"check": sum(1 for r in rows if r["group"] == "attention" and r["tickable"]),
                   "cannot": sum(1 for r in rows if not r["tickable"]),
                   "ready": sum(1 for r in rows if r["group"] == "ready"),
                   "skipped": len(empty)},
        "ticked": {"cameras": len(ticked), "photos": sum(r["photos"] for r in ticked),
                   "measured": sum(r["measured"] for r in ticked)},
        "pace_s": pace(),
    }


def _build(root: Path, method: str = inference.DEFAULT_METHOD) -> tuple[list[dict], list[str]]:
    """Every row, with the private `_got` (photo path -> flag photo) and `_scan` (the folder as read)."""
    from . import report

    scan_ = ready_scan(root)
    if scan_["status"] != "ready":
        raise ValueError(f"{root} is not a site folder: it holds photos itself, or no folder in it does.")
    cameras = store.sites()
    cals = store.calibrations()
    # dates the plan needs now and the first read skipped: a row the user moved to a camera with two flag photos
    fill_dates([p for f in _needed(root, scan_["folders"], cameras, cals) for p in f["photos"]])
    usable = {c: [r for r in cals if r["site"] == c and r["ok"]] for c in cameras}
    sites = {_site_of(c) for c in cameras}
    known = {p["path"]: p for p in store.photos()}
    fid = inference.state["fidelity"] or inference.fidelity()
    picks = CHOICES.get(root, {})
    rows = []
    for f in scan_["folders"]:
        report.LISTED_FOLDERS.add(f["path"])  # its photos may be shown: the Compare dialog, the table
        rows.append(_row(root, f, cameras, usable, sites, picks.get(str(f["path"]), {}), known, method, fid))
    _duplicates(rows)
    for r in rows:
        explicit = picks.get(r["folder"], {}).get("tick")
        default = r.pop("_default_tick")
        r["ticked"] = r["tickable"] and (default if explicit is None else bool(explicit))
        r["group"] = "attention" if r["warnings"] or not r["tickable"] else "ready"
    order = {"attention": 0, "ready": 1}
    rows.sort(key=lambda r: (order[r["group"]], calibration._name_key(r["name"])))
    return rows, scan_["empty"]


def _row(root: Path, f: dict, cameras: list[str], usable: dict, sites: set[str], pick: dict, known: dict,
         method: str, fid: str) -> dict:
    camera, chosen, matched_from, candidates = _camera(root, f["path"], cameras, pick)
    row = {"folder": str(f["path"]), "name": f["rel"], "photos": len(f["photos"]), "camera": camera,
           "candidates": candidates, "state": "ok", "note": None, "stamp": None, "flags": [], "flag_choice": "",
           "options": [], "measured": 0, "warnings": [], "actions": [], "tickable": False,
           "_default_tick": False, "_got": {}, "_scan": f}
    if camera is None:
        row["state"] = "ambiguous" if candidates else "unknown"
        if candidates:
            row["warnings"].append(f"The name fits {_and(candidates)}. Choose the camera.")
        else:
            row["actions"].append("flaglabel")
        return row
    if not chosen and matched_from != camera:
        row["note"] = f'Matched "{matched_from}" to {camera}'
    if not usable[camera]:
        row["state"] = "unlabelled"
        row["actions"].append("flaglabel")
        return row

    # what the photos say about themselves
    stamps = [s for s in (parse_stamp(t, sites) for t in f["stamps"]) if s]
    if stamps:
        st = Counter(stamps).most_common(1)[0][0]
        row["stamp"] = {"text": st[2], "camera": stamp_camera(st, cameras), "mismatch": not _same_camera(camera, st),
                        "kept": pick.get("keep") == camera}
    mismatch = bool(row["stamp"] and row["stamp"]["mismatch"] and not row["stamp"]["kept"])
    says = row["stamp"] and (row["stamp"]["camera"] or row["stamp"]["text"])
    if mismatch:
        row["warnings"].append(f"The photos say they are from {says}")
        row["actions"] += ["compare", "use", "keep"] if row["stamp"]["camera"] else ["keep"]
    elif row["stamp"] and row["stamp"]["mismatch"]:
        row["note"] = f"You kept {camera}. The photos say {says}."

    # which flag photo each photo uses
    cals = usable[camera]
    row["options"] = [{"image_name": c["image_name"], "captured_at": c["captured_at"]}
                      for c in sorted(cals, key=lambda c: calibration._name_key(c["image_name"]))]
    forced = next((c for c in cals if c["image_name"] == pick.get("flag")), None)
    row["flag_choice"] = forced["image_name"] if forced else ""
    got = {str(p["path"]): forced for p in f["photos"]} if forced else \
        assign({str(p["path"]): p["captured_at"] for p in f["photos"]}, cals)
    first = min((c for c in cals if c["captured_at"]), key=lambda c: c["captured_at"], default=None)
    used = Counter(c["image_name"] for c in got.values())
    for c in sorted({c["image_name"]: c for c in got.values()}.values(),
                    key=lambda c: (c["captured_at"] is None, c["captured_at"] or "", c["image_name"])):
        row["flags"].append({"image_name": c["image_name"], "captured_at": c["captured_at"],
                             "photos": used[c["image_name"]],
                             "visit": None if not c["captured_at"] else "setup" if c is first else "service"})
    row["measured"] = sum(1 for p, c in got.items() if measure.current_answer(known.get(p), c, method, fid))
    row["tickable"], row["_default_tick"], row["_got"] = True, not mismatch, got
    return row


def _overlap(a: dict, b: dict) -> bool:
    """Same photos: half or more of the smaller folder's dated photos are in the other (same name, same time)."""
    ka = {(p["name"], p["captured_at"]) for p in a["photos"] if p["captured_at"]}
    kb = {(p["name"], p["captured_at"]) for p in b["photos"] if p["captured_at"]}
    small = min(len(ka), len(kb))
    return small > 0 and len(ka & kb) * 2 >= small


def _duplicates(rows: list[dict]) -> None:
    """Two folders of one camera with the same photos: say so on both, keep the smaller one ticked and the larger
    not. Only within a camera: two cameras on one time-lapse schedule can both write IMG_0001.JPG at noon, and a
    copy filed under the wrong camera is what the stamp check is for."""
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if not a["camera"] or a["camera"] != b["camera"] or not _overlap(a["_scan"], b["_scan"]):
                continue
            small, big = (a, b) if a["photos"] <= b["photos"] else (b, a)
            text = f"{small['name']} has the same photos as {big['name']}. Measure only one."
            for r in (small, big):
                if text not in r["warnings"]:
                    r["warnings"].append(text)
            big["_default_tick"] = False


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def assignments(path: str) -> dict[str, dict]:
    """photo path -> the flag photo (calibration row) the plan gives it, for every row with a usable camera.
    What the site listing's "out of date" asks against, and what the run measures with."""
    out = {}
    for r in _build(Path(path).expanduser().resolve())[0]:
        out.update(r["_got"])
    return out


# --- the run ------------------------------------------------------------------------------------------------

def _left_out(r: dict) -> str:
    """Why a row was not measured, in the words of the done note."""
    if r["state"] == "unknown":
        return "no camera with this name"
    if r["state"] == "unlabelled":
        return "no labelled flag photo yet"
    if r["state"] == "ambiguous":
        return "choose which camera it is"
    if r["stamp"] and r["stamp"]["mismatch"] and not r["stamp"]["kept"]:
        return "check which camera it is"
    if any("same photos" in w for w in r["warnings"]):
        return "same photos as another folder"
    return "not ticked"


def start(path: str, method: str, rerun: bool = False, photos: list[str] | None = None) -> dict:
    """Measure the ticked rows of a site folder, or exactly the photos given, each photo against the flag photo
    the plan gives it. One job per (camera folder, flag photo): the models are handed one flag photo per call.
    Raises ValueError (bad input) or RuntimeError (a run is busy)."""
    root = Path(path).expanduser().resolve()
    if method not in inference.METHODS:
        raise ValueError(f"Unknown method {method!r}; choose one of {', '.join(inference.METHODS)}.")
    rows, _ = _build(root, method)
    if photos is None:
        chosen = [(r, [str(p["path"]) for p in r["_scan"]["photos"]]) for r in rows if r["ticked"]]
        if not chosen:
            raise ValueError("No camera ticked. Tick at least one camera to measure.")
    else:
        wanted = [str(Path(p).expanduser().resolve()) for p in photos]
        chosen = [(r, [p for p in wanted if p in r["_got"]]) for r in rows]
        chosen = [(r, ps) for r, ps in chosen if ps]
        if not wanted or sum(len(ps) for _, ps in chosen) != len(wanted):
            raise ValueError("Pick photos from camera folders that have a camera and a flag photo.")
    cameras, jobs = [], []
    for i, (r, ps) in enumerate(chosen):
        groups: dict[str, list[Path]] = {}
        for p in ps:
            groups.setdefault(r["_got"][p]["image_name"], []).append(Path(p))
        for flag, group in groups.items():
            cal = r["_got"][str(group[0])]
            if not store.ref_path(cal["site"], flag).exists():
                raise ValueError(f"The flag photo {flag} of {cal['site']} is not on this computer yet. "
                                 "Press Sync, then measure again.")
            jobs.append({"camera": i, "cal": cal, "photos": group})
        flags = [{"image_name": f, "captured_at": r["_got"][str(g[0])]["captured_at"]} for f, g in groups.items()]
        cameras.append({"folder": r["folder"], "name": r["name"], "site": r["camera"], "flags": flags,
                        "prefix": str(Path(r["name"])) + os.sep,  # how TABLE names this folder's photos
                        "total": len(ps), "done": 0, "deer": 0, "needs_look": 0, "status": "waiting",
                        "photos": None, "median_m": None})
    left = [] if photos is not None else \
        [{"name": r["name"], "why": _left_out(r)} for r in rows if not r["ticked"]]
    return measure.start_jobs({"kind": "site", "folder": str(root), "site": None, "flag": None,
                               "cameras": cameras, "camera_i": 0, "left_out": left},
                              jobs, method, rerun or photos is not None)


def compare(path: str, folder: str, score: bool = True) -> dict:
    """The Compare dialog: one photo of the row, lined up against the matched camera's flag photo and against the
    flag photo of the camera its stamp names. Lining up loads the alignment model when needed (seconds), so the
    dialog first asks with score=False, shows the three photos, and then asks for the scores.
    Raises ValueError with the message."""
    root = Path(path).expanduser().resolve()
    want = str(Path(folder).expanduser().resolve())
    row = next((r for r in _build(root)[0] if r["folder"] == want), None)
    if row is None or not row["stamp"] or not row["stamp"]["camera"] or not row["_got"]:
        raise ValueError("Nothing to compare for this folder.")
    photo = row["_scan"]["sample"]
    sample = next(p for p in row["_scan"]["photos"] if p["path"] == photo)
    fill_dates([sample])  # a folder with one flag photo was not dated; the other camera may need it
    when = sample["captured_at"]
    other = row["stamp"]["camera"]
    theirs = [c for c in store.calibrations() if c["site"] == other and c["ok"]]
    pairs = [(row["camera"], row["_got"][str(photo)]), (other, assign({"p": when}, theirs)["p"] if theirs else None)]
    refs = [{**cal, "ref_path": str(store.ref_path(cam, cal["image_name"]))} for cam, cal in pairs if cal]
    points = iter(inference.alignment(photo, refs) if score else [None] * len(refs))
    flags = []
    for cam, cal in pairs:
        n = next(points) if cal else None
        flags.append({"site": cam, "image_name": cal and cal["image_name"], "score": n,
                      "lines_up": n is not None and n >= COMPARE_GOOD})
    return {"folder": want, "photo": str(photo), "name": photo.name, "stamp": row["stamp"]["text"], "flags": flags}
