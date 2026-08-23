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

from . import calibration, measure, store
from .distance import MIN_INLIERS
from .inference import DEFAULT_METHOD, MIN_SPECIES_SCORE

LOW_CONF = 0.5  # ponytail: detector confidence below this is "weak box"; tune with the dept's first season
DEER = {"white-tailed deer", "unsure"}  # default export: the survey target plus animals that may be it
BIN_M = 2  # histogram bin width, metres

COLUMNS = ["photo", "camera", "timestamp", "species", "distance_m", "q05_m", "q95_m", "confidence", "method",
           "match_score", "flag"]
DOC = """\
# photo: file name; camera: site (the photo folder's name); timestamp: EXIF capture time in the camera's local time, no zone
# species: SpeciesNet name — 'white-tailed deer' is any deer-family prediction, 'unsure' a weak one (score < {min_species})
# distance_m: horizontal ground distance to the animal in metres (median estimate)
# q05_m, q95_m: bounds of the 90% interval around distance_m, metres; empty when no distance could be read
# confidence: MegaDetector box confidence, 0-1; method: md = distance read at the box bottom, sam3 = at the SAM3 mask's feet
# match_score: alignment inliers between this photo and its flag photo (fewer than {min_inliers} = suspicious)
# flag: empty for a clean row, else why the row is suspicious (such rows are in this file only if you asked for them)
""".format(min_inliers=MIN_INLIERS, min_species=MIN_SPECIES_SCORE)


def reasons(row: dict) -> list[str]:
    """Why a detection row is suspicious; [] when it is clean. Thresholds are named so the gallery explains itself."""
    out = []
    aligned = row["match_score"] is not None and row["match_score"] >= MIN_INLIERS
    if row["match_score"] is None:
        out.append("the photo did not align to its flag photo — no distance")
    elif not aligned:
        out.append(f"poor match to the flag photo ({row['match_score']} < {MIN_INLIERS} points) — misfiled or moved camera?")
    if row["confidence"] < LOW_CONF:
        out.append(f"low detector confidence ({row['confidence']:.2f} < {LOW_CONF})")
    if row["species"] == "unsure":
        out.append("species unsure — may not be a deer")
    if row["distance_m"] is None and aligned:
        out.append("no ground under the animal — no distance")
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


def rows(site=None, date_from=None, date_to=None, folder=None) -> list[dict]:
    """Detection rows in scope, each with `flag` = '; '.join(reasons)."""
    out = []
    for r in store.detections():
        if (site and r["site"] != site) or not _in_range(r["captured_at"], date_from, date_to):
            continue
        if not _in_folder(r["path"], folder):
            continue
        out.append({**r, "flag": "; ".join(reasons(r))})
    return out


def photos(site=None, date_from=None, date_to=None, folder=None) -> list[dict]:
    """Photo rows in scope — measured and held."""
    return [p for p in store.photos()
            if (not site or p["site"] == site) and _in_range(p["captured_at"], date_from, date_to)
            and _in_folder(p["path"], folder)]


def summary(site=None, date_from=None, date_to=None, all_species=False, folder=None) -> dict:
    """Counts, a histogram of deer distances, and one line per camera. `suspicious` counts the rows the
    export with the same species setting would leave out, so the number on screen is the number in the file.
    `folder` narrows all of it to the photos measured out of one folder — what RESULTS shows by default, so
    the screen answers for the folder in the bar rather than for everything ever measured."""
    ph, rs = photos(site, date_from, date_to, folder), rows(site, date_from, date_to, folder)
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


UNREADABLE = "this file could not be read — it may be truncated or not really a JPEG"

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
               "match_score": None, "method": None, "flag_image": None, "reasons": [], "detections": []}
        if seen:
            row.update(captured_at=seen["captured_at"], match_score=seen["match_score"], method=seen["method"],
                       flag_image=seen["calibration_image"],
                       stale=cal is not None and not measure.current_answer(seen, cal, method),
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


def export_csv(site=None, date_from=None, date_to=None, all_species=False, include_suspicious=False,
               folder=None) -> str:
    """The documented CSV: header lines (#) state the filters, what was excluded, and every column's meaning."""
    rs = [r for r in rows(site, date_from, date_to, folder) if all_species or r["species"] in DEER]
    kept = [r for r in rs if include_suspicious or not r["flag"]]
    excluded = len(rs) - len(kept)
    methods = sorted({r["method"] for r in kept})
    buf = io.StringIO()
    buf.write(f"# CamTrap Measure export {datetime.now().astimezone().isoformat(timespec='seconds')}; "
              f"site={site or 'all'}; from={date_from or 'start'}; to={date_to or 'end'}; "
              f"folder={folder or 'all'}; "
              f"species={'all' if all_species else 'white-tailed deer + unsure'}; "
              f"{'suspicious rows included (see flag)' if include_suspicious else f'{excluded} suspicious rows excluded'}\n")
    buf.write(DOC)
    if len(methods) > 1:
        buf.write(f"# methods present: {', '.join(methods)} — a photo measured with both has one row per animal per method; "
                  "filter on the method column before analysis\n")
    w = csv.DictWriter(buf, COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in kept:
        w.writerow({**r, "photo": basename(r["path"]), "camera": r["site"], "timestamp": r["captured_at"]})
    return buf.getvalue()
