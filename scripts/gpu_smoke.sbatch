#!/bin/bash
#SBATCH -A bgte-dtai-gh
#SBATCH -p ghx4
#SBATCH --gpus-per-node=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48g
#SBATCH -t 00:20:00
#SBATCH -J camtrap_smoke
#SBATCH -o scripts/slurm-%j.out
# GPU smoke test: real MegaDetector + SpeciesNet through the API on one deer photo.
# Prereqs: scripts/hpc_env.sh once; a staged weights folder (scripts/upload_weights.py --stage).
set -euo pipefail
source /opt/cray/pe/lmod/lmod/init/bash
module load python/miniforge3_pytorch/2.11.0
conda activate base
cd "$SLURM_SUBMIT_DIR"
ENV=/work/nvme/bgte/tsarker/envs/camtrap_gpu
export CAMTRAP_WEIGHTS_DIR=${CAMTRAP_WEIGHTS_DIR:-/work/nvme/bgte/tsarker/caches/camtrap_weights}
export CAMTRAP_SMOKE_PHOTO=${CAMTRAP_SMOKE_PHOTO:-/work/nvme/bgte/tsarker/research/distance_estimation/data/MAS/MAS_CAM22/IMG_0526.JPG}
# the same camera's flag photo (+ its .json annotation next to it), taken 8 days before the deer photo
export CAMTRAP_SMOKE_FLAG=${CAMTRAP_SMOKE_FLAG:-/work/nvme/bgte/tsarker/research/distance_estimation/flaglabel-dataset/MAS_CAM22/IMG_0001.JPG}
export CAMTRAP_DATA_DIR=$(mktemp -d)
[ -f "$CAMTRAP_WEIGHTS_DIR/manifest.json" ] || "$ENV/bin/python" scripts/upload_weights.py --stage "$CAMTRAP_WEIGHTS_DIR"
"$ENV/bin/python" -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0))"
"$ENV/bin/python" -m pytest -q -rs -s tests/test_gpu_smoke.py
