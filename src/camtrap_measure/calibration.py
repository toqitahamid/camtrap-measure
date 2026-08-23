"""App-level calibration: fit one flag photo, say in plain language when it cannot be, list them per camera.

A flag photo is unusable only when it cannot be fitted at all (ticket 15, the researcher's verdict after
the first dept session): not labeled yet in FlagLabel, missing from storage, or too few flag labels for
the 4-parameter fit. No validity windows, no leave-one-out quality verdict — the user picks the flag
photo to measure against. Research QC (monotonicity, LOO in `calib/qc.py`) stays a diagnostic.
"""

import json
from datetime import datetime
from io import BytesIO

from PIL import Image

from .calib.data import from_annotation
from .calib.model_b import MIN_DISTINCT_DISTS, MIN_GROUND_OBS, ModelB
_DATE_TIME_ORIGINAL, _EXIF_IFD, _MAKE, _MODEL = 0x9003, 0x8769, 0x010F, 0x0110


def read_exif(src) -> dict:
    """{captured_at, make, model} from a path or file object; every field None if unreadable.
    captured_at is DateTimeOriginal as naive local ISO ('2026-03-13T12:37:33') — naive on purpose:
    trail cameras have no zone, and flag photos and local photos are matched on the same field."""
    out = {"captured_at": None, "make": None, "model": None}
    try:
        with Image.open(src) as im:
            exif = im.getexif()
            out["make"], out["model"] = exif.get(_MAKE), exif.get(_MODEL)
            raw = exif.get_ifd(_EXIF_IFD).get(_DATE_TIME_ORIGINAL)
        out["captured_at"] = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:  # truncated file, corrupt EXIF (Pillow raises SyntaxError/struct.error), missing/odd date
        pass
    return out


LABEL_KEYS = ("wire_ground_points", "flag_to_ground_spans", "flag_vertical_spans", "flag_horizontal_spans")


def fit(annotation: dict, jpeg: bytes | None) -> dict:
    """→ {site, image_name, updated_at, captured_at, ok, reason, model}. jpeg=None: not in storage.
    Never raises: a broken row becomes a red reason, not a failed sync."""
    image = annotation["image_name"]
    row = {"site": annotation["site"], "image_name": image, "updated_at": annotation.get("updated_at"),
           "captured_at": None, "ok": False, "reason": None, "model": None}
    if jpeg is None:
        row["reason"] = f"{image} is missing from cloud storage — re-upload it in FlagLabel."
        return row
    row["captured_at"] = read_exif(BytesIO(jpeg))["captured_at"]  # dated even when unlabeled, so a fresh re-flag closes the old window
    data = annotation.get("data") or {}
    if annotation.get("status") != "annotated" or not any(data.get(k) for k in LABEL_KEYS):
        row["reason"] = f"{image} is not labeled yet — label its flags in FlagLabel."
        return row
    try:
        return _judge(row, data, image)
    except Exception as e:  # malformed labels (missing keys, 0 m distance, ...) — one row must not sink the sync
        row["reason"] = f"{image} could not be fitted ({type(e).__name__}: {e}) — relabel it in FlagLabel."
        return row


def _judge(row: dict, data: dict, image: str) -> dict:
    photo = from_annotation({**data, "site": row["site"], "image": image})
    model = ModelB.fit(photo)
    if not model.ok:
        n, nd = len(photo.ground), len({g.dist for g in photo.ground})
        row["reason"] = (f"{image} has too few flag labels ({n} ground marks at {nd} distances; "
                         f"needs {MIN_GROUND_OBS} at {MIN_DISTINCT_DISTS}) — label more flags in FlagLabel.")
        return row
    row["ok"], row["model"] = True, json.dumps(model.to_dict())
    return row


def cameras(sites: list[str], rows: list[dict]) -> list[dict]:
    """Every camera with its flag photos, newest first (undated last); usable ones carry ok=True."""
    by_site: dict[str, list[dict]] = {s: [] for s in sites}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)
    out = []
    for site, cals in sorted(by_site.items()):
        cals.sort(key=lambda r: (r["captured_at"] is None, r["captured_at"] or ""), reverse=True)
        cals.sort(key=lambda r: r["captured_at"] is None)  # dated first (newest first), undated after
        out.append({"site": site, "flags": [{"image_name": c["image_name"], "captured_at": c["captured_at"],
                                             "ok": c["ok"], "reason": c["reason"]} for c in cals]})
    return out
