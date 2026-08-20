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
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from . import store

REPO = os.environ.get("CAMTRAP_WEIGHTS_REPO", "toqi/camtrap-measure-weights")


class WeightsMissing(Exception):
    """No weights on disk and none could be fetched."""


def hub_check(token: str | None) -> None:
    """Raises whatever the hub raises for this repo with this token; returns when it is reachable."""
    HfApi(token=token).model_info(REPO)


def ensure() -> dict:
    """Check the manifest against the hub and fetch what changed.
    → {dir, version, offline: bool, problem: str | None}. Raises WeightsMissing when nothing is on disk."""
    pinned = os.environ.get("CAMTRAP_WEIGHTS_DIR")
    local = Path(pinned) if pinned else store.DATA_DIR / "weights"
    offline, problem = False, None
    if not pinned:
        token = os.environ.get("HF_TOKEN") or store.config().get("hf_token")
        try:
            hub_check(token)
            snapshot_download(REPO, local_dir=local, token=token)
        except (RepositoryNotFoundError, GatedRepoError) as e:
            problem = f"the weights repo {REPO} rejected the access token ({type(e).__name__}) — check hf_token in config.json"
        except HfHubHTTPError as e:
            problem = f"the weights server answered {e.response.status_code if e.response is not None else '?'} ({e})"
        except Exception:  # DNS, timeouts, connection refused: offline
            offline = True
        if (offline or problem) and not (local / "manifest.json").exists():
            raise WeightsMissing("Model weights are not downloaded yet and " + (
                f"{problem}." if problem else "the download failed — connect to the internet and restart the app."))
    try:
        manifest = json.loads((local / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise WeightsMissing(f"No usable weights manifest in {local} ({e}).") from e
    return {"dir": local, "version": manifest["version"], "offline": offline, "problem": problem}
