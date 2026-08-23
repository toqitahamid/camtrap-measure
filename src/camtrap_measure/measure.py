"""A measurement run: every JPEG in a folder, measured against the flag photo the user chose for that camera,
streamed through the inference boundary.

One run at a time (one GPU machine); progress lives in `current` and is polled by the UI. Results are
written per photo, so a cancel, a crash or a power cut loses at most the photo in flight: the next run
of the same folder skips every photo that already has a current answer (same method, same flag photo,
same annotation version) unless asked to `rerun`.
"""

import threading
import time
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from . import calibration, inference, store

JPEG = {".jpg", ".jpeg"}
# ponytail: in-memory progress + daemon thread, forgotten on restart — the store is the record, a restart
# just means pressing Measure again. Persist `current` if the dept asks where last night's run got to.
current: dict | None = None
_lock = threading.Lock()


def jpegs(d: Path) -> list[Path]:
    """Every JPEG directly in the folder, name order. Not recursive: one folder is one SD-card dump, and a
    subfolder is another camera's. The folder listing shows exactly this set, so what is on screen is what
    Measure all measures."""
    try:
        return sorted(p for p in d.iterdir() if p.suffix.lower() in JPEG)
    except OSError as e:  # a share that dropped, or a folder this Windows account may not read
        raise ValueError(f"Could not read {d}: {e}")


def prepare(folder: str, site: str, flag: str, method: str, photos: list[str] | None = None) -> tuple[Path, list[Path], dict]:
    """Check the folder, the camera and its flag photo, and settle which photos the run measures — the whole
    folder, or the picked subset in the order given. Raises ValueError with the message."""
    d = Path(folder).expanduser().resolve()  # results are keyed by absolute path
    if method not in inference.METHODS:
        raise ValueError(f"Unknown method {method!r}; choose one of {', '.join(inference.METHODS)}.")
    if not d.is_dir():
        raise ValueError(f"Folder not found: {d}")
    if not store.sites():
        raise ValueError("No cameras known yet — run Sync first.")
    if site not in store.sites():
        raise ValueError(f"'{site}' is not a camera in FlagLabel.")
    cal = next((r for r in store.calibrations() if r["site"] == site and r["image_name"] == flag), None)
    if cal is None:
        raise ValueError(f"{site} has no flag photo {flag} — run Sync and pick one from the list.")
    if not cal["ok"]:
        raise ValueError(cal["reason"])
    if not store.ref_path(site, flag).exists():
        raise ValueError(f"The flag photo {flag} is not on this computer yet — run Sync, then measure again.")
    if photos is None:
        found = jpegs(d)
        if not found:
            raise ValueError(f"No JPEG photos in {d}")
        return d, found, cal
    chosen = []
    for name in photos:
        p = Path(name).expanduser().resolve()
        if p.suffix.lower() not in JPEG or p.parent != d or not p.is_file():
            raise ValueError(f"{name} is not a photo in {d} — pick photos from the folder you are measuring.")
        chosen.append(p)
    if not chosen:
        raise ValueError("No photos picked — tick at least one photo, or measure the whole folder.")
    return d, chosen, cal


def start(folder: str, site: str, flag: str, method: str, rerun: bool = False, photos: list[str] | None = None) -> dict:
    """Validate, then measure in a background thread. Raises ValueError (bad input) or RuntimeError (busy)."""
    global current
    with _lock:
        if current and current["status"] == "running":
            raise RuntimeError("A run is already in progress.")
        d, chosen, cal = prepare(folder, site, flag, method, photos)
        current = {"folder": str(d), "site": site, "flag": flag, "method": method, "status": "running",
                   "total": len(chosen), "done": 0, "skipped": 0, "unreadable": 0, "detections": 0, "error": None, "cancel": False,
                   "started": time.monotonic(), "elapsed_s": 0.0, "eta_s": None}
        # picking photos by hand IS the intent to measure them: only a whole-folder run skips what already has an answer
        threading.Thread(target=_work, args=(current, chosen, cal, rerun or photos is not None), daemon=True).start()
        return status()


def _plain(e: Exception) -> str:
    """A run's failure as something to act on. Out of memory is the one a technician can actually fix,
    and on a card shared with the desktop it is the one they will meet (seen 2026-08-23)."""
    if inference.is_oom(e):
        return ("The GPU ran out of memory. Other programs are using it — close Chrome, Teams or other "
                "heavy windows, then measure again. The photos already done keep their numbers.")
    return f"{type(e).__name__}: {e}"


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
    measured = current["done"] - current["skipped"] - current["unreadable"]  # only inferred photos set the pace
    if measured:
        r["eta_s"] = round(r["elapsed_s"] / measured * (current["total"] - current["done"]), 1)
    return r


def current_answer(known: dict | None, cal: dict, method: str) -> bool:
    """Does the store already hold this photo's answer under this method and this very calibration? The
    calibration's annotation `updated_at` is its version: a relabel changes it → measure again. Versions are
    compared, never clocks (the dept machine's and the cloud's need not agree)."""
    return bool(known and known["method"] == method
                and known["calibration_image"] == cal["image_name"] and known["calibration_version"] == cal.get("updated_at"))


def readable(p: Path) -> bool:
    """A truncated or non-JPEG file must not sink the whole batch; it is counted and skipped."""
    try:
        with Image.open(p) as im:
            im.verify()
        return True
    except Exception:
        return False


def _work(run: dict, photos: list[Path], cal: dict, rerun: bool) -> None:
    known = {p["path"]: p for p in store.photos()}
    method = run["method"]
    try:
        batch = []
        for p in photos:
            if not rerun and current_answer(known.get(str(p)), cal, method):
                run["skipped"] += 1
                run["done"] += 1
                continue
            if not readable(p):
                run["unreadable"] += 1
                run["done"] += 1
                continue
            batch.append((p, {"path": str(p), "site": run["site"], **calibration.read_exif(p), "held_reason": None,
                              "calibration_image": cal["image_name"], "calibration_version": cal.get("updated_at")}))
        if batch and not run["cancel"]:
            ref = {**cal, "ref_path": str(store.ref_path(cal["site"], cal["image_name"]))}
            results = inference.backend([p for p, _ in batch], ref, method)  # one call: real models batch
            for (_, photo), res in zip(batch, results, strict=True):  # a photo's old rows go only once its new ones exist
                store.record({**photo, "match_score": res.match_score}, method, [asdict(d) for d in res.detections])
                run["detections"] += len(res.detections)
                run["done"] += 1
                if run["cancel"]:
                    break
        outcome = ("cancelled", None) if run["cancel"] else ("done", None)
    except Exception as e:
        outcome = ("error", _plain(e))
    run["elapsed_s"] = round(time.monotonic() - run["started"], 1)
    run["status"], run["error"] = outcome
