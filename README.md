# CamTrap Measure

Windows desktop app: distance to each white-tailed deer in camera-trap photos.
Design context in `CONTEXT.md`; spec and tickets in `.scratch/app/`; picking the work up on
another machine: `HANDOFF.md`.

## Install (department machine, Windows — no expert needed)

Open PowerShell (Start → type "PowerShell" → Enter) and paste this one line:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
```

No administrator account is needed at any point. It gets Git (a portable copy unpacked into
`%LOCALAPPDATA%\Programs\MinGit`) and uv (its own user-scope installer), downloads the app into
`%LOCALAPPDATA%\CamTrapMeasure`, builds its environment (Python 3.12 and the CUDA build of
PyTorch come from the lockfile — a few GB once), runs the preflight checks before the big
download and asks for two things:

- the **Hugging Face read token** for the model weights (ask the researcher; Enter skips it
  for now — the app then runs with made-up numbers until the token is set);
- the **FlagLabel email**, then the **one-time code** FlagLabel emails to it (the app remembers
  the login; there is no password).

Every failed check prints what it found and what to do, in plain words: GPU driver missing or
older than 570 (install/update from nvidia.com/drivers — a warning, the app still installs and
runs on the CPU), less than 20 GB free, a host that the network or firewall blocks
(`github.com` for updates, `huggingface.co` for weights, the FlagLabel cloud for sync — a
warning), WebView2 runtime missing, a rejected token, an unknown email or a wrong code, and finally the
engine's own health check. Fix, run the same line again.

The installer runs in a window of its own — the steps tick past with a details pane under them, and a
failure says what to do about it in a dialog. It ends with a **CamTrap Measure** icon on the desktop and
in the Start menu, an entry in **Settings ▸ Apps** (per-user, so removing it needs no administrator
either), and the app started; the first start downloads the model weights (~7 GB) and shows the progress
in the window. To repair an install later, double-click `install.bat` in the app folder — every step is a
no-op when already done. `install.ps1 -Console` does the same in a console, for a machine where the
window cannot be drawn.

Requirements: Windows 10/11, an NVIDIA GPU (8 GB recommended; less runs with a warning, none
runs on the CPU slowly) with its driver already installed (driver 570 or newer — the one thing
that does need IT), ~20 GB free, the WebView2 runtime (built into Windows 11; the checks name
the download if it is missing). A Git or uv already on the PATH is used as is.
`CAMTRAP_INSTALL_DIR` overrides the install folder.

## Run (department machine, Windows)

Double-click the desktop shortcut. No console window appears at any point: the shortcut runs
`scripts\launch.vbs`, which starts the launcher hidden; a splash says what it is doing while it checks for
an update, and then the app window opens. Double-clicking the icon again brings that window forward
instead of starting a second copy. (`run.bat` is the same launcher with its steps in a console — the way
in when something needs looking at.) Sign in with your FlagLabel email and
the code it emails you. The window is one screen: three tabs along the top — **Measure**, **Table**, **Results** — and under them
a bar holding the four things every section works on: the camera, which of its flag photos to measure
against, the photo folder, and where the distance is read.

1. **Sync** — pulls the flag-photo labels from FlagLabel (first time: a few minutes; later: seconds).
2. **Pick the camera and its flag photo**, then **Browse…** to the folder holding that camera's photos.
   The folder's name does not matter; you choose which flag photo it belongs to. (Opened in a browser
   rather than the app window there is no folder chooser, so the bar lets you type the path instead.)
3. **Measure** — the whole folder with *Measure all*, one photo with the button on its row (every row has
   one, whether or not it already has a number) or the one in the panel beside the photo, or a few by
   ticking them in the Table and pressing *Measure these N*. A photo
   you pick explicitly is measured whatever it already holds; *Measure all* skips the ones already
   answered unless you tick *Re-measure*.
4. **Check the numbers** — Measure shows one photo at a time with its boxes labelled `species · distance`,
   the 90% interval on a scale, the alignment score and the flag photo it was read against (one click).
   Arrow keys walk the folder. Table shows the same photos as sortable rows, which is where a confidence
   or an alignment score out of line with its neighbours shows up.
5. **Results** — counts, the distance histogram, per-camera figures, and the CSV export.

The bar at the bottom says what the models are doing; during a run it becomes the progress line, with the
photo in flight, how many are left and a Stop button.

### Updates and rollback

`scripts\launcher.ps1` is the updater: at every start it fetches the Git remote and checks out `REF`
(default `origin/main`), installs exactly the committed lockfile (`uv sync --frozen --extra inference`)
and starts the app. Offline, or if anything about the update fails, the splash says so and the version
already on the computer runs; if the new version's dependencies cannot be installed, it goes back to the
previous commit and runs that; if even that fails, a dialog says so and offers the log
(`logs\launcher.log` in the app folder). A clone with local changes is never updated — that is a
developer's tree, not an install. The running version and checkout show in the page header
(`v0.1.0 (v0.1.0-3-gabc1234)`, i.e. `git describe`) and in `GET /api/health`.

- **Publish a release**: bump `version` in `pyproject.toml`, commit, push `main`;
  optionally tag it (`git tag v0.2.0 && git push --tags`) so it can be pinned later.
- **Roll back a bad release**: create a file `ref.txt` next to `run.bat` containing a
  known-good tag on one line (plain text, no spaces), e.g. `v0.1.0`. The app stays on that
  tag at every start until the file is deleted. No reinstall, no download. (Not by editing
  the launcher: Git refuses to update over a changed tracked file. The update itself lives in
  PowerShell now, which reads a script whole before running it — cmd re-read a running `.bat` by byte
  offset, which is why `run.bat` still keeps its one command on the last line, ending in `exit /b`.)
- **Remove it**: Settings ▸ Apps ▸ CamTrap Measure ▸ Uninstall. It asks before deleting the app, and asks
  separately about the measurements and downloaded models in `~/.camtrap-measure`, which are kept unless
  they are asked for by name.
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
