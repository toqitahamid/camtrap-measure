"""Stage the model weights folder and (optionally) upload it to the Hugging Face repo the app reads (public from
the release of ticket 36).

Run by the researcher, never by the app. Sources are the research caches on the HPC: MegaDetector v1000 from the HF hub cache, SpeciesNet
v4.0.3a from the kagglehub cache, the paper checkpoint `ckpt_unified_scratch_split2_rollfix/best`
from the research repo, RoMa outdoor + DINOv2 ViT-L/14 from the torch hub cache, SAM3 straight from the
gated facebook/sam3 hub repo (transformers format; needs a token that accepted its license).

    python scripts/upload_weights.py --stage /path/to/folder            # build the folder only
    python scripts/upload_weights.py --stage /path/to/folder --upload   # ...and push it to REPO
    python scripts/upload_weights.py --stage /path/to/folder --sam-license /path/to/SAM_LICENSE   # ...with the licence

SAM3 may be redistributed only with a copy of the SAM License. `--sam-license` copies the given file into sam3/;
without it, a licence file that came with the facebook/sam3 snapshot is kept; with neither, a warning is printed.
Nothing is fetched from the internet for the licence.

Bump VERSION whenever a file changes; the app shows it in its status line, stamps each answer with it, and calls
every answer read by another version "Out of date" (measure.current_answer). `--upload` refuses when the repo's
manifest.json already names this VERSION (a changed file under an unchanged version would leave old answers looking
current); `--force` uploads anyway.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from camtrap_measure.weights import REPO  # noqa: E402  one source of truth for the repo id

VERSION = "2026.08.20c"
RESEARCH = Path("/work/nvme/bgte/tsarker/research/distance_estimation")
UNIFIED = RESEARCH / "finetune/ckpt_unified_scratch_split2_rollfix/best"  # paper tab:main checkpoint, seed 1
TORCH_HUB = Path("/work/nvme/bgte/tsarker/caches/torch/hub/checkpoints")
MD = Path("/work/nvme/bgte/tsarker/hf_cache/hub/models--agentmorris--megadetector/snapshots/"
          "222d40e2cf24749c5ce3e67f2f3deb39df30d181/md_v1000.0.0-redwood.pt")
SN = Path("/work/nvme/bgte/tsarker/caches/kagglehub/models/google/speciesnet/pyTorch/v4.0.3a/1")
README = """---
license: other
license_name: per-component
---
# CamTrap Measure weights

Fetched by the CamTrap Measure desktop app at startup via `manifest.json`. Once the repo is public the app reads
it with no token. The app does not download `sam3/`.

Each component keeps its own licence. The repo as a whole has no single licence, so the card says `other`.

| Folder | Component | Licence | Source and credit |
|---|---|---|---|
| `unified/` | Distance net (unified distance + CQR) | CC-BY-NC-4.0, non-commercial use only | Modified: fine-tuned from `depth-anything/Depth-Anything-V2-Metric-Outdoor-Large-hf` (Depth Anything V2, Yang et al.; Base, Large and Giant are CC-BY-NC-4.0 upstream) |
| `speciesnet/` | SpeciesNet v4.0.3a | Apache-2.0 | Google; cite Gadot et al. 2024, IET Computer Vision |
| `roma/dinov2_vitl14_pretrain.pth` | DINOv2 ViT-L/14 | Apache-2.0 | Meta |
| `megadetector/md_v1000.0.0-redwood.pt` | MegaDetector v1000 redwood | MIT | agentmorris/megadetector |
| `roma/roma_outdoor.pth` | RoMa outdoor | Code MIT (Edstedt et al.); upstream states no separate licence for the weights | Parskatt/RoMa |
| `sam3/` | SAM 3 | SAM License (Meta); a copy of the licence must be in `sam3/` before the repo is public | Meta |

- `unified/` — the paper's unified distance+CQR net (Depth-Anything-V2-Large backbone, 7-channel input,
  [q05, q50, q95] output); `ckpt_unified_scratch_split2_rollfix/best` of the research repo.
- `speciesnet/` — the always-crop classifier. Its `info.json` points the detector entry at the MegaDetector file,
  so nothing else is downloaded.
- `roma/` — RoMa outdoor and its DINOv2 ViT-L/14 backbone.
- `sam3/` — SAM 3 in transformers format, for the "precise" method's ground-contact masks; loaded only when that
  method is chosen.
