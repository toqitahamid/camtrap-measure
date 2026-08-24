"""Model weights: a private Hugging Face repo mirrored into a local folder.

The repo holds `manifest.json` ({version, megadetector: <file>, speciesnet: <folder>}) next to the
files. `snapshot_download` is the whole update mechanism: it compares every file with the hub,
downloads only missing/changed ones, resumes partial downloads, and leaves unchanged files alone.
It also silently returns the local folder whenever the hub is unreachable *or* the token is
rejected, so reachability is checked explicitly first and reported: offline → cached copy with
a notice; bad token → cached copy with a warning naming the token; neither cached → error.

The repo id and token come from the environment or `~/.camtrap-measure/config.json` (`hf_token`),
written by the installer. `CAMTRAP_WEIGHTS_DIR` points at a ready-made folder and skips the hub
entirely (offline installs, GPU smoke tests).
"""

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from . import store

REPO = os.environ.get("CAMTRAP_WEIGHTS_REPO", "toqi/camtrap-measure-weights")


class WeightsMissing(Exception):
    """No weights on disk and none could be fetched."""


def hub_check(token: str | None) -> int:
    """Raises whatever the hub raises for this repo with this token; returns the repo's total size in bytes."""
    info = HfApi(token=token).model_info(REPO, files_metadata=True)
    return sum(s.size or 0 for s in info.siblings)


def _dir_bytes(local: Path) -> int:
    # ponytail: bytes on disk stand in for bytes downloaded — files left from an older weights version count too,
    # so the bar can sit at 100% while the last file still streams. Pass a tqdm_class to snapshot_download for exact.
    n = 0
    for f in local.rglob("*"):
        try:
            n += f.stat().st_size
        except OSError:  # hf_hub renames .incomplete files under us; Windows refuses stat mid-rename
            pass
    return n


def _watch(local: Path, total: int, progress: Callable[[int, int], None], stop: threading.Event) -> None:
    """Report bytes on disk (finished + partial files) against the hub total while a download runs."""
    while not stop.wait(0.25):
        progress(min(_dir_bytes(local), total), total)


def ensure(progress: Callable[[int, int], None] | None = None) -> dict:
    """Check the manifest against the hub and fetch what changed, calling progress(done_bytes, total_bytes) along
    the way. → {dir, version, offline, problem, bundled}. Raises WeightsMissing when nothing is on disk.

    `bundled` is the no-token install: the weights arrived with the installer, the hub is never asked,
    and the copy on disk is simply what this machine runs."""
    pinned = os.environ.get("CAMTRAP_WEIGHTS_DIR")
    local = Path(pinned) if pinned else store.DATA_DIR / "weights"
    offline, problem, bundled = False, None, False
    token = os.environ.get("HF_TOKEN") or store.config().get("hf_token")
    if not pinned and not token and store.config().get("weights_from") == "bundle" and (local / "manifest.json").exists():
        # Weights the installer copied in from its own bundle. The department is given the models, not a
        # credential to fetch them, so asking the hub could only fail — the repo is private and its 401
        # reads as "your token is wrong", which would put a permanent false warning on every team
        # machine. The version on disk is what this machine runs until someone installs a newer bundle.
        #
        # The installer says so in config.json rather than this being guessed from the absence of a
        # token: a developer machine has no token either, and reaches the hub through the cached
        # huggingface-cli login, and must go on picking up new weights versions (HANDOFF, gotchas).
        bundled = True
    if not pinned and not bundled:
        stop, watcher = threading.Event(), None
        try:
            total = hub_check(token) or 0
            if progress:
                watcher = threading.Thread(target=_watch, args=(local, total, progress, stop), daemon=True)
                watcher.start()
            snapshot_download(REPO, local_dir=local, token=token)
            if progress:
                progress(total, total)
        except (RepositoryNotFoundError, GatedRepoError) as e:
            problem = f"the weights repo {REPO} rejected the access token ({type(e).__name__}) — check hf_token in config.json"
        except HfHubHTTPError as e:
            problem = f"the weights server answered {e.response.status_code if e.response is not None else '?'} ({e})"
        except Exception:  # DNS, timeouts, connection refused: offline
            offline = True
        finally:
            stop.set()
            if watcher:
                watcher.join()  # no progress tick after the caller has moved on
        if (offline or problem) and not (local / "manifest.json").exists():
            raise WeightsMissing("Model weights are not downloaded yet and " + (
                f"{problem}." if problem else "the download failed — connect to the internet and restart the app."))
    try:
        manifest = json.loads((local / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise WeightsMissing(f"No usable weights manifest in {local} ({e}).") from e
    return {"dir": local, "version": manifest["version"], "offline": offline, "problem": problem,
            "bundled": bundled}
