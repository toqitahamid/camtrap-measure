"""Model weights: a Hugging Face repo (public since the public-weights change, ADR 0003) mirrored into a local folder.

The repo holds `manifest.json` ({version, megadetector: <file>, speciesnet: <folder>, ...}) next to the
files. `snapshot_download` is the whole update mechanism: it compares every file with the hub,
downloads only missing/changed ones, resumes partial downloads, and leaves unchanged files alone.
It also silently returns the local folder whenever the hub is unreachable *or* refuses the request,
so reachability is checked explicitly first and reported: offline → cached copy with a notice;
refused → cached copy with a warning; neither cached → error.

The repo is public since the public-weights change (2026-10-12, ADR 0003), so no token is needed: every install, a bundle
install too, asks the hub at start and fetches what changed. A token in HF_TOKEN or `~/.camtrap-measure/config.json`
(`hf_token`) is still used when one is set; a token the hub refuses is dropped for that start and the public repo is
read without it. With no token set, huggingface_hub still sends a cached `hf auth login` if the machine has one; a
login the hub refuses is dropped the same way.
`manifest.json` is fetched last, and only once every other file is confirmed at the new commit. An interrupted update
therefore keeps the OLD manifest, but files it already downloaded are new: the app may run a mix of old and new files
under the old version until the next complete update, which changes the version and redoes the answers.
SAM3 (`SKIP`) is never downloaded. `CAMTRAP_WEIGHTS_DIR` points at a ready-made folder and skips the hub entirely
(offline installs, GPU smoke tests).
"""

import json
import os
from fnmatch import fnmatch
import threading
import time
from collections.abc import Callable
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download
from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError
from huggingface_hub.utils import filter_repo_objects

from . import store

REPO = os.environ.get("CAMTRAP_WEIGHTS_REPO", "toqi/camtrap-measure-weights")
# Files in the repo that no install downloads: SAM3 (3.4 GB) serves only the "precise" method, which the window no
# longer offers (user, 2026-10-11). It stays in the repo; a sam3/ folder already on a machine is left alone.
SKIP = ["sam3/*"]


class WeightsMissing(Exception):
    """No weights on disk and none could be fetched."""


class NotUpdated(Exception):
    """snapshot_download returned, but some files on disk are not the pinned commit's."""


def hub_check(token: str | bool | None) -> tuple[int, str | None, list[str]]:
    """Raises whatever the hub raises for this repo with this token (False: send none); returns the size in bytes
    of what `ensure` downloads (every file but SKIP), the repo commit that size belongs to, and those files' names."""
    info = HfApi(token=token).model_info(REPO, files_metadata=True)
    files = list(filter_repo_objects(info.siblings, ignore_patterns=SKIP, key=lambda s: s.rfilename))
    return sum(s.size or 0 for s in files), info.sha, [s.rfilename for s in files]


def _dir_bytes(local: Path) -> int:
    """Bytes of the files `ensure` downloads that are on disk: SKIP and hf_hub's `.cache` records are left out, as
    hub_check's total leaves them out."""
    # ponytail: bytes on disk stand in for bytes downloaded — files left from an older weights version count too,
    # so the bar can sit at 100% while the last file still streams. Pass a tqdm_class to snapshot_download for exact.
    n = 0
    for f in local.rglob("*"):
        rel = f.relative_to(local).as_posix()
        if rel.split("/")[0] == ".cache" or any(fnmatch(rel, pat) for pat in SKIP):
            continue
        try:
            if f.is_file():
                n += f.stat().st_size
        except OSError:  # hf_hub renames .incomplete files under us; Windows refuses stat mid-rename
            pass
    return n


def _watch(local: Path, total: int, progress: Callable[[int, int], None], stop: threading.Event) -> None:
    """Report bytes on disk (finished + partial files) against the hub total while a download runs."""
    while not stop.wait(0.25):
        progress(min(_dir_bytes(local), total), total)


def refused(e: HfHubHTTPError) -> bool:
    """Did the hub refuse this request (bad or unentitled credential, or a repo it will not show)?"""
    code = e.response.status_code if e.response is not None else None
    return code in (401, 403) or isinstance(e, RepositoryNotFoundError)  # GatedRepoError is a RepositoryNotFoundError


def _at_commit(local: Path, filename: str, sha: str | None) -> bool:
    """Did hf_hub last confirm `filename` in `local` at commit `sha`? Read from its per-file download record
    (.cache/huggingface/download/<file>.metadata) through huggingface_hub._local_folder, a private API (checked
    against 1.28.0): every path of _hf_hub_download_to_local_dir that downloads, copies or confirms a file writes the
    commit it resolved there; the one that keeps an old file after a failed HEAD (timeout, 5xx, 429) writes nothing."""
    from huggingface_hub._local_folder import read_download_metadata

    meta = read_download_metadata(local, filename)
    return meta is not None and meta.commit_hash == sha


