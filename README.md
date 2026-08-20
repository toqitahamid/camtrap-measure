# CamTrap Measure

Windows desktop app: distance to each white-tailed deer in camera-trap photos.
Design context in `CONTEXT.md`; spec and tickets in `.scratch/app/`.

## Run (department machine, Windows)

Double-click `run.bat`. Needs [uv](https://docs.astral.sh/uv/) and Git installed; the folder is a
clone of this repository (the installer, ticket 12, makes it one).

### Updates and rollback

`run.bat` is the updater: at every start it fetches the Git remote and checks out `REF`
(default `origin/main`), installs exactly the committed lockfile (`uv sync --frozen`) and
runs the app offline (`uv run --frozen --offline`). Offline, or if anything about the
update fails, it says so in the console and runs the version already on the computer;
if the new version's dependencies cannot be installed, it goes back to the previous
commit and runs that. The running version and checkout show in the page header
(`v0.1.0 (v0.1.0-3-gabc1234)`, i.e. `git describe`) and in `GET /api/health`.

- **Publish a release**: bump `version` in `pyproject.toml`, commit, push `main`;
  optionally tag it (`git tag v0.2.0 && git push --tags`) so it can be pinned later.
- **Roll back a bad release**: create a file `ref.txt` next to `run.bat` containing a
  known-good tag on one line (plain text, no spaces), e.g. `v0.1.0`. The app stays on that
  tag at every start until the file is deleted. No reinstall, no download. (Not by editing
  `run.bat`: Git refuses to update over a changed tracked file, and cmd reads a running
  `.bat` by byte offset — which is also why everything after the checkout sits on the
  launcher's last line, ending in `exit /b`.)
- The lockfile `uv.lock` is committed and installed `--frozen`, so a release is exactly the
  set of packages it was tested with and `uv` never modifies a tracked file on the dept
  machine. The CUDA build of torch is the open question for the installer (ticket 12):
  a frozen sync of the current lock would install the CPU torch.
- **Model weights are not code**: they live in `~/.camtrap-measure/weights/` and are
  updated by the app itself through the weights manifest (see below), never by Git.

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
(`manifest.json` + MegaDetector v1000 + SpeciesNet v4.0.3a + the paper's unified
distance net + RoMa/DINOv2; staged and pushed by `scripts/upload_weights.py`). At every start the engine compares the local copy
in `~/.camtrap-measure/weights/` with the hub and fetches only what changed
(resumable); offline it uses the cached copy and says so. The read token comes
from `HF_TOKEN` or `~/.camtrap-measure/config.json` (`{"hf_token": "..."}`,
written by the installer). `CAMTRAP_WEIGHTS_DIR=<folder>` pins a ready-made
folder and skips the hub. Bump `VERSION` in the upload script when a file changes.

### GPU smoke test (HPC)

`tests/test_gpu_smoke.py` runs the real models through the API on one deer photo
(detection, species, aligned-reference distance with its 90% band, match score)
and is skipped unless CUDA, the extra, `CAMTRAP_WEIGHTS_DIR`, `CAMTRAP_SMOKE_PHOTO`
and `CAMTRAP_SMOKE_FLAG` (the camera's flag photo + `.json`) are all present. On DeltaAI: `scripts/hpc_env.sh` once
(layered venv on the module torch), then `sbatch scripts/gpu_smoke.sbatch`.
On the department's Windows machine torch comes from the installer (ticket 12),
not from `uv sync` — the lockfile deliberately does not pin a CUDA build.

Supabase is read-only from this app: `supabase_ro.py` is the only client and
exposes auth plus three reads; `tests/test_supabase_ro.py` enforces it.
