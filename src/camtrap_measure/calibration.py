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
    if row["captured_at"] is None:
        row["reason"] = f"Could not read the capture date from {image} — re-upload the original camera file in FlagLabel."
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
    # A mislabeled flag also skews its neighbours' held-out predictions, so among the
    # flags over the relative threshold, blame the one furthest off in metres.
    # ponytail: serial LOO (~0.2 s/photo, ~1 min first sync of 300) inside the request; thread pool if it drags.
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
        # Verdict = the governing window (latest dated photo: it is what new photos match), plus any
        # undated photo (cannot be placed in time, so it must be fixed). Older bad windows stay red in
        # the row list only — they hold photos from their own period, not the camera.
        dated = [w for w in windows if w["captured_at"]]
        undated_bad = [w for w in windows if not w["captured_at"] and not w["ok"]]
        if not cals:
            reason = f"No flag photo for {site} in FlagLabel — upload and label one."
        elif undated_bad:
            reason = undated_bad[0]["reason"]
        else:
            reason = dated[-1]["reason"] if dated else None
        out.append({"site": site, "verdict": "red" if reason else "green", "reason": reason, "calibrations": windows})
    return out


def window_for(site: str, rows: list[dict], captured_at: str | None) -> tuple[dict | None, str | None]:
    """Match one local photo to its calibration: the latest dated flag photo of `site` taken at or before
    `captured_at`. → (calibration row, None) or (None, plain-language reason it is held)."""
    if captured_at is None:
        return None, "Photo has no capture date in its EXIF — it cannot be placed in a calibration window."
    mine = [r for r in rows if r["site"] == site]
    undated = [r for r in mine if not r["captured_at"]]
    if undated:  # same rule as the camera verdict: a flag photo that cannot be placed in time may be a re-flag
        return None, undated[0]["reason"]
    dated = sorted((r for r in mine if r["captured_at"]), key=lambda r: r["captured_at"])
    before = [r for r in dated if r["captured_at"] <= captured_at]
    if not before:
        day = captured_at[:10]
        return None, (f"No flag photo of {site} taken on or before {day} — upload and label one in FlagLabel, "
                      f"or its photos from before {dated[0]['captured_at'][:10]} cannot be measured."
                      if dated else f"No flag photo of {site} taken on or before {day} — upload and label one in FlagLabel.")
    row = before[-1]
    return (row, None) if row["ok"] else (None, row["reason"])