def _fetch(local: Path, token: str | bool | None, progress: Callable[[int, int], None] | None) -> None:
    """Download what changed, manifest.json last: the manifest is fetched only once every other file is confirmed at
    the commit hub_check saw. So an interrupted update keeps the old manifest; files it already downloaded may be
    new, and the app runs that mix under the old version until the next complete update. Both calls ask for that
    commit: an upload in between cannot pair a new manifest with other files, and snapshot_download, which quietly
    returns the local folder when it cannot list a branch, raises instead. It still returns normally when a single
    file's check fails and an old copy is on disk (hf_hub logs a warning only), hence the check before the manifest."""
    stop, watcher = threading.Event(), None
    try:
        total, sha, files = hub_check(token)
        total = total or 0
        if progress:
            watcher = threading.Thread(target=_watch, args=(local, total, progress, stop), daemon=True)
            watcher.start()
        snapshot_download(REPO, local_dir=local, token=token, revision=sha, ignore_patterns=SKIP + ["manifest.json"])
        old = [f for f in files if f != "manifest.json" and not _at_commit(local, f, sha)]
        if old:
            raise NotUpdated(f"{len(old)} weights file(s) could not be checked against the new version ({old[0]}"
                             f"{', ...' if len(old) > 1 else ''}); the next start tries again")
        hf_hub_download(REPO, "manifest.json", local_dir=local, token=token, revision=sha)
        if progress:
            progress(total, total)
    finally:
        stop.set()
        if watcher:
            watcher.join()  # no progress tick after the caller has moved on


def ensure(progress: Callable[[int, int], None] | None = None) -> dict:
    """Check the manifest against the hub and fetch what changed, calling progress(done_bytes, total_bytes) along
    the way. → {dir, version, offline, problem, notice, bundled}. Raises WeightsMissing when nothing is on disk.

    `problem`: the weights could not be checked (cached copy in use). `notice`: they were checked, but a set token
    or a stored `hf auth login` was refused and the public repo was read without it.

    `bundled` only labels a bundle install (the weights first arrived with the installer, config.json says
    "weights_from": "bundle"). It is checked against the hub like every other install: once the repo is public, a
    machine with no token gets new weights versions too (2026-10-12; before, a bundle install never asked)."""
    pinned = os.environ.get("CAMTRAP_WEIGHTS_DIR")
    local = Path(pinned) if pinned else store.DATA_DIR / "weights"
    offline, problem, notice = False, None, None
    bundled = not pinned and store.config().get("weights_from") == "bundle" and (local / "manifest.json").exists()
    token = os.environ.get("HF_TOKEN") or store.config().get("hf_token")  # optional once the repo is public
    if not pinned:
        try:
            try:
                _fetch(local, token, progress)
            except HfHubHTTPError as e:
                # Refused with our token, or with none: huggingface_hub then sends a cached `hf auth login`, which
                # may be stale. Either way, one retry with no credential at all.
                if not refused(e):
                    raise
                sent = "access token" if token else "Hugging Face login on this computer (`hf auth login`)"
                try:
                    _fetch(local, False, progress)  # False: send no token at all, not even a cached login
                except HfHubHTTPError as e2:
                    if not refused(e2):
                        raise
                    if isinstance(e, RepositoryNotFoundError) and isinstance(e2, RepositoryNotFoundError):
                        # the credential was accepted (a bad one is a plain 401) and nobody may see the repo
                        problem = f"the weights repo {REPO} was not found" + (
                            " (check CAMTRAP_WEIGHTS_REPO)" if os.environ.get("CAMTRAP_WEIGHTS_REPO") else "")
                    elif token:
                        problem = (f"the weights repo {REPO} rejected the access token ({type(e).__name__}) and is "
                                   "not readable without one; fix hf_token in config.json, or remove it once the repo "
                                   "is public")
                    else:
                        problem = (f"the weights repo {REPO} refused the stored {sent} ({type(e).__name__}) and is not "
                                   "readable without it")
                else:
                    notice = (f"The weights repo {REPO} refused the stored {sent} ({type(e).__name__}); the weights "
                              "were checked without it. " + (
                                  "Remove hf_token from config.json (and HF_TOKEN from the environment): the repo "
                                  "needs none." if token else "Run `hf auth logout`: the repo needs no login."))
        except NotUpdated as e:
            problem = str(e)
        except HfHubHTTPError as e:  # not a refusal: those were handled above
            code = e.response.status_code if e.response is not None else None
            problem = f"the weights server answered {code or '?'} ({e})"
        except Exception:  # DNS, timeouts, connection refused: offline
            offline = True
        if (offline or problem) and not (local / "manifest.json").exists():
            raise WeightsMissing("Model weights are not downloaded yet and " + (
                f"{problem}." if problem else "the download failed. Connect to the internet and restart the app."))
    try:
        manifest = json.loads((local / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise WeightsMissing(f"No usable weights manifest in {local} ({e}).") from e
    return {"dir": local, "version": manifest["version"], "offline": offline, "problem": problem, "notice": notice,
            "bundled": bundled}
