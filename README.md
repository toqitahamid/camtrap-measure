# CamTrap Measure

Windows desktop app: distance to each white-tailed deer in camera-trap photos.
Design context in `CONTEXT.md`; spec and tickets in `.scratch/app/`; picking the work up on
another machine: `HANDOFF.md`.

## Install (department machine, Windows — no expert needed)

Open PowerShell (Start → type "PowerShell" → Enter) and paste this one line:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
```

It installs Git and uv (via winget), downloads the app into `%LOCALAPPDATA%\CamTrapMeasure`,
builds its environment (the CUDA build of PyTorch comes from the lockfile — a few GB once),
runs the preflight checks before the big download and asks for two things:

- the **Hugging Face read token** for the model weights (ask the researcher; Enter skips it
  for now — the app then runs with made-up numbers until the token is set);
- the **FlagLabel email and password** (the app remembers the login).

Every failed check prints what it found and what to do, in plain words: GPU driver missing or
older than 570 (install/update from nvidia.com/drivers — a warning, the app still installs and
runs on the CPU), less than 20 GB free, a host that the network or firewall blocks
(`github.com` for updates, `huggingface.co` for weights, the FlagLabel cloud for sync — a
warning), WebView2 runtime missing, a rejected token, a wrong password, and finally the
engine's own health check. Fix, run the same line again.

It ends with a **CamTrap Measure** shortcut on the desktop and starts the app; the first start
downloads the model weights (~7 GB) and shows the progress in the window. To repair an install
later, double-click `install.bat` in the app folder — every step is a no-op when already done.

Requirements: Windows 10/11, an NVIDIA GPU (8 GB recommended; less runs with a warning, none
runs on the CPU slowly), ~20 GB free, the WebView2 runtime (built into Windows 11; the checks
name the download if it is missing). The script installs Git and uv through winget (App
Installer from the Microsoft Store); if winget is missing, install them by hand first —
Git from https://git-scm.com/download/win, uv with
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` — then
paste the install line again. `CAMTRAP_INSTALL_DIR` overrides the install folder.

## Run (department machine, Windows)

Double-click the desktop shortcut (= `run.bat` in the app folder).

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
