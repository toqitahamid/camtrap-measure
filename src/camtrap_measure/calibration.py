"""App-level calibration: fit one flag photo, judge it in plain language, group per camera.

Verdict rules (a photo is red on the first that trips):
  1. not labeled yet in FlagLabel
  2. no EXIF capture date (the validity window cannot open)
  3. too few flag labels for the 4-parameter fit
  4. a flag whose leave-one-out prediction is off by > LOO_MAX_REL of its label
Research QC (monotonicity, LOO) is noisier than that on real data — every one
of the 122 research photos has some monotonicity violation — so only gross LOO
outliers (14/122 photos at 0.5) turn a camera red.
"""

import json
from datetime import datetime
from io import BytesIO

from PIL import Image

from .calib.data import from_annotation
from .calib.model_b import MIN_DISTINCT_DISTS, MIN_GROUND_OBS, ModelB
from .calib.qc import loo_cv

LOO_MAX_REL = 0.5  # |held-out prediction - label| / label; 0.5 flags ~11% of research photos
TRANSECT = {"L": "left", "C": "centre", "R": "right"}
_DATE_TIME_ORIGINAL, _EXIF_IFD = 0x9003, 0x8769


def capture_date(jpeg: bytes) -> str | None:
    """EXIF DateTimeOriginal as naive local ISO ('2026-03-13T12:37:33'); None if absent.
    Naive on purpose: trail cameras have no zone, and local photos are matched on the same field."""
    try:
        raw = Image.open(BytesIO(jpeg)).getexif().get_ifd(_EXIF_IFD).get(_DATE_TIME_ORIGINAL)
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").isoformat()
    except (OSError, TypeError, ValueError):
        return None


def fit(annotation: dict, jpeg: bytes | None) -> dict:
    """→ {site, image_name, updated_at, captured_at, ok, reason, model}. jpeg=None: not in storage."""
    image = annotation["image_name"]
    row = {"site": annotation["site"], "image_name": image, "updated_at": annotation.get("updated_at"),
           "captured_at": None, "ok": False, "reason": None, "model": None}
    data = annotation.get("data") or {}
    labeled = any(data.get(k) for k in ("wire_ground_points", "flag_to_ground_spans", "flag_vertical_spans"))
    if annotation.get("status") != "annotated" or not labeled:
        row["reason"] = f"{image} is not labeled yet — label its flags in FlagLabel."
        return row
    if jpeg is None:
        row["reason"] = f"{image} is missing from cloud storage — re-upload it in FlagLabel."
        return row
    row["captured_at"] = capture_date(jpeg)
    if row["captured_at"] is None:
        row["reason"] = f"Could not read the capture date from {image} — re-upload the original camera file in FlagLabel."
        return row
    photo = from_annotation({**data, "site": annotation["site"], "image": image})
    model = ModelB.fit(photo)
    if not model.ok:
        n, nd = len(photo.ground), len({g.dist for g in photo.ground})
        row["reason"] = (f"{image} has too few flag labels ({n} ground marks at {nd} distances; "
                         f"needs {MIN_GROUND_OBS} at {MIN_DISTINCT_DISTS}) — label more flags in FlagLabel.")
        return row
    # A mislabeled flag also skews its neighbours' held-out predictions, so among the
    # flags over the relative threshold, blame the one furthest off in metres.
    suspects = [r for r in loo_cv(photo) if r["pred_b"] is not None and abs(r["err_b"]) / r["dist"] > LOO_MAX_REL]
    if suspects:
        worst = max(suspects, key=lambda r: abs(r["err_b"]))
        row["reason"] = (f"In {image} the {worst['dist']:g} m flag on the {TRANSECT[worst['transect']]} transect "
                         f"measures as {worst['pred_b']:.1f} m from the other flags — check its distance label in FlagLabel.")
        return row
    row["ok"], row["model"] = True, json.dumps(model.to_dict())
    return row


def cameras(sites: list[str], rows: list[dict]) -> list[dict]:
    """Per-camera verdict + validity windows. rows: fit() outputs for every synced annotation."""
    by_site: dict[str, list[dict]] = {s: [] for s in sites}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)
    out = []
    for site, cals in sorted(by_site.items()):
        cals.sort(key=lambda r: (r["captured_at"] is not None, r["captured_at"] or ""))  # undated first
        dates = [c["captured_at"] for c in cals]
        # a window closes when the next flag photo is taken, good or bad: a re-flag may mean a moved camera
        windows = [{"image_name": c["image_name"], "captured_at": c["captured_at"],
                    "window_end": next((d for d in dates[i + 1:] if d), None) if c["captured_at"] else None,
                    "ok": c["ok"], "reason": c["reason"]} for i, c in enumerate(cals)]
        bad = [w for w in windows if not w["ok"]]
        if not cals:
            reason = f"No flag photo for {site} in FlagLabel — upload and label one."
        else:
            reason = bad[-1]["reason"] if bad else None  # latest problem first: it governs new photos
        out.append({"site": site, "verdict": "red" if reason else "green", "reason": reason, "calibrations": windows})
    return out
