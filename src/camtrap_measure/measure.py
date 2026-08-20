"""A measurement run: validate the folder against the camera registry, place each photo in a calibration
window by its EXIF timestamp, stream everything with a window through the inference boundary, hold the rest.

One run at a time (one GPU machine); progress lives in `current` and is polled by the UI. Results are
written per photo, so a cancel, a crash or a power cut loses at most the photo in flight: the next run
of the same folder skips every photo that already has a current answer (same method, same calibration
version) unless asked to `rerun`. Photos held for a missing
calibration are re-tried by `start_held()` after the sync that may have provided it.
"""

import threading
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from . import calibration, inference, store

JPEG = {".jpg", ".jpeg"}
# ponytail: in-memory progress + daemon thread, forgotten on restart — the store is the record, a restart
# just means pressing Measure again. Persist `current` if the dept asks where last night's run got to.
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


def _launch(folder: str, site: str, method: str | None, items: list[tuple[Path, str, str]], rerun: bool) -> dict:
    """items = (photo, site, method). `site`/`method` label the run for the UI: '' / None for a run across
    cameras and methods (the held-photo catch-up). Caller holds the lock."""
    global current
    current = {"folder": folder, "site": site, "method": method, "status": "running", "total": len(items), "done": 0, "held": 0,
               "skipped": 0, "detections": 0, "held_reasons": [], "error": None, "cancel": False,
               "started": time.monotonic(), "elapsed_s": 0.0, "eta_s": None}
    threading.Thread(target=_work, args=(current, items, rerun), daemon=True).start()
    return status()


def start(folder: str, method: str, rerun: bool = False) -> dict:
    """Validate, then measure in a background thread. Raises ValueError (bad input) or RuntimeError (busy)."""
    with _lock:
        if current and current["status"] == "running":
            raise RuntimeError("A run is already in progress.")
        d, photos = prepare(folder, method)
        return _launch(str(d), d.name, method, [(p, d.name, method) for p in photos], rerun)


def start_held() -> int | None:
    """Re-try every held photo a sync could have fixed (it has a capture date; the calibration was what was
    missing), each under the method it was first asked with. → photos queued, or None when a run is in
    progress (they wait for the next sync)."""
    with _lock:
        if current and current["status"] == "running":
            return None
        # ponytail: scans the photos table on every sync; index held_reason if a season's table makes Sync feel slow
        items = [(Path(p["path"]), p["site"], p["method"] or inference.DEFAULT_METHOD)
                 for p in store.photos() if p["held_reason"] and p["captured_at"] and Path(p["path"]).is_file()]
        if items:
            _launch("held photos", "", None, items, rerun=False)
        return len(items)


def cancel() -> dict | None:
    """Stop after the photo in flight; what is done stays done."""
    with _lock:
        if current and current["status"] == "running":
            current["cancel"] = True
    return status()


def status() -> dict | None:
    if current is None:
        return None
    r = {k: v for k, v in current.items() if k not in ("started", "cancel")}
    if current["status"] == "running":
        r["elapsed_s"] = round(time.monotonic() - current["started"], 1)
    measured = current["done"] - current["held"] - current["skipped"]  # only inferred photos set the pace
    if measured:
        r["eta_s"] = round(r["elapsed_s"] / measured * (current["total"] - current["done"]), 1)
    return r


def _current_answer(known: dict | None, cal: dict, method: str) -> bool:
    """Does the store already hold this photo's answer under this method and this very calibration? The
    calibration's annotation `updated_at` is its version: a relabel changes it → measure again. Versions are
    compared, never clocks (the dept machine's and the cloud's need not agree)."""
    return bool(known and not known["held_reason"] and known["method"] == method
                and known["calibration_image"] == cal["image_name"] and known["calibration_version"] == cal.get("updated_at"))


def _work(run: dict, items: list[tuple[Path, str, str]], rerun: bool) -> None:
    rows = store.calibrations()
    known = {p["path"]: p for p in store.photos()}
    held: Counter[str] = Counter()
    groups: dict[tuple, tuple[dict, str, list[tuple[Path, dict]]]] = {}  # (calibration, method) → (row, method, [(photo, its row)])
    try:
        for p, site, method in items:  # pass 1: EXIF + window match; held photos are finished here and never get numbers
            ex = calibration.read_exif(p)
            cal, reason = calibration.window_for(site, rows, ex["captured_at"])
            if cal and not store.ref_path(site, cal["image_name"]).exists():
                cal, reason = None, f"The flag photo {cal['image_name']} is not on this computer yet — run Sync, then measure again."
            if cal and not rerun and _current_answer(known.get(str(p)), cal, method):
                run["skipped"] += 1
                run["done"] += 1
                continue
            photo = {"path": str(p), "site": site, **ex, "held_reason": reason,
                     "calibration_image": cal["image_name"] if cal else None,
                     "calibration_version": cal.get("updated_at") if cal else None}
            if cal:
                groups.setdefault((cal["image_name"], method), (cal, method, []))[2].append((p, photo))
                continue
            store.record(photo, method, [])  # clears any numbers it had under a window that has since gone red
            held[reason] += 1
            run["held"] += 1
            run["done"] += 1
            run["held_reasons"] = [{"reason": r, "count": n} for r, n in held.most_common()]
        for cal, method, batch in groups.values():  # pass 2: one backend call per window so real models can batch
            if run["cancel"]:
                break
            cal = {**cal, "ref_path": str(store.ref_path(cal["site"], cal["image_name"]))}
            results = inference.backend([p for p, _ in batch], cal, method)
            for (_, photo), res in zip(batch, results, strict=True):  # a photo's old rows go only once its new ones exist
                store.record({**photo, "match_score": res.match_score}, method, [asdict(d) for d in res.detections])
                run["detections"] += len(res.detections)
                run["done"] += 1
                if run["cancel"]:
                    break
        outcome = ("cancelled", None) if run["cancel"] else ("done", None)
    except Exception as e:
        outcome = ("error", f"{type(e).__name__}: {e}")
    run["elapsed_s"] = round(time.monotonic() - run["started"], 1)
    run["status"], run["error"] = outcome
