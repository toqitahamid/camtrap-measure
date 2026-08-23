# CamTrap Measure — CONTEXT

Decisions from the 2026-08-19/20 grilling session. Each carries its why; change
one only with a reason that beats the recorded one.

## What this is

Windows desktop app for the wildlife department. Measures the distance to each
white-tailed deer in camera-trap photos, with a 90% interval per animal, feeding
distance-sampling abundance analysis. Companion to cloud FlagLabel (labeling
stays there; this app never annotates). Research provenance: the unified
distance+CQR net and calibration method from `../distance_estimation` (CV4E/ECCV
2026 paper; checkpoint `ckpt_unified_scratch_split2_rollfix`).

## Division of labor

- **Cloud FlagLabel** (exists, unchanged): dept uploads + labels flag photos →
  schema-v2 JSON in Supabase `annotations.data` (project `uggjzcbozdxvuawxddrn`).
- **CamTrap Measure** (this repo): Sync annotations → fit per-photo 4-param
  calibration (`run_qc` logic) → detect + measure local photos on their GPU →
  local results DB → CSV export.
- Photos never upload; only annotation JSONs come down.

## Stack (settled — do not relitigate)

- **Backend**: uv-managed Python, FastAPI, PyTorch pipeline (MegaDetector,
  optional SAM3, SpeciesNet, RoMa, unified net). All logic lives here, tested here.
- **Frontend**: Vite + React + TypeScript → `dist/`, served by FastAPI. No
  router, no state library. Frontend stays dumb: renders JSON, posts clicks.
- **Shell**: pywebview (WebView2 window). Tauri rejected: Python sidecar
  babysitting, updater targets the wrong layer, signing burden.
- **Auto-update**: uv upgrade-on-launch from GitHub in `run.bat`; offline →
  runs current version. Weights excluded from code updates.
- **Weights**: private Hugging Face model repo, `snapshot_download`, versioned
  manifest checked at startup, token in app config.
- **Results**: local SQLite (single GPU machine is the record — Q13); rerun of a
  photo replaces its rows, so one current answer per photo. CSV is an export
  view, never the store.

## Pipeline decisions

- **Detection**: MegaDetector always; SAM3 as a second selectable method
  ("precise, slower"). Which is *default* is decided by a planned comparison on
  existing labeled data in `../distance_estimation` (bbox-bottom vs mask ground
  contact), not by assumption.
- **Species**: SpeciesNet per detection. Export filter = white-tailed deer +
  generic deer-family labels + unsure; unsure also goes to the suspicious
  gallery; show-all toggle. Survey target is white-tailed deer only (Q10).
- **Distance read**: aligned-reference (RoMa) is the deploy path; per-camera
  reference features cached. RoMa match score doubles as misfile/moved-camera
  alarm.
- **Camera identity**: folder name == `annotations.site` (dept instruction,
  enforced: folder must exist in `sites`). 167 cameras across MAS/MOR/SHB/SRF/TON
  as of 2026-08-19.
- **Calibration windows**: flag photo EXIF `DateTimeOriginal` (read from
  Supabase Storage at sync) opens a window; photo matched by folder + its EXIF
  timestamp → latest window ≤ timestamp. No window → photo held with a banner
  naming the flags to label. **Ticket zero: verify EXIF survives Storage upload
  on one SRF image; fallback = `captured_at` column filled at upload.**

## Calibration verdicts (ticket 04, 2026-08-20)

- Fit + QC ported verbatim from `../distance_estimation@6a6eed5` into
  `calib/`; change the math there first.
- Research QC is diagnostic, not pass/fail: all 122 research photos have some
  monotonicity violation and LOO error >1 m somewhere. Red therefore means only
  a genuinely unusable photo: not labeled, no EXIF date, too few labels, or a
  flag whose leave-one-out prediction is off by >50% of its label
  (`LOO_MAX_REL`; 14/122 research photos, each naming a clear outlier such as
  an "8 m" flag measuring 12.6 m). Tune the constant with real dept feedback.
- A window closes when the next flag photo of that camera is taken, good, bad
  or not yet labeled — a re-flag may mean a moved camera, so old geometry is
  never extended past it. Capture dates are naive local time (trail cameras
  have no zone).
- The camera verdict is the governing window (latest dated flag photo) plus
  any undated photo; an older bad window stays red in its own row only, since
  it holds photos from its period without making the camera un-ready now.
