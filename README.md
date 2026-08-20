# CamTrap Measure

Windows desktop app: distance to each white-tailed deer in camera-trap photos.
Design context in `CONTEXT.md`; spec and tickets in `.scratch/app/`.

## Run (department machine, Windows)

Double-click `run.bat`. Needs [uv](https://docs.astral.sh/uv/) installed.

## Develop

```sh
uv run camtrap-measure --no-window   # engine only, prints the URL (Linux-friendly)
uv run pytest                        # API tests, no GPU needed
cd frontend && npm install && npm run build   # rebuild UI into src/camtrap_measure/ui/
```

The built UI is committed so `uv run` from a fresh clone works without Node.
Rebuild and commit it whenever `frontend/` changes.

Local state (cached login session, SQLite mirror of cloud annotations/sites)
lives in `~/.camtrap-measure/`; override with `CAMTRAP_DATA_DIR`.

Measurement runs go through the inference boundary in `inference.py`. With the
`inference` extra installed (`uv sync --extra inference`, plus a CUDA build of
torch — see below) the engine downloads the model weights at startup and runs real
MegaDetector + SpeciesNet; without it, the shipped `fake` backend produces
deterministic detections per file name and the UI says so, so the whole app
runs and demos without a GPU. Set `CAMTRAP_FAKE_DELAY=0.3` (seconds per photo)
to watch the progress display.

### Model weights

Weights live in the private Hugging Face repo `toqi/camtrap-measure-weights`
(`manifest.json` + MegaDetector v1000 + SpeciesNet v4.0.3a; staged and pushed by
`scripts/upload_weights.py`). At every start the engine compares the local copy
in `~/.camtrap-measure/weights/` with the hub and fetches only what changed
(resumable); offline it uses the cached copy and says so. The read token comes
from `HF_TOKEN` or `~/.camtrap-measure/config.json` (`{"hf_token": "..."}`,
written by the installer). `CAMTRAP_WEIGHTS_DIR=<folder>` pins a ready-made
folder and skips the hub. Bump `VERSION` in the upload script when a file changes.

### GPU smoke test (HPC)

`tests/test_gpu_smoke.py` runs the real models through the API on one deer photo
and is skipped unless CUDA, the extra, `CAMTRAP_WEIGHTS_DIR` and
`CAMTRAP_SMOKE_PHOTO` are all present. On DeltaAI: `scripts/hpc_env.sh` once
(layered venv on the module torch), then `sbatch scripts/gpu_smoke.sbatch`.
On the department's Windows machine torch comes from the installer (ticket 12),
not from `uv sync` — the lockfile deliberately does not pin a CUDA build.

Supabase is read-only from this app: `supabase_ro.py` is the only client and
exposes auth plus three reads; `tests/test_supabase_ro.py` enforces it.
