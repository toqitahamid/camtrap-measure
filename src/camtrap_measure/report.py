"""Views over the results store: the folder the window is working on, the post-run summary, and the gated CSV export.

`folder` lists every JPEG in one folder — measured or not — with its boxes and their numbers, because the
window works on a folder the technician picked, and a photo with no answer yet still has to appear in the
list, the table and the frame. A detection row is *suspicious* when its number should not enter
an analysis unread: the photo did not match its flag photo well (misfiled / moved camera), the detector was
unsure of the box, SpeciesNet was unsure of the animal, or no ground could be read under it. Such rows are
marked in the listing and left out of the export unless asked — and the file says how many it left out.
"""

import csv
import io
import statistics
from datetime import datetime
from ntpath import basename  # splits on / and \ alike: paths come from the dept's Windows machine or a Linux test box
from pathlib import Path

from . import calibration, inference, measure, store
from .distance import MIN_INLIERS
from .inference import DEFAULT_METHOD, MIN_SPECIES_SCORE

LOW_CONF = 0.5  # ponytail: detector confidence below this is "weak box"; tune with the dept's first season
DEER = {"white-tailed deer", "unsure"}  # default export: the survey target plus animals that may be it
BIN_M = 2  # histogram bin width, metres

COLUMNS = ["photo", "camera", "site", "timestamp", "species", "distance_m", "q05_m", "q95_m", "confidence", "method",
           "fidelity", "match_score", "flag"]
DOC = """\
# photo: file name; camera: the camera (the photo folder's name); timestamp: EXIF capture time in the camera's local time, no zone
# site: the survey site, the part of the camera name before its last '_CAM' (MAS_CAM01 -> MAS); a name with no '_CAM' is its own site
# species: what the species model named; 'white-tailed deer' is any deer-family prediction, 'unsure' a weak one (score < {min_species})
# distance_m: horizontal ground distance to the animal in metres (median estimate)
# q05_m, q95_m: bounds of the 90% interval around distance_m, metres; empty when no distance could be read
# confidence: how sure the detector is that the box holds an animal, 0-1; method: md = distance read at the bottom of the MegaDetector box, sam3 = where the SAM3 outline meets the ground
# fidelity: research = the published settings, fast = quicker settings for a small graphics card (see the app's docs);
#           distances differ between the two by a few centimetres, well inside the q05-q95 band, but do not mix them silently
# match_score: points that line up between this photo and its flag photo (fewer than {min_inliers} = needs a look)
# flag: empty for a row that looks fine, else why the row needs a look (such rows are in this file only if you asked for them)
""".format(min_inliers=MIN_INLIERS, min_species=MIN_SPECIES_SCORE)


def site_of(camera: str) -> str:
    """The survey site a camera belongs to: the part of its name before the last "_CAM" (MAS_CAM01 -> MAS).
    A name with no "_CAM" is its own site."""
    head, cam, _ = camera.rpartition("_CAM")
    return head if cam else camera


def reasons(row: dict) -> list[str]:
    """Why a detection row is suspicious; [] when it is clean. Thresholds are named so the gallery explains itself."""
    out = []
    aligned = row["match_score"] is not None and row["match_score"] >= MIN_INLIERS
    if row["match_score"] is None:
        out.append("did not line up with its flag photo, so no distance")
    elif not aligned:
        out.append(f"lines up poorly with its flag photo ({row['match_score']} points, needs {MIN_INLIERS}). Wrong camera, or was it moved?")
    if row["confidence"] < LOW_CONF:
        out.append(f"low confidence it is an animal ({row['confidence']:.2f}, needs {LOW_CONF})")
    if row["species"] == "unsure":
        out.append("species unsure, may not be a deer")
    if row["distance_m"] is None and aligned:
        out.append("could not find the ground under the animal, so no distance")
    return out


def _in_range(captured_at: str | None, date_from: str | None, date_to: str | None) -> bool:
    """Capture dates are compared as YYYY-MM-DD. A photo without one is in every range: it cannot be
    placed in time, which is exactly why it is held and must stay in view."""
    if captured_at is None:
        return True
    day = captured_at[:10]
    return (not date_from or day >= date_from) and (not date_to or day <= date_to)


def _in_folder(path: str, folder: str | None) -> bool:
    """Was this photo measured out of `folder`? Directly inside it, not below it: a run only ever reads the
    JPEGs sitting in the one folder the window is pointed at. On Windows the comparison folds case, as the
    filesystem does — the picker and a typed path can disagree about drive letters and capitals."""
    return not folder or Path(path).parent == Path(folder)


def _in_site(camera: str, site: str | None, survey_site: str | None) -> bool:
    """`site` picks one camera (the store's historic name for it); `survey_site` picks every camera of a site."""
    return (not site or camera == site) and (not survey_site or site_of(camera) == survey_site)