- Red rows are re-fitted on every sync (a re-upload or storage blip fixes
  itself); green rows refit only when the annotation's `updated_at` changes.

## Calibration QC threshold after the first dept sync (2026-08-23)

- First sync: 264 labeled flag photos, 314 windows. The LOO rule at 0.5 turned 20 photos
  red; the researcher checked the flagged labels and found them correct. Probe results
  (scratch, not committed): worst-flag LOO relative error per photo p50 27%, p90 46%,
  p95 59%; the fit's own residual at every flag is ~0 by construction (plane + per-transect
  correction interpolated through the flags), so a fitted-residual rule cannot see a
  mislabel at all — tried and discarded. Six of the 20 were first/last flags on their
  transect (held-out = extrapolation past the correction's range); the rest are real
  terrain/click scatter (e.g. MAS_CAM07 left transect: the 8 m mark sits between the
  12 m and 13 m marks in the image) that the fit absorbs with the flag present.
- `LOO_MAX_REL` 0.5 → 0.75: clears those 18, keeps MOR_CAM14/IMG_1452 (2 m flag the
  others put at 5.2 m) and TON_CAM12/IMG_6692 (15 m flag at 28.3 m). Red rows are
  re-fitted at every sync, so the next sync after the update applies it. Remaining red
  is then overwhelmingly "not labeled yet" (≈45 windows, 25 of them an `IMG_0001.JPG`).
- Still open: whether LOO at the ends of a transect should be skipped outright, and a
  yellow "check this flag" state that would warn without holding photos.

## Measurement runs (ticket 05, 2026-08-20)

- Inference boundary = `inference.backend(paths, calibration, method)`, one
  call per calibration window so a real backend can batch; yields one
  detection list per photo. The shipped `fake` is deterministic per file name.
- A photo matches the latest dated flag photo of its folder's camera taken at
  or before its EXIF timestamp (a photo taken at the re-flag instant belongs
  to the new window). Held when: no EXIF date, no flag photo before it, the
  matching window is red, or the camera has an undated flag photo (same rule
  as the verdict) — the hold reason is the window's own red reason.
- Results: `photos` keyed by absolute path (EXIF make/model, window used,
  hold reason); `detections` keyed by (path, idx, method). A measured photo
  replaces its rows for that method only once the new ones exist (a crash
  keeps earlier answers); a held photo drops its rows for every method, so a
  photo can never keep numbers from a window that has since gone red.
- One run at a time; progress is polled (`GET /api/run`), not streamed — the
  page stays a dumb poller.

## Weights and real inference (ticket 06, 2026-08-20)

- Weights repo: private HF `toqi/camtrap-measure-weights` (move to the org later
  via HF repo transfer; id is `CAMTRAP_WEIGHTS_REPO`). `manifest.json`
  {version, megadetector, speciesnet}; `snapshot_download` into
  `~/.camtrap-measure/weights/` is the entire update/resume/cache mechanism.
  SpeciesNet's `info.json` has its detector entry pointed at the MegaDetector
  file so loading never reaches for the internet.
- Engine start: `inference.warmup()` in a thread — extra importable? weights
  present or fetchable? models load? — result in `/api/status.inference`; runs
  are refused (503) while loading or on error. No extra → fake backend with a
  visible "numbers are made up" warning, never silently. `snapshot_download`
  returns the local folder silently on *any* hub error, so reachability is
  checked first: offline → "(offline — cached copy)" notice; rejected token →
  cached copy plus a warning naming the token; nothing cached → error.
- Real backend: MegaDetector v1000 animal boxes (conf ≥ 0.15) → SpeciesNet
  v4.0.3a crop per box, batched; FP16 via autocast; SpeciesNet batch size is
  half the largest of 64…1 whose forward pass fits the free VRAM at start
  (the other half is headroom for MegaDetector), halved again on any OOM
  mid-run; a card under 8 GB runs with a warning. Species
  rule: any cervidae ≥ 0.2 → "white-tailed deer"; score < 0.2 → "unsure";
  else SpeciesNet's common name. No geofence yet (research ran `--country USA`;
  add when out-of-region labels show up). Distance fields are NULL until 07.
- CPU fallback is automatic with a loud warning; CUDA build of torch is the
  installer's job (ticket 12), the lockfile pins only CPU-agnostic packages.
- Verified 2026-08-20: weights repo live (manifest 2026.08.20), first-start
  download + no-op recheck work from the app venv; GPU smoke passed on a GH200
  (`sbatch scripts/gpu_smoke.sbatch`, job 2988630, 34 s).

