#!/bin/bash
# Build /work/nvme/bgte/tsarker/envs/camtrap_gpu for the GPU smoke test on DeltaAI (aarch64, GH200).
# Same recipe as the research repo's deer_seg: a venv layered on the module torch (pip, not uv — uv
# would replace the module torch with a PyPI one). speciesnet is installed --no-deps because its
# onnx2torch→onnx dependency has no aarch64 wheel and the module stack already ships onnx 1.19.1.
set -euo pipefail
source /opt/cray/pe/lmod/lmod/init/bash
module load python/miniforge3_pytorch/2.11.0
conda activate base
ENV=/work/nvme/bgte/tsarker/envs/camtrap_gpu
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ -d "$ENV" ] || python -m venv --system-site-packages "$ENV"
source "$ENV/bin/activate"
pip install -q megadetector pytest
pip install -q --no-deps speciesnet onnx2torch
pip install -q absl-py cloudpathlib kagglehub reverse_geocoder humanfriendly yolov5
pip install -q -e "$REPO"
python - <<'PY'
import torch, megadetector, speciesnet, fastapi, camtrap_measure
assert "/sw/user/python/miniforge3-pytorch" in torch.__file__, torch.__file__
print("camtrap_gpu env OK, torch", torch.__version__)
PY
