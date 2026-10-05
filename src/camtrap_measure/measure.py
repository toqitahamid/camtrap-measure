"""A measurement run: every JPEG in a folder, measured against the flag photo the user chose for that camera,
streamed through the inference boundary.

One run at a time (one GPU machine); progress lives in `current` and is polled by the UI. Results are
written per photo, so a cancel, a crash or a power cut loses at most the photo in flight: the next run
of the same folder skips every photo that already has a current answer (same method, same flag photo,
same fidelity, same annotation version) unless asked to `rerun`.

A run happens in stages, and `phase` says which one it is in: the detector looks at every photo first,
then the distance models measure only the photos it found an animal in. The photos with nothing in them
are finished and written during the first stage, which on a real card-dump is most of them.
"""

import os
import stat
import threading
import time
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from . import calibration, inference, store

JPEG = {".jpg", ".jpeg"}
HIDDEN = stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM
# ponytail: in-memory progress + daemon thread, forgotten on restart — the store is the record, a restart
# just means pressing Measure again. Persist `current` if the dept asks where last night's run got to.
current: dict | None = None
_lock = threading.Lock()


def is_photo(f: Path | os.DirEntry) -> bool:
    """Is this file a photo a camera took? A JPEG by its name, and not one of the files that only look like it:
    a name starting with "." (macOS writes an AppleDouble twin, ._IMG_0037.JPG, 4 KB, beside every photo it
    copies to an exFAT or FAT card: seen on 2,835 of them, 2026-10-05), or a file Windows marks hidden or
    system. Every listing asks this one question, so the listing, the count and Measure all always agree."""
    name = f.name
    if os.path.splitext(name)[1].lower() not in JPEG or name.startswith("."):
        return False
    try:
        attrs = getattr(f.stat(), "st_file_attributes", 0)  # Windows only; elsewhere the dot is the rule
    except OSError:
        return False
    return not attrs & HIDDEN


def jpegs(d: Path) -> list[Path]:
    """Every photo directly in the folder (`is_photo`), name order. Not recursive: one folder is one SD-card
    dump, and a subfolder is another camera's. The folder listing shows exactly this set, so what is on screen
    is what Measure all measures."""
    try:
        with os.scandir(d) as entries:  # on Windows the attributes come with the listing: no extra disk reads
            return sorted(Path(e.path) for e in entries if is_photo(e))
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
        raise ValueError("No cameras yet. Press Sync first.")
    if site not in store.sites():
        raise ValueError(f"'{site}' is not a camera in FlagLabel.")
    cal = next((r for r in store.calibrations() if r["site"] == site and r["image_name"] == flag), None)
    if cal is None:
        raise ValueError(f"{site} has no flag photo {flag}. Press Sync and pick one from the list.")
    if not cal["ok"]:
        raise ValueError(cal["reason"])
    if not store.ref_path(site, flag).exists():
        raise ValueError(f"The flag photo {flag} is not on this computer yet. Press Sync, then measure again.")
    if photos is None:
        found = jpegs(d)
        if not found:
            raise ValueError(f"No JPEG photos in {d}")
        return d, found, cal
    chosen = []
    for name in photos:
        p = Path(name).expanduser().resolve()
        if not is_photo(p) or p.parent != d or not p.is_file():
            raise ValueError(f"{name} is not a photo in {d}. Pick photos from the folder you are measuring.")
        chosen.append(p)
    if not chosen:
        raise ValueError("No photos picked. Tick at least one photo, or measure the whole folder.")
    return d, chosen, cal