## Real distance (ticket 07, 2026-08-20)

- Port of the paper's deploy path, pinned to `../distance_estimation@6a6eed5`
  in `distance.py`: RoMa (outdoor, pure-torch corr) matches the window's flag
  photo to the target (both banner-cropped at row 995/1080), MAGSAC homography
  target→reference, a stride-4 target grid warped into the reference and read
  through the reference ModelB gives D_R (2–18 m, else 0), 7-channel input
  [target RGB, reference RGB, D_R/20] at 518² into the unified DA-V2 net,
  [q05, q50, q95] upsampled to the photo and read as a 5×5 nanmedian at each
  box's bottom-centre. Raw band, no conformal widening (paper R4 rollfix).
- Reference = the flag photo of the matched calibration window, cached at
  sync under `~/.camtrap-measure/refs/<site>/<image>`; a green calibration
  whose file is missing is refetched on the next sync, and a photo whose flag
  photo is not on disk is held ("run Sync"). Reference tensors are computed
  once per calibration per engine lifetime (RoMa features are not cacheable
  through its API; ~1 s/photo on a GH200 is the ceiling).
- `match_score` = homography inlier count, stored per photo; below
  `distance.MIN_INLIERS` (15, the published gate) the photo is suspicious
  (misfiled / moved camera). Empty frames skip alignment (`match_score` NULL).
  The warp/displacement ratio half of the research gate is dropped: on RoMa it
  only produced false abstentions (transport/gate_roma.py).
- Weights manifest 2026.08.20b adds `unified/` (paper checkpoint
  `ckpt_unified_scratch_split2_rollfix/best`, 1.3 GB), `roma/roma_outdoor.pth`
  and `roma/dinov2_vitl14_pretrain.pth`. The [inference] extra gains
  transformers≥5, safetensors, kornia, einops, loguru and `romatch` pinned to
  RoMa@77f8d68 (HPC installs it --no-deps: poselib has no aarch64 wheel).
- Unified net runs bf16 where supported, else fp16; RoMa keeps its fp16 default.
- Verified 2026-08-20 on a GH200 (`sbatch scripts/gpu_smoke.sbatch`): MAS_CAM22
  deer photo against its 2025-12-20 flag photo → white-tailed deer 0.968,
  6.7 m [4.9, 9.2], ~500 inliers; 60–95 s including model load. `match_score`
  varies a few % run to run (RoMa samples matches stochastically).

## Precise method (ticket 08, 2026-08-20)

- Within a run the methods differ only in the readout point of the same distance map:
  `md` at the box's bottom centre, `sam3` at the feet of a SAM3 mask prompted with that box (median column
  of the mask's lowest 5% of rows, lowest row — the research contact-pixel rule,
  `04_lindenthal_zeroshot/prep.py`). SAM3's box prompt is an exemplar and returns every
  instance it sees, so the mask is matched to the box by IoU ≥ 0.5 (`MIN_MASK_IOU`); a
  box SAM3 cannot outline falls back to the box bottom rather than losing its number.
- SAM3 = transformers' port (`Sam3Model`, transformers ≥ 5 is already a dependency; no
  vendored repo). Weights `sam3/` in manifest 2026.08.20c, mirrored from the gated
  `facebook/sam3` hub repo minus its original-format `sam3.pt`. Loaded on the first
  precise run of the engine's lifetime, never at start — the fast method pays no VRAM
  for it (the 3.4 GB download itself is not lazy: `snapshot_download` mirrors the whole
  repo at first start). The image is encoded once per photo; each box prompts on the
  shared features. bf16 autocast as the research ran it; a card without bf16 runs SAM3
  in fp32 (fp16 overflows its backbone), never fp16.
- `DEFAULT_METHOD = "md"` (inference.py) until the research comparison (open item 2)
  says otherwise; `/api/methods` returns the default plus a label and plain-language hint
  per method, and the run screen shows the hint under the selector.
- Rows are keyed (path, idx, method) since ticket 05: a rerun with the other method
  adds rows, a rerun with the same method replaces only its own. Each detection row also
  carries the `match_score` it was read under — every run re-aligns, so the photo-level
  score (latest run, used for empty frames) cannot stand in for the other method's rows.