def rows(site=None, date_from=None, date_to=None, folder=None, survey_site=None) -> list[dict]:
    """Detection rows in scope, each with `flag` = '; '.join(reasons)."""
    out = []
    for r in store.detections():
        if not _in_site(r["site"], site, survey_site) or not _in_range(r["captured_at"], date_from, date_to):
            continue
        if not _in_folder(r["path"], folder):
            continue
        out.append({**r, "flag": "; ".join(reasons(r))})
    return out


def photos(site=None, date_from=None, date_to=None, folder=None, survey_site=None) -> list[dict]:
    """Photo rows in scope — measured and held."""
    return [p for p in store.photos()
            if _in_site(p["site"], site, survey_site) and _in_range(p["captured_at"], date_from, date_to)
            and _in_folder(p["path"], folder)]


def summary(site=None, date_from=None, date_to=None, all_species=False, folder=None, survey_site=None) -> dict:
    """Counts, a histogram of deer distances, and one line per camera. `suspicious` counts the rows the
    export with the same species setting would leave out, so the number on screen is the number in the file.
    `folder` narrows all of it to the photos measured out of one folder — what RESULTS shows by default, so
    the screen answers for the folder in the bar rather than for everything ever measured."""
    ph, rs = photos(site, date_from, date_to, folder, survey_site), rows(site, date_from, date_to, folder, survey_site)
    deer = [r for r in rs if all_species or r["species"] in DEER]
    dists = [r["distance_m"] for r in deer if r["distance_m"] is not None]
    hist = {}
    for d in dists:
        lo = int(d // BIN_M) * BIN_M
        hist[lo] = hist.get(lo, 0) + 1
    cams = []
    for s in sorted({p["site"] for p in ph}):
        cp, cd = [p for p in ph if p["site"] == s], [r for r in deer if r["site"] == s]
        cdist = [r["distance_m"] for r in cd if r["distance_m"] is not None]
        cams.append({"site": s, "photos": len(cp), "held": sum(1 for p in cp if p["held_reason"]),
                     "detections": sum(1 for r in rs if r["site"] == s), "deer": len(cd),
                     "median_m": round(statistics.median(cdist), 1) if cdist else None,
                     "suspicious": sum(1 for r in cd if r["flag"])})
    return {"photos": len(ph), "held": sum(1 for p in ph if p["held_reason"]), "detections": len(rs), "deer": len(deer),
            "suspicious": sum(1 for r in deer if r["flag"]),
            "histogram": [{"lo": lo, "hi": lo + BIN_M, "n": hist[lo]} for lo in sorted(hist)], "cameras": cams}


DET_KEYS = ("idx", "x1", "y1", "x2", "y2", "species", "confidence", "distance_m", "q05_m", "q95_m",
            "method", "match_score")


UNREADABLE = "this file could not be read. It may be damaged or not a real JPEG."

# Folders `folder()` has listed since the engine started. The photo endpoint serves their JPEGs as well as
# measured ones: the list, the table and the frame show a folder before anything in it has been measured, and
# a thumbnail must not be the one broken thing on the page. Forgotten on restart, which only costs a relist.
LISTED_FOLDERS: set[Path] = set()


def listed(path: str) -> bool:
    """Is this a JPEG sitting directly in a folder this process has listed? Strict on purpose: the parent must
    be a listed folder itself, so no path is served merely for looking like it is somewhere below one."""
    p = Path(path).expanduser().resolve()
    return p.suffix.lower() in measure.JPEG and p.parent in LISTED_FOLDERS


def folder(path: str, site: str = "", flag: str = "", method: str = DEFAULT_METHOD) -> dict:
    """Every JPEG in one folder, name order, each joined with the answer the store holds for this flag photo
    and method — measured or not, because the window renders the folder the technician picked, not the
    measured photos. A photo measured under the OTHER method reads as unmeasured here, because the
    question is what this method says. `stale` asks the run's own skip rule (`measure.current_answer`), so a stale row is
    exactly a row that measuring the folder again would redo; with no flag photo chosen nothing is stale,
    because there is nothing to be stale against. Raises ValueError with the message."""
    d = Path(path).expanduser().resolve()
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    files = measure.jpegs(d)  # raises ValueError with a plain message if the folder cannot be read
    LISTED_FOLDERS.add(d)
    cal = next((c for c in store.calibrations() if c["site"] == site and c["image_name"] == flag), None)
    known = {p["path"]: p for p in store.photos()}
    dets: dict[str, list[dict]] = {}
    for r in store.detections():
        if r["method"] == method:
            dets.setdefault(r["path"], []).append(r)
    out, unreadable = [], 0
    for p in files:
        seen = known.get(str(p))
        if seen and seen["method"] != method:
            seen = None  # measured, but not under the method being asked about: no answer to this question
        row = {"name": p.name, "path": str(p), "captured_at": None, "measured": seen is not None, "stale": False,
               "match_score": None, "method": None, "flag_image": None, "flag_site": None, "reasons": [], "detections": []}
        if seen:
            # flag_site travels with flag_image or the pair is meaningless: the window shows the flag photo a
            # number was read against, and a camera chosen in the meantime is not the camera that produced it.
            # Asking for one camera's flag under another camera's name is a 404 and a blank frame (2026-08-25).
            row.update(captured_at=seen["captured_at"], match_score=seen["match_score"], method=seen["method"],
                       flag_image=seen["calibration_image"], flag_site=seen["site"],
                       stale=cal is not None and not measure.current_answer(seen, cal, method, inference.fidelity()),
                       reasons=[seen["held_reason"]] if seen["held_reason"] else [])
            for r in sorted(dets.get(str(p), []), key=lambda r: r["idx"]):
                why = reasons(r)
                row["detections"].append({**{k: r[k] for k in DET_KEYS}, "reasons": why})
                row["reasons"] += [w for w in why if w not in row["reasons"]]
        elif measure.readable(p):
            row["captured_at"] = calibration.read_exif(p)["captured_at"]
        else:  # a truncated file is listed like any other, so the technician sees which one to look at
            unreadable += 1
            row["reasons"] = [UNREADABLE]
        out.append(row)
    return {"folder": str(d), "total": len(out), "unreadable": unreadable, "rows": out}


def _wanted(site, date_from, date_to, all_species, folder, survey_site) -> list[dict]:
    """The rows an export with these filters looks at, before the rows that need a look are taken out."""
    return [r for r in rows(site, date_from, date_to, folder, survey_site) if all_species or r["species"] in DEER]


def export_csv(site=None, date_from=None, date_to=None, all_species=False, include_suspicious=False,
               folder=None, survey_site=None) -> str:
    """The documented CSV: header lines (#) state the filters, what was excluded, and every column's meaning."""
    rs = _wanted(site, date_from, date_to, all_species, folder, survey_site)
    kept = [r for r in rs if include_suspicious or not r["flag"]]
    excluded = len(rs) - len(kept)
    left_out = f"{excluded} row that needs a look left out" if excluded == 1 else f"{excluded} rows that need a look left out"
    methods = sorted({r["method"] for r in kept})
    buf = io.StringIO()
    buf.write(f"# CamTrap Measure export {datetime.now().astimezone().isoformat(timespec='seconds')}; "
              f"camera={site or 'all'}; site={survey_site or 'all'}; "
              f"from={date_from or 'start'}; to={date_to or 'end'}; "
              f"folder={folder or 'all'}; "
              f"species={'all' if all_species else 'white-tailed deer + unsure'}; "
              f"{'rows that need a look included (see flag)' if include_suspicious else left_out}\n")
    buf.write(DOC)
    if len(methods) > 1:
        buf.write(f"# methods present: {', '.join(methods)}; a photo measured with both has one row per animal per method; "
                  "filter on the method column before analysis\n")
    w = csv.DictWriter(buf, COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in kept:
        w.writerow({**r, "photo": basename(r["path"]), "camera": r["site"], "site": site_of(r["site"]),
                    "timestamp": r["captured_at"]})
    return buf.getvalue()


def file_name(key: str | None, date_from: str | None, date_to: str | None) -> str:
    """What an export file is called: the camera or site it holds (or all), then the date range."""
    return f"camtrap-measure_{key or 'all'}_{date_from or 'start'}_{date_to or 'end'}.csv"


def _write_new(folder: Path, name: str, text: str) -> Path:
    """Write `text` to `name` in `folder`, never over a file already there: the next one is "name (2).csv",
    then "(3)", and so on. Opened with "x", so a file that appears in the meantime is not overwritten either."""
    stem, suffix = name.rsplit(".", 1)
    n = 1
    while True:
        p = folder / (name if n == 1 else f"{stem} ({n}).{suffix}")
        try:
            with open(p, "x", encoding="utf-8", newline="") as f:
                f.write(text)
            return p
        except FileExistsError:
            n += 1


def export_split(to: str, by: str, site=None, date_from=None, date_to=None, all_species=False,
                 include_suspicious=False, folder=None, survey_site=None) -> list[Path]:
    """The export as one file per site (by="site") or per camera (by="camera"), written into the folder `to`.
    Each file is `export_csv` narrowed to its site or camera, so it has the same header lines and filters as
    the combined file. Only a site or camera with rows to write gets a file. Raises ValueError with the message."""
    if by not in ("site", "camera"):
        raise ValueError(f"Split by site or camera, not {by!r}")
    d = Path(to).expanduser().resolve()
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    kept = [r for r in _wanted(site, date_from, date_to, all_species, folder, survey_site)
            if include_suspicious or not r["flag"]]
    written = []
    if by == "site":
        for s in sorted({site_of(r["site"]) for r in kept}):
            text = export_csv(site, date_from, date_to, all_species, include_suspicious, folder, survey_site=s)
            written.append(_write_new(d, file_name(s, date_from, date_to), text))
    else:
        for cam in sorted({r["site"] for r in kept}):
            text = export_csv(cam, date_from, date_to, all_species, include_suspicious, folder, survey_site)
            written.append(_write_new(d, file_name(cam, date_from, date_to), text))
    return written