def start(folder: str, site: str, flag: str, method: str, rerun: bool = False, photos: list[str] | None = None) -> dict:
    """Validate, then measure in a background thread. Raises ValueError (bad input) or RuntimeError (busy)."""
    global current
    with _lock:
        if current and current["status"] == "running":
            raise RuntimeError("A run is already in progress.")
        d, chosen, cal = prepare(folder, site, flag, method, photos)
        current = {"folder": str(d), "site": site, "flag": flag, "method": method,
                   "fidelity": inference.state["fidelity"] or inference.fidelity(), "status": "running",
                   "total": len(chosen), "done": 0, "skipped": 0, "unreadable": 0, "detections": 0, "error": None, "cancel": False,
                   # the run happens in stages, and which one it is in is the difference between "nothing is
                   # happening" and "it is looking through 400 photos for animals before it measures any"
                   "phase": "loading the models", "phase_done": 0, "phase_total": 0,
                   "started": time.monotonic(), "elapsed_s": 0.0, "eta_s": None}
        # picking photos by hand IS the intent to measure them: only a whole-folder run skips what already has an answer
        threading.Thread(target=_work, args=(current, chosen, cal, rerun or photos is not None), daemon=True).start()
        return status()


def _plain(e: Exception) -> str:
    """A run's failure as something to act on. Out of memory is the one a technician can actually fix,
    and on a card shared with the desktop it is the one they will meet (seen 2026-08-23)."""
    if inference.is_oom(e):
        return ("The graphics card ran out of memory because other programs are using it. Close Chrome, "
                "Teams or other heavy windows, then measure again. Photos already done keep their numbers.")
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


def current_answer(known: dict | None, cal: dict, method: str, fidelity: str) -> bool:
    """Does the store already hold this photo's answer under this method, this fidelity and this very
    calibration? The calibration's annotation `updated_at` is its version: a relabel changes it → measure
    again. Versions are compared, never clocks (the dept machine's and the cloud's need not agree).

    Fidelity counts for the same reason a relabel does: it is a different set of settings and so a
    different number. Switching it re-measures the folder rather than leaving two kinds of metres side by
    side with nothing on screen to tell them apart."""
    return bool(known and known["method"] == method and known.get("fidelity") == fidelity
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
    method, fidelity = run["method"], run["fidelity"]
    try:
        batch = []
        for p in photos:
            if not rerun and current_answer(known.get(str(p)), cal, method, fidelity):
                run["skipped"] += 1
                run["done"] += 1
                continue
            if not readable(p):
                run["unreadable"] += 1
                run["done"] += 1
                continue
            batch.append((p, {"path": str(p), "site": run["site"], **calibration.read_exif(p), "held_reason": None,
                              "calibration_image": cal["image_name"], "calibration_version": cal.get("updated_at"),
                              "fidelity": fidelity}))
        if batch and not run["cancel"]:
            ref = {**cal, "ref_path": str(store.ref_path(cal["site"], cal["image_name"]))}
            rows = {str(p): photo for p, photo in batch}

            def progress(phase: str, done: int, total: int) -> None:
                run["phase"], run["phase_done"], run["phase_total"] = phase, done, total

            # The backend finishes photos out of order - an empty frame is done as soon as the detector
            # has looked at it, one with a deer in it not until the distance stage - so each result names
            # its own photo instead of arriving in the order the photos were handed over.
            for res in inference.backend([p for p, _ in batch], ref, method, progress=progress):
                photo = rows[str(res.path)]
                store.record({**photo, "match_score": res.match_score}, method, [asdict(d) for d in res.detections])
                run["detections"] += len(res.detections)
                run["done"] += 1
                if run["cancel"]:
                    break
        outcome = ("cancelled", None) if run["cancel"] else ("done", None)
    except Exception as e:
        outcome = ("error", _plain(e))
    finally:
        # The run is over: the models go and the card goes back to whatever else is running on this
        # machine. The next run loads them again, which is the price of not sitting on 4 GB while idle.
        run["phase"], run["phase_done"], run["phase_total"] = "finished", 0, 0
        try:
            inference.release()
        except Exception:  # freeing memory must never be what turns a finished run into a failed one
            pass
    run["elapsed_s"] = round(time.monotonic() - run["started"], 1)
    run["status"], run["error"] = outcome
