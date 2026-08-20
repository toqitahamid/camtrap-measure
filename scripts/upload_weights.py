"""Stage the model weights folder and (optionally) upload it to the private Hugging Face repo.

Run by the researcher, never by the app. Sources are the research caches on the HPC: MegaDetector v1000 from the HF hub cache, SpeciesNet
v4.0.3a from the kagglehub cache, the paper checkpoint `ckpt_unified_scratch_split2_rollfix/best`
from the research repo, RoMa outdoor + DINOv2 ViT-L/14 from the torch hub cache, SAM3 straight from the
gated facebook/sam3 hub repo (transformers format; needs a token that accepted its license).

    python scripts/upload_weights.py --stage /path/to/folder            # build the folder only
    python scripts/upload_weights.py --stage /path/to/folder --upload   # ...and push it to REPO

Bump VERSION whenever a file changes; the app shows it in its status line.
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
---
# CamTrap Measure weights

Fetched by the CamTrap Measure desktop app at startup via `manifest.json`.

- `megadetector/md_v1000.0.0-redwood.pt` — MegaDetector v1000 (agentmorris/megadetector, MIT).
- `speciesnet/` — SpeciesNet v4.0.3a always-crop classifier (google/speciesnet, Apache-2.0).
  Its `info.json` points the detector entry at the MegaDetector file so nothing else is downloaded.
- `unified/` — the paper's unified distance+CQR net (Depth-Anything-V2-Large backbone, 7-channel
  input, [q05, q50, q95] output); `ckpt_unified_scratch_split2_rollfix/best` of the research repo.
- `roma/` — RoMa outdoor (Edstedt et al., MIT) and its DINOv2 ViT-L/14 backbone (Meta, Apache-2.0).
- `sam3/` — SAM 3 (Meta, SAM License) in transformers format, for the "precise" method's ground-contact masks;
  loaded only when that method is chosen.
"""


def stage(out: Path) -> None:
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
    (out / "manifest.json").write_text(json.dumps(
        {"version": VERSION, "megadetector": f"megadetector/{MD.name}", "speciesnet": "speciesnet",
         "unified": "unified", "roma": "roma/roma_outdoor.pth", "dinov2": "roma/dinov2_vitl14_pretrain.pth",
         "sam3": "sam3"}, indent=2))
    (out / "README.md").write_text(README)
    print(f"staged {VERSION} in {out}")


def upload(folder: Path) -> None:
    from huggingface_hub import HfApi
    api = HfApi()
    api.create_repo(REPO, private=True, exist_ok=True)
    api.upload_folder(repo_id=REPO, folder_path=str(folder), commit_message=f"weights {VERSION}")
    print("uploaded:", api.list_repo_files(REPO))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, required=True, help="folder to build")
    ap.add_argument("--upload", action="store_true", help=f"push the folder to {REPO}")
    a = ap.parse_args()
    stage(a.stage)
    if a.upload:
        upload(a.stage)