"""


SAM_LICENSE = "LICENSE"  # the name the licence copy gets in sam3/


def _sam_license(sam3: Path, given: Path | None) -> None:
    """Put a copy of the SAM License in sam3/: the given file, else one the facebook/sam3 snapshot brought; else warn."""
    if given:
        shutil.copy2(given, sam3 / SAM_LICENSE)
        print(f"SAM License: copied {given} to {sam3 / SAM_LICENSE}")
        return
    found = [f.name for f in sam3.glob("*") if f.is_file() and f.name.upper().startswith("LICENSE")]
    if found:
        print(f"SAM License: kept {', '.join(found)} from the facebook/sam3 snapshot")
        return
    print(f"WARNING: no SAM License in {sam3}. SAM3 may be redistributed only with a copy of it. Run again with "
          "--sam-license <file> before the repo is made public.", file=sys.stderr)


def stage(out: Path, sam_license: Path | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "megadetector").mkdir(exist_ok=True)
    shutil.copy2(MD, out / "megadetector" / MD.name)
    info = json.loads((SN / "info.json").read_text())
    sn = out / "speciesnet"
    sn.mkdir(exist_ok=True)
    for key in ("classifier", "classifier_labels", "taxonomy", "geofence"):
        shutil.copy2(SN / info[key], sn / info[key])
    info["detector"] = f"../megadetector/{MD.name}"  # a local path: ModelInfo only downloads http(s) entries
    (sn / "info.json").write_text(json.dumps(info, indent=2))
    (out / "unified").mkdir(exist_ok=True)
    for f in ("config.json", "model.safetensors"):
        shutil.copy2(UNIFIED / f, out / "unified" / f)
    (out / "roma").mkdir(exist_ok=True)
    for f in ("roma_outdoor.pth", "dinov2_vitl14_pretrain.pth"):
        shutil.copy2(TORCH_HUB / f, out / "roma" / f)
    from huggingface_hub import snapshot_download
    snapshot_download("facebook/sam3", local_dir=out / "sam3", ignore_patterns=["sam3.pt"])  # the original-format twin, 3.4 GB we never read
    _sam_license(out / "sam3", sam_license)
    (out / "manifest.json").write_text(json.dumps(
        {"version": VERSION, "megadetector": f"megadetector/{MD.name}", "speciesnet": "speciesnet",
         "unified": "unified", "roma": "roma/roma_outdoor.pth", "dinov2": "roma/dinov2_vitl14_pretrain.pth",
         "sam3": "sam3"}, indent=2))
    (out / "README.md").write_text(README)
    print(f"staged {VERSION} in {out}")


def remote_version() -> str | None:
    """The version the repo's manifest.json names; None when the repo or the manifest is not there yet."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

    try:
        return json.loads(Path(hf_hub_download(REPO, "manifest.json")).read_text())["version"]
    except (EntryNotFoundError, RepositoryNotFoundError):
        return None


def same_version(local: str, remote: str | None) -> str | None:
    """Why an upload of version `local` must not go ahead over `remote`, or None when it may."""
    if remote == local:
        return (f"The repo {REPO} already holds weights version {local}. Bump VERSION in scripts/upload_weights.py, "
                "stage again, and upload: the app redoes answers only when the version changes. Use --force to "
                "upload under the same version anyway (only for files the app does not read).")
    return None


def upload(folder: Path, force: bool = False) -> None:
    from huggingface_hub import HfApi
    why = same_version(json.loads((folder / "manifest.json").read_text())["version"], remote_version())
    if why and not force:
        sys.exit(why)
    api = HfApi()
    api.create_repo(REPO, private=True, exist_ok=True)  # a new repo starts private; making it public is a separate step
    api.upload_folder(repo_id=REPO, folder_path=str(folder), commit_message=f"weights {VERSION}")
    print("uploaded:", api.list_repo_files(REPO))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True, help="folder to build")
    ap.add_argument("--upload", action="store_true", help=f"push the folder to {REPO}")
    ap.add_argument("--sam-license", type=Path, help="a copy of Meta's SAM License, copied into sam3/")
    ap.add_argument("--force", action="store_true", help="upload even when the repo already holds this VERSION")
    a = ap.parse_args()
    stage(a.stage, a.sam_license)
    if a.upload:
        upload(a.stage, a.force)
