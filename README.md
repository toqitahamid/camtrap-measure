# CamTrap Measure

A Windows desktop app that gives the distance to each white-tailed deer in camera-trap photos, with a 90%
interval, for camera-trap distance sampling.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version 0.3.0](https://img.shields.io/badge/version-0.3.0-informational.svg)](CITATION.cff)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](docs/INSTALL.md)
[![Paper code: camtrap-distance](https://img.shields.io/badge/paper%20code-camtrap--distance-green.svg)](https://github.com/toqitahamid/camtrap-distance)

**Installing on a department machine?** Follow the step-by-step guide in [docs/INSTALL.md](docs/INSTALL.md).
It covers the one-line installer, what its checks mean, updates, rollback and removal.

## Overview

Camera traps record when an animal passed, but not how far away it was. Distance sampling, the usual
way to turn camera-trap detections into a population density, needs that distance for every animal.
Measuring it by hand from each photo is slow and hard to repeat.

CamTrap Measure reads the distance from the photos. For each photo it finds the animals with
[MegaDetector](https://github.com/agentmorris/MegaDetector) v1000, names the species with
[SpeciesNet](https://github.com/google/cameratrapai) v4.0.3a, and reads the horizontal ground distance to
each animal with the reference-conditioned distance network from the accompanying paper. Every animal gets
a median distance and a 90% interval, in metres. Once the weights and flag labels are on the computer it
measures without a network connection. It needs no programming and exports one CSV row per animal.

It is built for wildlife staff and technicians who run camera-trap surveys and label a flag survey for
each camera in [FlagLabel](https://github.com/toqitahamid/FlagLabel). It was developed for the Center for
Wildlife Sustainability Research at Southern Illinois University Carbondale.

## How it works

1. **Flag survey.** When a camera is set up, flags are placed at known distances in front of it and
   photographed. The flags in this *flag photo* are labeled in FlagLabel.
2. **Sync.** The app pulls the flag labels from FlagLabel (read-only).
3. **Per-camera calibration.** Each flag photo is fitted with a pinhole camera over a flat ground plane
   (focal length, camera height, pitch and roll), which gives a reference distance for every ground pixel
   of that view. A flag photo with too few labels cannot be fitted and is shown as unusable.
4. **Detection and species.** MegaDetector finds the animals in each photo; SpeciesNet names them. Any
   deer-family prediction is reported as white-tailed deer; a weak one (score below 0.2) as `unsure`.
5. **Line-up.** RoMa matches the photo to its flag photo and fits a homography, so the reference distances
   line up with the photo. Fewer than 15 matching points means the photo lines up poorly (a wrong camera, or
   a camera that moved). A night (infrared) photo, and a day photo whose own line-up is weak, borrow the
   line-up of a nearby day photo from the same camera instead
   ([ADR 0001](docs/adr/0001-night-photos-borrow-a-day-line-up.md),
   [ADR 0002](docs/adr/0002-weak-day-photos-borrow-a-day-line-up.md)).
6. **Distance and interval.** The distance network reads the horizontal ground distance and its 90% interval
   at the bottom of each MegaDetector box, where the animal meets the ground.
7. **Export.** The results go to a CSV with one row per animal, ready for distance-sampling software.

## Features

- One-line installer for Windows with no administrator account; automatic updates from GitHub, with a
  one-file rollback to a known-good version.
- Runs a single camera folder or a whole site folder (one subfolder per camera, each photo given its flag
  photo by date).
- Measures the whole folder, a selection, or one photo; runs can be cancelled and resumed, and photos already
  answered are skipped.
- Shows each photo with its boxes, species, distance and interval, a sortable table, and summary figures.
- CSV export, as one file or one file per site or per camera.
- A researcher log with the reasons a number may need a check by eye.
- Never writes to FlagLabel's cloud database: the only client is read-only.
- Without a GPU or the model software it runs a deterministic stand-in backend, so the app can be tried
  and tested anywhere.

## Requirements

Windows 10/11, an NVIDIA GPU (8 GB recommended; less runs with a warning, none
runs on the CPU slowly) with its driver already installed (driver 570 or newer — the one thing
that does need IT), about 14 GB free on the install drive, the WebView2 runtime (built into Windows 11; the checks name
the download if it is missing). A Git or uv already on the PATH is used as is.
`CAMTRAP_INSTALL_DIR` overrides the install folder.

The model weights are about 7 GB and are downloaded at the first start.

## Installation

On a department machine, open PowerShell and paste this one line:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
```

It installs Git and uv for the current user, the app, its Python environment and the CUDA build of
PyTorch, runs preflight checks, and adds a **CamTrap Measure** icon to the desktop and Start menu. The full
guide, including every check, updates, rollback and uninstalling, is in [docs/INSTALL.md](docs/INSTALL.md).

For development on any platform, see [Development](#development).

## Usage

Double-click the desktop shortcut. No console window appears at any point: the shortcut runs
`scripts\launch.vbs`, which starts the launcher hidden; a splash says what it is doing while it checks for
an update, and then the app window opens. Double-clicking the icon again brings that window forward
instead of starting a second copy. (`run.bat` is the same launcher with its steps in a console — the way
in when something needs looking at.) Sign in with your FlagLabel email and
the code it emails you. The window is one screen: three tabs along the top — **Measure**, **Table**, **Results** — and under them
a bar holding the three things every section works on: the camera, which of its flag photos to measure
against, and the photo folder. The distance is always read at the bottom of the MegaDetector box.

1. **Sync** — pulls the flag-photo labels from FlagLabel (first time: a few minutes; later: seconds).
2. **Browse…** to the folder holding one camera's photos. The camera is set from the folder's name, or from
   the nearest of the three folders above it that names one (`MAS_CAM07\DCIM\100BMCIM` is MAS_CAM07;
   `mas cam 2` is MAS_CAM02; the deployment folder `MAS_CAM10B` is MAS_CAM10). When no name gives exactly one camera, the menu says *Pick a camera* and
   Measure waits until you pick one. You can change the camera by hand; a new folder sets it again. Then
   check the flag photo: it follows the camera. (Opened in a browser rather than the app window there is no
   folder chooser, so the bar lets you type the path instead.)
3. **Measure** — the whole folder with *Measure all*, one photo with the button on its row (every row has
   one, whether or not it already has a number) or the one in the panel beside the photo, or a few by
   ticking them in the Table and pressing *Measure these N*. A photo
   you pick explicitly is measured whatever it already holds; *Measure all* skips the ones already
   answered unless you tick *Re-measure*.
4. **Check the numbers** — Measure shows one photo at a time with its boxes labelled `species · distance`,
   the 90% interval on a scale and the flag photo it was read against (one click).
   Arrow keys walk the folder. Table shows the same photos as sortable rows, which is where a confidence
   out of line with its neighbours shows up.
5. **Results** — counts, the distance histogram, per-camera figures, and the CSV export.

The bar at the bottom says what the models are doing. During a run in one camera folder it becomes the
progress line, with the photo in flight and how many are left. During a site run the run card shows the
progress, and the bottom bar keeps its status and warnings.

## Output

The CSV holds data only: the column header row, then one row per animal. It has no `#` note lines and no
warning text, and it holds every result row in the selection. Every row is a
MegaDetector-box answer; a photo an older run also measured with SAM3 still gives one row per animal. A photo
measured only with SAM3 by an older version is not in the CSV until it is measured again. The seven columns, in
order:

| column | meaning |
|---|---|
| `photo` | the file name |
| `camera` | the camera's name in FlagLabel, the camera the photo was measured under (a folder named `mas cam 2` exports as `MAS_CAM02`) |
| `timestamp` | the EXIF capture time, in the camera's local time, with no time zone |
| `species` | what the species model named. `white-tailed deer` is any deer-family prediction; `unsure` is a weak one (score below 0.2) |
| `distance_m` | the horizontal ground distance to the animal in metres, to 2 decimals (the median estimate); empty when no distance could be read |
| `q05_m`, `q95_m` | the bounds of the 90% interval around `distance_m`, in metres, to 2 decimals; empty when no distance could be read |

The three distance columns are rounded to 2 decimals in the file only (for example `11.49`, not
`11.488765716552734`). The app keeps and computes with the full numbers.

The default export holds the white-tailed deer and `unsure` rows; the Species filter set to all species adds
every animal.

### The researcher log

What a researcher needs beyond the numbers is in one file, `logs\research-log.jsonl` in the app folder, not in
the CSV or the window. It has one JSON line per photo each time it is measured: the photo, the camera, day or
night, whether a distance was read, how many animals, and the reasons a number may need a check by eye (for
example "lines up poorly with its flag photo (9 points, needs 15). Wrong camera, or was it moved?"). A night
photo's line also says how it was lined up through a day photo (`night`, with `checks`: `moved`, `unchecked`,
`undated`). A file that cannot be read gets one line per run. The file is never trimmed.

The app gives distances only. Density estimation (for example with R's `Distance` package) is the wildlife
staff's own task, done outside the app from this CSV.

## Model weights

Weights are downloaded from the public Hugging Face repo `toqi/camtrap-measure-weights` (no token needed)
(`manifest.json` + MegaDetector v1000 + SpeciesNet v4.0.3a + the paper's unified
distance net + RoMa/DINOv2 + SAM3; staged and pushed by `scripts/upload_weights.py`; each component keeps
its own licence, listed on the repo's model card). At every start the engine compares the local copy
in `~/.camtrap-measure/weights/` with the hub and fetches only what changed
(resumable), with no token. This holds for a bundle install too: the weights it copied in are checked
like any others. SAM3 (`sam3/`, 3.4 GB) is never downloaded (`weights.SKIP`). Offline the engine uses the
cached copy and says so. A token in `HF_TOKEN` or `~/.camtrap-measure/config.json` (`{"hf_token": "..."}`)
is still sent when set; a rejected one is named in a warning, and the repo is read again without it. `CAMTRAP_WEIGHTS_DIR=<folder>` pins a
ready-made folder and skips the hub. Bump `VERSION` in the upload script when a file changes: each answer
stores the version that read it, and every answer read by another version shows as out of date until it is
measured again.

## Development

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
`inference` extra installed (`uv sync --extra inference`; on Windows this brings the CUDA
build of torch from the lockfile) the engine downloads the model weights at startup and runs real
MegaDetector + SpeciesNet; without it, the shipped `fake` backend produces
deterministic detections per file name and the UI says so, so the whole app
runs and demos without a GPU. Set `CAMTRAP_FAKE_DELAY=0.3` (seconds per photo)
to watch the progress display.

### GPU smoke test (HPC)

`tests/test_gpu_smoke.py` runs the real models through the API on one deer photo
(detection, species, aligned-reference distance with its 90% band, match score)
and is skipped unless CUDA, the extra, `CAMTRAP_WEIGHTS_DIR`, `CAMTRAP_SMOKE_PHOTO`
and `CAMTRAP_SMOKE_FLAG` (the camera's flag photo + `.json`) are all present. On DeltaAI: `scripts/hpc_env.sh` once
(layered venv on the module torch), then `sbatch scripts/gpu_smoke.sbatch`.
On the department's Windows machine torch comes from the same frozen `uv sync --extra inference`:
the lockfile pins the CUDA 12.8 build for Windows.

### Project layout

| path | what it holds |
|---|---|
| `src/camtrap_measure/` | the engine: FastAPI app (`api.py`), calibration (`calibration.py`, `calib/`), detection and distance (`inference.py`, `distance.py`), line-up rules (`lineup.py`), runs (`measure.py`, `batch.py`), export (`report.py`), local store, weights and the read-only FlagLabel client |
| `src/camtrap_measure/ui/` | the built web UI, committed |
| `frontend/` | the UI source (Vite, React, TypeScript) |
| `scripts/` | Windows installer, launcher and uninstaller; bundle and weights upload scripts; HPC scripts |
| `tests/` | the test suite (`uv run pytest`) |
| `docs/adr/` | design decisions |
| `docs/INSTALL.md` | the department-machine install guide |

Supabase is read-only from this app: `supabase_ro.py` is the only client and
exposes auth plus three reads; `tests/test_supabase_ro.py` enforces it.

## Related resources

- [FlagLabel](https://github.com/toqitahamid/FlagLabel): the tool the flag photos are labeled in.
- [camtrap-distance](https://github.com/toqitahamid/camtrap-distance): the research code for the paper's
  distance network.
- [camtrap-distance-flags](https://huggingface.co/datasets/toqi/camtrap-distance-flags): the dataset.
- [camtrap-measure-weights](https://huggingface.co/toqi/camtrap-measure-weights): the model weights this
  app downloads.

## Citation

If you use CamTrap Measure, please cite the software (see also [CITATION.cff](CITATION.cff)):

```bibtex
@software{sarker2026camtrapmeasure,
  title   = {CamTrap Measure: Distance Estimation of White-Tailed Deer in Camera-Trap Photos},
  author  = {Sarker, Toqi Tahamid and Islam, Taminul and Morelock, Seth J. and Bastille-Rousseau, Guillaume and Ahmed, Khaled R.},
  year    = {2026},
  version = {0.3.0},
  license = {MIT},
  url     = {https://github.com/toqitahamid/camtrap-measure}
}
```

and the paper that describes the distance method:

```bibtex
@inproceedings{sarker2026reference,
  title     = {Reference-Conditioned Distance Intervals on Unseen Camera Traps},
  author    = {Sarker, Toqi Tahamid and Islam, Taminul and Morelock, Seth J. and Bastille-Rousseau, Guillaume and Ahmed, Khaled R.},
  booktitle = {Computer Vision for Ecology Workshop, European Conference on Computer Vision (ECCV)},
  year      = {2026}
}
```

## License

MIT; see [LICENSE](LICENSE). The model weights keep their own licences, listed on the weights repo's model
card.

## Acknowledgments

Developed for the Center for Wildlife Sustainability Research, Southern Illinois University Carbondale.
Animal detection uses [MegaDetector](https://github.com/agentmorris/MegaDetector) and species
classification uses [SpeciesNet](https://github.com/google/cameratrapai).