- Verified 2026-08-20 on a GH200 (`sbatch scripts/gpu_smoke.sbatch`, jobs 2988962 and
  2989015): the MAS_CAM22 deer reads 6.7 m [4.9, 9.2] at the box bottom and 6.4 m
  [4.7, 8.7] at the mask's feet; SAM3 loads in ~40 s on first use. Across runs the fast
  reading of the same photo moved 5.6 → 7.8 m with the RoMa draw (354 vs 524 inliers): the alignment's
  run-to-run spread is larger than the method gap and is the thing to pin down before
  the comparison that sets the default (fixed seed, or matches averaged over draws).

## Summary, gallery, export (ticket 09, 2026-08-20)

- `report.py` is a pure view over the store; nothing is stored about suspicion, it is
  recomputed from the row (`report.reasons`): match_score NULL (no alignment) or
  < `distance.MIN_INLIERS`; confidence < `report.LOW_CONF` (0.5, tune with the first
  season); species "unsure"; aligned but no ground under the animal. Held photos join the
  gallery with their hold reason. Every reason names its threshold.
- Summary histogram and per-camera median are over deer rows (white-tailed deer +
  unsure, the export default); counts of animals are over everything. Bins are 2 m.
- Export: `GET /api/export.csv?site&date_from&date_to&all_species&include_suspicious`.
  Capture dates are compared as YYYY-MM-DD in the camera's local time. The file opens
  with `#` lines — filters used, how many suspicious rows were left out (or that they
  are in, with `flag` naming why), and every column's meaning and unit — so it is
  unambiguous without the app (R `comment.char="#"`, pandas `comment="#"`). Columns are
  the spec's ten plus `match_score`. `photo` is the file name; camera + timestamp make
  it unique enough for a statistician; the absolute path stays in the store.
- Gallery thumbnails come from `GET /api/photo?path=` which serves only paths a run has
  recorded (640 px JPEG); boxes are drawn by the page from the stored fractions.
  pywebview `ALLOW_DOWNLOADS` is on so the CSV link saves through the native dialog.

## Resume, catch-up, offline (ticket 10, 2026-08-20)

- A run writes per photo, so a cancel (`POST /api/run/cancel`, stops after the photo in
  flight), a crash or a power cut loses at most one photo. There is no separate resume:
  Measure on the same folder skips every photo that already has a *current answer* —
  same method, same calibration image, same calibration version (the annotation's
  `updated_at`; a relabel changes it and the photo is measured again). Versions are
  compared, never clocks: the dept machine's and the cloud's need not agree. `rerun`
  (a checkbox) replaces current answers too. So a folder that accumulates a season's
  SD-card dumps is measured incrementally by the same button.
- `photos` gained `method` and `calibration_version` for that rule. Run status gained
  `skipped` and the `cancelled` state; the ETA counts only inferred photos.
- After a successful sync the engine re-tries every held photo still on disk, each under
  the method it was first asked with (`measure.start_held()`; response `remeasure` =
  photos queued, `null` when a run is busy or models are not ready — they wait for the
  next sync). Photos still uncalibrated are simply held again with the current reason.
  Run progress is not persisted across restarts: the store is the record and a restart
  means pressing Measure again.
- Offline: every surface already degraded politely (weights check → cached copy notice;
  sync → "offline — using calibrations from last sync"); ticket 10 adds the end-to-end
  test (`test_an_offline_day_still_measures`). The launcher's update skip is ticket 11.

## Launcher and updates (ticket 11, 2026-08-20)

- The dept install is a Git clone; `run.bat` is the updater: `git fetch` + detached
  `checkout REF` (default `origin/main`), `uv sync --frozen` (the committed `uv.lock`,
  exactly; uv never touches a tracked file, so the next checkout can never be refused
  because of it), then `uv run --frozen --offline camtrap-measure`. Every failure
  prints its reason and falls through to the version on disk; a failed dependency
  install restores the previous commit and runs that — offline never blocks a launch.
  `GIT_TERMINAL_PROMPT=0` so a private remote fails instead of hanging on a password
  prompt (the installer stores the credential). cmd reads a running `.bat` by byte
  offset and the checkout rewrites it, so everything after the checkout is one final
  line ending in `exit /b`.
- Resolved in ticket 12: `pyproject.toml` pins PyTorch's cu128 index for
  `sys_platform == 'win32'`, so the one lockfile carries `torch 2.11.0+cu128` for the dept
  machine and PyPI's build for Linux. The launcher syncs `--extra inference` — without
  it `uv sync --frozen` would remove the GPU packages on every start.
