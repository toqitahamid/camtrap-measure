"""A measurement run: validate the folder against the camera registry, place each photo in a calibration
window by its EXIF timestamp, stream everything with a window through the inference boundary, hold the rest.

One run at a time (one GPU machine); progress lives in `current` and is polled by the UI.
"""

import threading
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from . import calibration, inference, store

JPEG = {".jpg", ".jpeg"}
# ponytail: in-memory progress + daemon thread, no cancel, forgotten on restart. Ticket 10 adds cancel/resume.
current: dict | None = None
_lock = threading.Lock()


def prepare(folder: str, method: str) -> tuple[Path, list[Path]]:
    """Refuse anything that would produce numbers under the wrong geometry. Raises ValueError with the message."""
    d = Path(folder).expanduser().resolve()  # results are keyed by absolute path
    if method not in inference.METHODS:
        raise ValueError(f"Unknown method {method!r}; choose one of {', '.join(inference.METHODS)}.")
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    sites = store.sites()
    if not sites:
        raise ValueError("No cameras known yet — run Sync first.")
    if d.name not in sites:
        raise ValueError(f"'{d.name}' is not a registered camera — the folder must be named exactly like its site "
                         f"in FlagLabel (e.g. {sites[0]}).")
    photos = sorted(p for p in d.iterdir() if p.suffix.lower() in JPEG)
    if not photos:
        raise ValueError(f"No JPEG photos in {d}")
    return d, photos


def start(folder: str, method: str) -> dict:
    """Validate, then measure in a background thread. Raises ValueError (bad input) or RuntimeError (busy)."""
    global current
    with _lock:
        if current and current["status"] == "running":
            raise RuntimeError("A run is already in progress.")
        d, photos = prepare(folder, method)
        current = {"folder": str(d), "site": d.name, "method": method, "status": "running", "total": len(photos),
                   "done": 0, "held": 0, "detections": 0, "held_reasons": [], "error": None,
                   "started": time.monotonic(), "elapsed_s": 0.0, "eta_s": None}
        threading.Thread(target=_work, args=(current, photos), daemon=True).start()
    return status()


def status() -> dict | None:
    if current is None:
        return None
    r = {k: v for k, v in current.items() if k != "started"}
    if current["status"] == "running":
        r["elapsed_s"] = round(time.monotonic() - current["started"], 1)
    measured = current["done"] - current["held"]  # held photos finish in milliseconds; only inferred ones set the pace
    if measured:
        r["eta_s"] = round(r["elapsed_s"] / measured * (current["total"] - current["done"]), 1)
    return r


def _work(run: dict, photos: list[Path]) -> None:
    site, method = run["site"], run["method"]
    rows = store.calibrations()
    held: Counter[str] = Counter()
    groups: dict[str, tuple[dict, list[tuple[Path, dict]]]] = {}  # calibration image → (row, [(photo, its row)])
    try:
        for p in photos:  # pass 1: EXIF + window match; held photos are finished here and never get numbers
            ex = calibration.read_exif(p)
            cal, reason = calibration.window_for(site, rows, ex["captured_at"])
            if cal and not store.ref_path(site, cal["image_name"]).exists():
                cal, reason = None, f"The flag photo {cal['image_name']} is not on this computer yet — run Sync, then measure again."
            photo = {"path": str(p), "site": site, **ex, "held_reason": reason,
                     "calibration_image": cal["image_name"] if cal else None}
            if cal:
                groups.setdefault(cal["image_name"], (cal, []))[1].append((p, photo))
                continue
            store.record(photo, method, [])  # clears any numbers it had under a window that has since gone red
            held[reason] += 1
            run["held"] += 1
            run["done"] += 1
            run["held_reasons"] = [{"reason": r, "count": n} for r, n in held.most_common()]
        for cal, batch in groups.values():  # pass 2: one backend call per window so real models can batch
            cal = {**cal, "ref_path": str(store.ref_path(site, cal["image_name"]))}
            results = inference.backend([p for p, _ in batch], cal, method)
            for (_, photo), res in zip(batch, results, strict=True):  # a photo's old rows go only once its new ones exist
                store.record({**photo, "match_score": res.match_score}, method, [asdict(d) for d in res.detections])
                run["detections"] += len(res.detections)
                run["done"] += 1
        outcome = ("done", None)
    except Exception as e:
        outcome = ("error", f"{type(e).__name__}: {e}")
    run["elapsed_s"] = round(time.monotonic() - run["started"], 1)
    run["status"], run["error"] = outcome
