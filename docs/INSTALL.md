# Installing CamTrap Measure

This guide is for the department machines that run the app: installing it, what the installer checks,
updating and rolling back, and removing it. For what the app does and how to use it, see the
[README](../README.md).

## Install (department machine, Windows — no expert needed)

Open PowerShell (Start → type "PowerShell" → Enter) and paste this one line:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
```

No administrator account is needed at any point. It gets Git (a portable copy unpacked into
`%LOCALAPPDATA%\Programs\MinGit`) and uv (its own user-scope installer), asks where to install
(a parent folder: `D:\` becomes `D:\CamTrapMeasure`; `-InstallTo <folder>` skips the question),
downloads the app into `<folder>\app`, keeps the models and results in `<folder>\data` and uv's
cache and Python beside them (remembered in `<folder>\camtrap-install.json`, never in user environment variables), builds its environment (Python 3.12 and the CUDA build of
PyTorch come from the lockfile — a few GB once), runs the preflight checks before the big
download, and asks for no Hugging Face credential: the model weights are downloaded from a
public Hugging Face repo, so no token is needed. The app window asks for the **FlagLabel email**, then the **one-time code** FlagLabel
emails to it (the app remembers the login; there is no password).

Every failed check prints what it found and what to do, in plain words: GPU driver missing or
older than 570 (install/update from nvidia.com/drivers — a warning, the app still installs and
runs on the CPU), too little free space for what is still to install (a warning), a host that the network or firewall blocks
(`github.com` for updates, `huggingface.co` for weights, the FlagLabel cloud for sync — a
warning), WebView2 runtime missing, a Hugging Face token that someone set and the hub rejects (a warning), an
unknown email or a wrong code (when the preflight runs in a console and asks for the FlagLabel login), and finally the
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
that does need IT), about 14 GB free on the install drive, the WebView2 runtime (built into Windows 11; the checks name
the download if it is missing). A Git or uv already on the PATH is used as is.
`CAMTRAP_INSTALL_DIR` overrides the install folder.

## Updates and rollback

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
  separately about the measurements and downloaded models (`<folder>\data`, or `~/.camtrap-measure` for an install from before the install folder could be chosen), which are kept unless
  they are asked for by name.
- The lockfile `uv.lock` is committed and installed `--frozen`, so a release is exactly the
  set of packages it was tested with and `uv` never modifies a tracked file on the dept
  machine. On Windows the lock pins the CUDA 12.8 build of torch and torchvision (the `pytorch-cu128`
  index in `pyproject.toml`), so the frozen sync installs the CUDA build; Linux gets PyPI's build.
- **Model weights are not code**: they live in `~/.camtrap-measure/weights/` and are
  updated by the app itself through the weights manifest (see [Model weights](../README.md#model-weights)), never by Git.