- Rollback = an untracked `ref.txt` beside `run.bat` naming a known-good tag (not an
  edit of `run.bat`: a dirty tracked file makes `checkout` refuse). Releases: bump
  `pyproject.toml` version, push main, tag. `/api/health` reports version +
  `git describe --tags --always --dirty` (None outside git) and the header shows them —
  the describe string is the word to put in `ref.txt`.
- The `.bat` cannot run here; its first real execution is the installer's first launch
  (ticket 12), which is the acceptance step for this ticket.
- Weights stay outside the code update entirely (`~/.camtrap-measure/weights/`, manifest).

## Installer (ticket 12, 2026-08-20)

- One pasted PowerShell line fetches `scripts/install.ps1` from GitHub and runs it:
  winget installs Git + uv, clone into `%LOCALAPPDATA%\CamTrapMeasure`, `uv sync --frozen`
  (small), `camtrap-measure --preflight` *before* the multi-GB inference extra, then
  `uv sync --frozen --extra inference` + a torch-sees-GPU check, desktop shortcut to
  `run.bat`, first launch. Re-runnable; `install.bat` in the clone repeats it for repairs.
- The checks live in Python (`preflight.py`, `tests/test_preflight.py`), not in PowerShell,
  so they are tested here: GPU via `nvidia-smi` (missing driver; driver < 570 = too old
  for the cu128 wheels; driver fine but torch blind = reboot; < 8 GB = slow) — all
  warnings, never stops: story 33 says loud warning, and the CPU fallback exists; ≥ 20 GB
  free on the data drive and on the app drive; TCP 443 to github.com / huggingface.co /
  the Supabase host (a plain socket — the read-only guard forbids any HTTP client outside
  the wrapper — hence a warning only: a proxy git/uv went through fools it); WebView2
  runtime (registry); HF token validated with `weights.hub_check` and saved to
  `config.json` (mode 0600 where modes exist; the user profile's ACL on Windows);
  FlagLabel login through the wrapper and saved as the app's session; and the engine's
  own `/api/health` in-process — the "passing first health check". Hard failures: disk,
  WebView2, engine, three rejected credentials. Three attempts per credential; an empty
  token is a soft warning (fake numbers until set).
- Weights download progress: `weights.ensure(progress)` watches bytes on disk against the
  hub's total (`model_info(files_metadata=True)`) while `snapshot_download` runs;
  `/api/status.inference.download` = {done_gb, total_gb}; the page shows a bar.
- Not verified end to end: no Windows machine here. Acceptance = the dept install; the
  README's install section is the script's contract.

## UI design pass (ticket 13, 2026-08-20)

- One stylesheet, `frontend/src/index.css`: colour/spacing/type tokens as CSS custom properties,
  `color-scheme: light dark` + `light-dark()` so dark mode follows the OS with no toggle and no
  JS (WebView2 is evergreen Chromium; both are safe there). Inter Variable (OFL, `frontend/src/fonts/`) is
  bundled by Vite into `ui/assets/` — the page fetches nothing at runtime.
- Components are CSS classes, not React abstractions (the one exception is the three-line `Stat` markup helper): `.card`, `.btn`/`.btn-primary`, `.badge`,
  `.notice{,-warn,-error}`, `.stats`/`.stat`, `.hist`, `.gallery`/`.thumb`/`.bbox`, styled native
  `<progress>`. Layout = sticky top bar (title, version, account) over a single column of cards:
  Cameras (with sync + models line), Measure, Results, Needs a look, Export.
- No behaviour or API change; `App.tsx` keeps its state and fetches verbatim.

## Windows acceptance of tickets 11–13 (2026-08-21, RTX 2060 SUPER 8 GB, driver 581.95, Windows 11)

The installer and launcher ran for the first time on a real Windows machine, as the dept will
run them (`scripts/install.ps1` from a clone; the `irm | iex` form is the same file). Verdicts:

- **Installer (12)**: tool check, clone, `uv sync --frozen`, preflight report (GPU, disk,
  three hosts, WebView2, engine ✓; scripted bad login ✗ with its fix), desktop shortcut,
  first launch — all as designed. Three things broke, all fixed:
  1. `uv sync --frozen --extra inference` failed building `onnx 1.12.0` from source (no cp312
     Windows wheel; needs CMake + Visual Studio + protoc). Cause: `megadetector 10.0.24 →
     ultralytics-yolov5 0.1.1` pins `protobuf<=3.20.1`, the newest onnx tolerating that is
     1.12.0. Fix: `[tool.uv] override-dependencies = ["protobuf>=3.20.2,<7"]` (wandb caps `<7`);
     lock now onnx 1.22.0 / protobuf 6.33.6. Verified at runtime: SpeciesNet converts and
     loads on CUDA. The HPC never noticed because it built onnx from the sdist.
  2. No interpreter pin: a fresh machine gets whatever uv calls newest (3.14 today, 3.13 here).
     `.python-version` = 3.12, the version the HPC tested; uv recreates the venv on its own.
  3. `winget install Git.Git` is a machine-scope install — the dept machines have **no
     administrator rights** (stated 2026-08-21). Git is now a portable MinGit unpacked into
     `%LOCALAPPDATA%\Programs\MinGit`, uv comes from its own user-scope installer, winget is
     not used; `run.bat` puts both on the PATH. MinGit alone serves `git fetch` and uv's git
     dependency (romatch). The preflight's driver and WebView2 fixes now say "ask IT".
- **Launcher (11)**: update (`198547c → b2a4a40`, `run.bat` rewrote itself to CRLF mid-run and
  finished on its last line as designed), offline (`fetch` to an unreachable remote → "Offline
  or no remote", cached sync, app up), rollback (`ref.txt` = a commit → that commit runs, the
  header shows it). `set /p` strips a CRLF from `ref.txt`. `.gitattributes` pins `.bat` to
  CRLF regardless of the clone's autocrlf.
- **Window (13)**: WebView2 window opens; header `v0.1.0 (b2a4a40)`; dark mode followed the
  OS; weights downloaded 6.5 GB in ~3 min. The sign-in card hid the download progress — the
  `ModelsLine` now sits above the card while loading (ticket 14's UI change).
- **Test hygiene**: the suite reached the real hub through a cached developer HF login and,
  with the extra present, loaded real models on the GPU (28 failures, 7 GB pulled into the
  data dir). `conftest` sets `HF_HUB_OFFLINE` and an autouse `hermetic` fixture (own data dir,
  no inference extra); the GPU smoke test opts back in. 154 passed, 1 skipped here.
- **Sign-in with a real mailbox** (window): verified 2026-08-23 after two fixes — the code
  form reused the email form's DOM input, so "Sign in" sent the address as the code
  (`otp_expired` ×3 in the auth log; distinct React keys, 293869d), and Supabase's
  `otp_disabled` for an address with no account reads as "No FlagLabel account uses this
  email" (f4aa268). The preflight's code prompt runs the same wrapper calls; not yet typed
  through by hand.
  The winget-free tool installs were exercised piecewise (MinGit unpack, uv's script) on a
  machine that already had both.
- Dept hardware fact for open item 3: this workstation = RTX 2060 SUPER 8 GB (VRAM floor
  exactly met).

## Email-code login (ticket 14, 2026-08-21)

- FlagLabel accounts sign in with a one-time code that Supabase emails (stated by the
  researcher during the acceptance); password login never applied. The wrapper gained
  `request_code` (`POST /auth/v1/otp`, `create_user: false` so the app can never create an
  account) and `verify_code` (`POST /auth/v1/verify`, `type: "email"`); `sign_in` is gone.
  `tests/test_supabase_ro.py` lists the three auth POSTs as the only non-GETs — the read-only
  guard is unchanged in spirit.
- Engine: `POST /api/login/code {email}` then `POST /api/login {email, code}`; `Offline` is a
  503 with a plain message (it used to be a 500). Window: two-step card with "Use a different
  email". Preflight: three tries at an email that gets a code, then three tries at the code; a
  wrong code never costs a new email (Supabase rate-limits one per 60 s per address).
- 4xx/404/422/429 on the two auth calls are `AuthError` (user-actionable: unknown email, bad or
  expired code, "only request this after N seconds"); `refresh` keeps its narrower rule so a
  429 there cannot sign the user out.

## Pick the flag photo, pick the folder, measure (ticket 15, 2026-08-23)

- The researcher, after the first real session on the dept machine: *no warnings, as simple as
  possible — select the site's flags, select the folder of images, it measures*. Confirmed by
  question: the user picks the flag photo (no automatic date windows), the quality verdict goes
  away entirely, Sync stays a button.
- This overrides tickets 04/05/10's design (EXIF-date validity windows, green/red verdict with
  leave-one-out QC, held photos, post-sync catch-up, folder named after the camera). Reason that
  beats the recorded one: the person operating the app knows which flag photo a folder belongs
  to, and the first sync showed the QC reading real terrain and click scatter as error (section
  above). What the windows protected against — a photo measured against the wrong flag photo
  after a camera was moved — is now the operator's responsibility, stated in the README.
- What remains of calibration QC: a flag photo is unusable only when it cannot be fitted at all
  (not labeled, too few flags, missing from storage, malformed); such photos are listed greyed
  with their reason. `calib/qc.py` (monotonicity, LOO) stays as a research diagnostic.
- `POST /api/run {folder, site, flag, method, rerun}`; `/api/cameras` = each camera's flag photos
  newest first with `ok`/`reason`; run status has `unreadable` (a truncated file is skipped and
  counted, never sinks the batch) instead of `held`/`held_reasons`; `/api/sync` no longer returns
  `remeasure`. A photo without an EXIF date is measured like any other and sits in every date
  range of the reports. The skip rule is unchanged: same method, same flag photo, same annotation
  version; picking another flag photo re-measures and replaces the rows.
- Store keeps the `held_reason` column (always NULL now) — no migration for a column nobody reads.

## Auth

Dept's existing FlagLabel accounts, signed in by one-time email code (ticket 14), session cached. RLS
verified 2026-08-20: `authenticated` role reads all of `annotations`, `sites`,
and the `photos` bucket — no policy changes needed. No service key.

## Trust / review UX (Q1=b, Q11=b)

- Post-run summary screen: counts, distance histogram, per-camera stats.
- Suspicious gallery only (no per-detection review): low RoMa score, low MD
  confidence, unsure species, held photos.
- **Soft export gate**: suspicious rows excluded from CSV by default; one
  explicit checkbox includes them. Silent poisoning impossible; no hard review
  requirement.

## Performance envelope (Q5 — hardware unknown)

Design floor: 8 GB VRAM, FP16, batch size auto-probed at startup. CPU fallback
runs but warns loudly. Models load once and stay resident; JPEG decode
prefetched in workers; incremental writes; runs resumable. "Fast but accurate":
accuracy is never traded silently — speed knob is the MD/SAM3 method choice.

## Offline (Q7=b)

Internet needed only for Sync, update check, first weights download. Each fails
politely (skip update; "offline — using calibrations from last sync <date>").
Measurement is fully local.

## Install (Q8=b)

Self-install is a first-class deliverable: interactive script with preflight
checks (GPU driver/CUDA visible, disk space, network, Supabase login) and
plain-language fixes on failure. No expert in the room.

## Export (Q12=a)

Generic documented CSV, one row per detection:
`photo, camera, timestamp, species, distance_m, q05_m, q95_m, confidence,
method, flag`. Units/columns documented in the export. Distance-package-shaped
export deferred until a real statistician's workflow is observed (needs effort/
region facts the app doesn't have).

## Name

**CamTrap Measure** (Q9=a). Standalone — publishable beside the paper code
without FlagLabel branding.

## Open items (not decisions — work)

1. ~~Ticket zero: EXIF-survival check~~ RESOLVED 2026-08-20: SRF_CAM08/IMG_3792.JPG downloaded from Storage carries full EXIF (DateTimeOriginal 2026-03-13 12:37:33, Browning BTC-7E). Uploads preserve bytes; windows key on EXIF as designed; no captured_at column needed.
2. MD-only vs MD+SAM3 accuracy comparison on existing data → sets default method.
3. Dept hardware facts (GPU model, photo volume) — collect at first install. Acceptance
   workstation (2026-08-21): RTX 2060 SUPER 8 GB; photo volume still unknown.
4. Distance-ready export (Q12b) — after first season with a statistician.
5. First real email-code sign-in on the dept machine (preflight + window) — needs a FlagLabel
   mailbox; everything else of the install was accepted 2026-08-21.

## Supabase is read-only from this app (hard constraint)

CamTrap Measure never writes to Supabase — not annotations, sites, storage, or
anything else. Enforced structurally: a single sync module wraps the Supabase
client and exposes only three read operations (select annotations, select
sites, download storage object); no write method exists to call. A test asserts
the wrapper surface stays read-only and that no other Supabase client is
constructed anywhere in the codebase. DB-level enforcement (RLS) deliberately
untouched: the same user accounts must keep writing via cloud FlagLabel.
