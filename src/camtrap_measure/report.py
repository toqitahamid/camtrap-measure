"""Views over the results store: the post-run summary, the photo-by-photo review, and the gated CSV export.

`review` lists every measured photo with its boxes and their numbers — the researcher checks an answer on
the photo itself, not on a summary line. A detection row is *suspicious* when its number should not enter
an analysis unread: the photo did not match its flag photo well (misfiled / moved camera), the detector was
unsure of the box, SpeciesNet was unsure of the animal, or no ground could be read under it. Such rows are
marked in the review and left out of the export unless asked — and the file says how many it left out.
"""

import csv
import io
import statistics
from datetime import datetime
from ntpath import basename  # splits on / and \ alike: paths come from the dept's Windows machine or a Linux test box

from . import store
from .distance import MIN_INLIERS
from .inference import MIN_SPECIES_SCORE

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


def rows(site=None, date_from=None, date_to=None) -> list[dict]:
    """Detection rows in scope, each with `flag` = '; '.join(reasons)."""
    out = []
    for r in store.detections():
        if (site and r["site"] != site) or not _in_range(r["captured_at"], date_from, date_to):
            continue
        out.append({**r, "flag": "; ".join(reasons(r))})
    return out


def photos(site=None, date_from=None, date_to=None) -> list[dict]:
    """Photo rows in scope — measured and held."""
    return [p for p in store.photos() if (not site or p["site"] == site) and _in_range(p["captured_at"], date_from, date_to)]


def summary(site=None, date_from=None, date_to=None, all_species=False) -> dict:
    """Counts, a histogram of deer distances, and one line per camera. `suspicious` counts the rows the
    export with the same species setting would leave out, so the number on screen is the number in the file."""
    ph, rs = photos(site, date_from, date_to), rows(site, date_from, date_to)
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


def review(site=None, date_from=None, date_to=None) -> list[dict]:
    """One entry per measured photo - its boxes, their numbers and why any of them is suspicious - so the
    researcher can check the answer on the photo itself instead of trusting the summary. Photos with no
    animal are in the list too: seeing that a photo was looked at and held nothing is part of the check."""
    out = []
    by_path: dict[str, dict] = {}
    for p in photos(site, date_from, date_to):
        by_path[p["path"]] = e = {
            "path": p["path"], "photo": basename(p["path"]), "site": p["site"], "captured_at": p["captured_at"],
            "flag_image": p["calibration_image"], "match_score": p["match_score"], "method": p["method"],
            "reasons": [p["held_reason"]] if p["held_reason"] else [], "detections": []}
        out.append(e)
    for r in rows(site, date_from, date_to):
        e = by_path.get(r["path"])
        if e is None:  # a detection whose photo row is out of scope: never drop a box silently
            continue
        why = reasons(r)
        e["detections"].append({**{k: r[k] for k in DET_KEYS}, "reasons": why})
        e["reasons"] += [w for w in why if w not in e["reasons"]]
    for e in out:
        e["detections"].sort(key=lambda d: (d["method"], d["idx"]))
    return sorted(out, key=lambda e: (e["site"], e["captured_at"] or "", e["path"]))


def export_csv(site=None, date_from=None, date_to=None, all_species=False, include_suspicious=False) -> str:
    """The documented CSV: header lines (#) state the filters, what was excluded, and every column's meaning."""
    rs = [r for r in rows(site, date_from, date_to) if all_species or r["species"] in DEER]
    kept = [r for r in rs if include_suspicious or not r["flag"]]
    excluded = len(rs) - len(kept)
    methods = sorted({r["method"] for r in kept})
    buf = io.StringIO()
    buf.write(f"# CamTrap Measure export {datetime.now().astimezone().isoformat(timespec='seconds')}; "
              f"site={site or 'all'}; from={date_from or 'start'}; to={date_to or 'end'}; "
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
