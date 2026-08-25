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

## Check every measured photo, not just the summary (ticket 16, 2026-08-23)

- The researcher, after the first real run, holding the app next to FlagLabel: *"i want a similar or
  better ui, where i can individually verify and check the animal photo that i gave to get the
  measure. not just a summary stat."* The Review card lists every measured photo and shows one at a
  time — the frame with its boxes labelled `species · distance`, each box's 90% interval, detector
  confidence and method, the alignment score, and the flag photo the numbers were read against.
- This overrides Q11=b's *suspicious gallery only, no per-detection review*. Reason that beats the
  recorded one: Q11 was answered before anyone had seen the app's own numbers. A distance in metres
  is not a label a technician can accept on faith — the only way to trust one is to see where the
  box sat and what ground was under it, and the same look is what catches a folder measured against
  the wrong flag photo (which ticket 15 made the operator's responsibility). Showing only the
  suspicious photos hides exactly the cases the thresholds get wrong: a photo the gate passes and a
  human would not.
- Not a review *gate*: nothing must be ticked, no state is written from the Review card. The soft
  export gate stays the only barrier, and the suspicious rows are marked in the review rather than
  being the whole of it.
- `GET /api/photos` (the review) replaces `GET /api/suspicious`; `report.suspicious` is gone since
  `review` subsumes it. `GET /api/photo` gained `size=thumb|full` (320 / 1600 px, day-cached) and
  `GET /api/flag?site=&image=` serves the reference frame from the sync's local copy. Both still
  refuse anything not in the store.
- A photo with no animal is in the list too: *this frame was looked at and held nothing* is part of
  the check, and the empty frames are where a missed deer would hide.

## The window becomes an app (ticket 17, 2026-08-23)

- The researcher on the scrolling page: *"instead of writing the folder dir location, i want to select the
  folder... instead of measuring all image at once, i want to have an option to individually measure each
  image, and have an option to measure all image at once... professional apps are not vertical and take all
  the space of the window."* Design settled on a canvas of nine artboards before any code was written
  (https://claude.ai/code/artifact/c45a02ab-37a5-4d4e-96f1-e2c7f6b5badb): three directions offered, A
  ("field instrument": graphite, one amber accent, three panes) chosen, C's icon rail and data grid folded
  into it, B kept as the record of what was not taken.
- **The shell.** Rail, title bar, context bar, work area, status bar - nothing scrolls but the photo list
  and the table. This replaces the stacked cards of tickets 09-16: one camera, one flag photo, one folder
  and one method live in the context bar and every section acts on them, so the thing being measured is
  always on screen instead of being re-stated per card.
- **Tabs, not a rail.** Both were drawn and both were built. The rail was taken first, on the argument that
  two navigations for the same three sections is one too many. The researcher, on seeing it: *"the measure,
  table, result was at the top bar of the ui as a tab. why did you put them in the left?"* Reason that beats
  the recorded one: they had already read the sections as tabs and looked for them there, and Lightroom —
  the closest thing to this app that any of them has used — puts its modules along the top. The rail went
  with them, because a rail carrying no navigation is 62 px of empty chrome; the app mark and the account
  moved into the title bar. Direction C's data grid, the other half of what the rail came in with, stays.
- **Three sections, not one page.** MEASURE is the photo and its numbers; TABLE is the same photos as
  sortable rows, which is the only place a technician can compare an alignment score or a confidence down a
  column; RESULTS is the survey-level view and the export. The table earns its place by doing two things
  the viewer cannot: tick many photos and measure exactly those, and see a value that is out of line with
  its neighbours.
- **Every row carries its own measure button**, whether or not it has a number. It first appeared only on
  unmeasured photos, which meant a folder that had already been run showed no way to redo one frame — the
  researcher looked for the feature they had asked for and could not find it. A measured row's button says
  "measure again" and carries the refresh mark; an unmeasured one is amber.
- **The folder is picked, never typed.** The path is a label beside a Browse button, per the researcher:
  *"the photo dir location should be slected by browse, dont need the option to type the dir in the app"*.
  The typed field survives in exactly one place — a window with no native dialog behind it (a browser, or
  `--no-window`), which the pick reports and the bar then falls back to. That also disposes of the
  per-keystroke listing: there are no keystrokes.
- **Measure one, some, or all.** `POST /api/run` takes `photos: [...]`; an explicit pick is measured
  whatever it already holds, because picking a photo *is* the intent to measure it. The whole-folder path
  keeps the skip rule of ticket 15 unchanged.
- **`GET /api/folder` replaces `GET /api/photos`.** The window works on a folder, so the listing is every
  JPEG in it joined with the answer held for this flag photo and method - `measured` and `stale` come from
  `measure.current_answer`, the same rule a whole-folder run skips on, so what the list calls stale is
  exactly what a run would redo. `report.review` is gone: it was the same view without the folder.
- **The folder picker.** `dialogs.pick_folder()` opens pywebview's native dialog on the window `main.py`
  built. With no native window (`--no-window`, or the page opened in a browser) it returns a reason instead
  of a path and the field stays typeable - the dev loop on Linux must not need a GUI toolkit, so `webview`
  is imported inside the function, never at module scope.
- **Serving unmeasured photos.** The list shows a thumbnail of every JPEG in the folder, including the ones
  with no answer yet, so `/api/photo` can no longer refuse everything `store.photo_known` does not know. It
  now also serves a JPEG whose resolved parent is exactly a folder `/api/folder` has listed in this
  process. Nothing widens that set but a folder the user pointed the window at.
- **RESULTS keeps its own filter row**, not the context bar. The other two sections measure one folder;
  RESULTS reads the whole store across cameras and dates, and a bar offering a flag photo and a folder
  there would be furniture. The rail is what they share.
- **A listing is a whole-folder scan**, so the typed fallback waits 400 ms after the typing stops before the
  window asks for it. Without that, a 500-photo folder ran a 5-second scan per keystroke and starved the
  rest of the engine (found in review); picking the folder sidesteps it entirely.
- **An answer stored under the other method reads as unmeasured.** The method sits in the context bar and
  changes with one click; claiming a photo was looked at under a method it was never run with made the
  window say "no animal" about a photo nobody had measured (found in review).
- Built by four agents in parallel against the contract above - engine, and one file per section - with the
  shared types, the stylesheet and the shell written first so the seams were fixed before anyone started.

## The GPU is shared with the desktop (2026-08-23)

- Measured on the dept machine while testing ticket 17: **7.7 of the card's 8 GB was in use** by Chrome,
  Teams, Cursor, WebView2, the shell and the lock screen, before this app asked for anything. A run died
  with `CUDA error: out of memory` after 53 s. This is the normal state of a consumer card in WDDM mode,
  not a leak - stopping the engine took the card back to ~1 GB.
- Three answers, none of them "buy a bigger card":
  1. **Closing the window ends the process** (`main.shutdown`). The driver hands the CUDA context back
     only when the process really dies, and a hung CUDA teardown or a daemon thread mid-run could keep it
     alive; the launcher stops the run, gives the photo in flight two seconds to write its row, then
     leaves hard. Safe because the store commits and closes per photo - the worst case is the photo in
     flight, which is exactly what a cancel already costs.
  2. **The startup warning reads free memory, not total.** `torch.cuda.mem_get_info()`; below three
     quarters of the floor it names what is free and says which windows to close. The old check only saw
     the card's size, which on this machine was never the problem.
  3. **An out-of-memory failure gets plain words**, not the driver's: "close Chrome, Teams or other heavy
     windows, then measure again. The photos already done keep their numbers." `inference.is_oom` was
     already there for SpeciesNet's batch back-off; `measure` now reads it too.
- Not done: shrinking the batch or the RoMa resolution when memory is short. The back-off already exists
  for SpeciesNet and did not fire here - the failure was in alignment, which allocates once and large.
  Revisit if the dept meets this on an idle machine rather than one running Teams.

## Auth

Dept's existing FlagLabel accounts, signed in by one-time email code (ticket 14), session cached. RLS
verified 2026-08-20: `authenticated` role reads all of `annotations`, `sites`,
and the `photos` bucket — no policy changes needed. No service key.

## Trust / review UX (Q1=b, Q11=b)

- Post-run summary screen: counts, distance histogram, per-camera stats.
- Photo-by-photo review of every measured photo, boxes and numbers on the frame
  (ticket 16 overrides Q11=b's suspicious-only gallery — see its section above);
  suspicious rows are marked there: low RoMa score, low MD confidence, unsure species.
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

## 2026-08-23 - It installs and starts like an app (ticket 18)

The researcher, on the shortcut we shipped: *"why does everytime i click the desktop shortcut button it
opens a command prompt? why not make the app professional"*. One cause, three faults deep: a `.lnk` whose
target is a `.bat` is run by `cmd.exe`, a console program, so Windows must give it a console; `run.bat`
then ran the app in that console's foreground, so the black window stayed for the whole session and
closing it killed the run; and `camtrap-measure.exe` was a `[project.scripts]` console executable of its
own.

**The shortcut runs `wscript.exe scripts\launch.vbs`.** wscript is not a console program, so nothing is
opened. `powershell -WindowStyle Hidden` was the obvious alternative and was rejected: it still flashes a
black window on the way up, which is exactly the complaint. The .vbs is four lines and does one thing.

**The update moved out of `run.bat` into `scripts\launcher.ps1`.** Not a rewrite for its own sake: the
launcher must now show a splash and report a failure in a dialog, and cmd can do neither. It also settles
an old fragility - the checkout rewrites the launcher while it runs, and cmd re-reads a `.bat` by byte
offset, which is why everything after the checkout had to sit on one last line. PowerShell parses a
script whole before executing it. Every promise of ticket 11 is carried over and asserted in
`tests/test_launcher.py`: `ref.txt`, the offline fallback, the rollback to the previous commit and its
offline sync. `run.bat` stays as the console way in (`-Console`), one command long.

Two rules learned in the writing. `Start-Process -PassThru` hands back a **null** ExitCode unless the
process object's `.Handle` is touched while it lives - untouched, every step reads as a failure and the
launcher would "go offline" on a working network (seen). And `-NoNewWindow` is what stops Windows giving
a child process a console of its own when the parent has none.

**A GUI entry point.** `[project.gui-scripts] camtrap-measure-app` builds a pythonw executable (PE
subsystem 2, checked), so the app itself can never own a console. `camtrap-measure` stays for the
terminal and for `--preflight`.

**An icon, drawn from the mark the window already uses** (`scripts/make_icon.py` writes
`src/camtrap_measure/assets/camtrap-measure.ico`, inside the package so it travels with an install).
Below 32 px the four ticks blur into the brackets, so the small sizes are drawn without them. The window
wears it through `win_icon.py`: a pywebview window is Python's until `WM_SETICON` says otherwise, and
`SetCurrentProcessExplicitAppUserModelID` is what the taskbar groups a pinned button by. Both are
cosmetic and best-effort - and both say why in plain words rather than failing silently, into the
launcher's log.

**One app at a time.** The launcher looks for a window titled "CamTrap Measure" and brings it forward
instead of starting a second engine; two engines would fight over an 8 GB card.

**The installer got a window** - steps, a progress bar, a details pane streaming what each command
prints, and a dialog on failure - plus a Start-menu shortcut, a per-user Settings > Apps entry (HKCU, no
administrator) and `scripts/uninstall.ps1` behind its UninstallString. The uninstaller asks twice: once
about the app, once about `~/.camtrap-measure`, which holds the measurements and ~7 GB of weights and is
kept unless it is asked for by name. It copies itself into TEMP first, because it deletes the folder it
lives in.

A real installer package (Inno Setup, MSI) was considered and left alone: building one needs a compiler
on the build machine and an administrator to install that, the dept machines have neither, and the
payload is a Git clone plus a multi-GB download that no installer package would carry anyway.

## 2026-08-23 - Three faults in the window (same day)

Reported from the running app: the camera list opened white-on-white, the chevron beside it did nothing,
and RESULTS showed the last run's numbers before any folder had been chosen.

A `<select>`'s dropdown is painted by the browser and takes its colours from the select element itself;
ours is transparent, so the list landed on the light default while inheriting our light text. `select`
now declares `color-scheme: dark` and the options carry their own colours. The chevron sat *beside* the
select in the flex row, so a click on it hit the label: it is now positioned over the select's right end
with `pointer-events: none`. The focus ring went amber with it - the browser's blue belonged to no
palette here.

RESULTS answers for the folder in the bar now: `/api/summary` and `/api/export.csv` take a `folder`, and
"Everything measured" is a deliberate choice in the filter row rather than the default. Photos directly
inside the folder count and nothing below it, because a run only ever reads one folder's JPEGs.

### The checks stopped asking (same day, running the new installer)

The first real run of the windowed installer failed on the preflight step: `preflight.run` asked for the
Hugging Face token with `input()`, the window has no console, and the answer was an `EOFError` traceback
in the details pane before a single check had been read. `run(prompt=...)` now decides whether anything
may be asked - by default from `sys.stdin.isatty()`, and forced off by `camtrap-measure --preflight
--no-prompt`, which is what the installer runs. With nothing to ask, it reports what is stored: the token
from `HF_TOKEN` or `config.json`, and whether this computer has a FlagLabel session. Neither absence is a
hard failure any more, because neither has to be settled at install time - the window signs in by emailed
code (ticket 14) and the token can be dropped into `config.json` later.

The installer keeps the one question only a person can answer: a masked box for the token, asked only
when none is stored, handed to the checks through `HF_TOKEN` so it is written where the app reads it. The
FlagLabel sign-in was dropped from the installer altogether - it belongs to the window.

### What the first real double-click found (2026-08-23, workstation)

Four faults, all in the new plumbing, all fixed and each now nailed down in `tests/test_launcher.py`:

1. The **splash carried the app's own window title**, so it answered the question "is the app already
   running?" and `win_icon` would have dressed it instead of the window. It is "Starting CamTrap
   Measure" now.
2. The launcher waited on `MainWindowHandle` of the process it started, **which never gets one**: the
   generated entry point re-runs itself as `pythonw`, so the window belongs to a child.
3. `**$null` is marshalled by PowerShell as an empty string**, so `FindWindowW($null, $Title)` searched
   for a window of class `""` and matched nothing - the single-instance check never fired and a second
   engine started beside the first, both holding the GPU. `[NullString]::Value` is a real NULL. The
   check now asks about the *process* anyway: for the first minute the models are loading and there is
   no window to find.
4. `.gitignore` **takes no trailing comments**: `logs/  # note` ignored nothing, every install then had
   an untracked `logs/`, and the launcher reads a clone with local changes as a developer's tree and
   stops updating it - for ever.

Accepted on the workstation: cold start from the desktop icon with no console at any point, a second
double-click bringing the running window forward instead of starting a second engine, the window closing
and its process going with it, and the installer's own window writing the shortcut, the Start-menu entry
and the Settings > Apps registration.


## Making a run fast, and proving the GPU is doing it (2026-08-23)

A folder of 11 real photos took **364 s — 33 s a photo**. The same folder now takes 34 s: **3.1 s a
photo, 1.65 s once warm**, about 1150 photos an hour instead of 109. Nothing about the method changed:
the metres move by less than the method already moves between repeat runs of identical settings.

The measurements are reproducible with `uv run python scripts/profile_run.py <folder> --site <camera>
--flag <photo>`, which times every stage with the GPU drained on both sides (CUDA is asynchronous, so
an unsynchronised timer bills the next stage for this one's work), records the peak VRAM each stage
adds, and samples `nvidia-smi` while the run happens.

### What was actually wrong

The card was never the problem. **The app did not fit in it**, and Windows hides that: when a CUDA
allocation does not fit in VRAM the driver serves it from system memory over PCIe instead of failing,
so the app keeps working and simply crawls. The same run, unchanged, took 3.6 s a photo one minute and
26 s the next depending on what Chrome had taken - a lottery, not a benchmark. Four causes, in the
order they cost:

1. **RoMa's `kde` builds the whole match-density matrix at once.** With its own defaults that is
   40000 x 40000 in half precision - 3.2 GB, and the expression materialises it several times over.
   This was not slow, it was fatal: on an 8 GB card the run died before the first photo with
   `CUDA error: out of memory` inside `romatch/utils/kde.py`. `distance.kde_chunked` computes the same
   sum a band of rows at a time and returns **bit-identical** results (`tests/test_performance.py`), so
   the sampling that follows, and the published `MIN_INLIERS` gate, still mean what the research
   measured.
2. **bfloat16 was being used on a card that only emulates it.** `torch.cuda.is_bf16_supported()`
   answers True on Turing, where bf16 is emulated: the same convolutions took **122 ms in bf16, 44 ms
   in fp32, 25 ms in fp16**. The unified net now asks `native_bf16()`, which passes
   `including_emulation=False`. SAM3 keeps the behaviour its comment already described - a card without
   real bf16 runs it in fp32, slower but right.
3. **RoMa's 864 x 864 refinement does not fit on an 8 GB card.** At 864 a photo needs 6.3 GB, more than
   Windows leaves free with a browser open; at 672 it needs 4.4 GB and fits. `Distance._upsample_res`
   chooses by the card's *total* memory, never by what happens to be free, so a given computer always
   produces the same numbers; a card of 10 GB or more keeps RoMa's default, which is what the research
   ran.
4. **The SpeciesNet batch probe kept its largest trial.** 2.9 GB held in the allocator's cache, unused,
   which is roughly the headroom the run then lacked. `empty_cache()` after the probe gives it back.

Distances at each step, same five photos, against the previous setting: **2-8 cm**. RoMa samples its
matches at random, and repeating one setting unchanged moves them **3-17 cm**; the app's own reported
90% band on these photos is about **±3 m**. The change is far inside the noise it is measured against.

Deliberately not changed: `symmetric=False` halves RoMa's encoder work and was 1.7x faster again, but
it tripled the run-to-run spread (2.7 cm to 16.6 cm). Speed bought with reproducibility is the wrong
trade for a measurement tool. **ponytail:** both this and the 672 warp should be checked against the
research repo's labeled data when open item 3 (MD vs MD+SAM3) is run - the same evaluation answers both.

### Where the time goes now

Per photo, warm, on the dept card: **RoMa alignment 1.3 s (68%)**, MegaDetector ~0.27 s, SpeciesNet
~0.11 s, unified net **0.079 s** (it was 15.8 s). GPU utilisation averaged 38% during the run, so the
GPU is no longer the limit - the next real gain is RoMa, whose reference photo is the same for every
photo of a run and is re-encoded every time. That is invasive (it means reaching inside `romatch`), so
it waits for a folder big enough to justify it.

### "Is it really using the GPU?"

It has to be answerable from the app's own window, not from a terminal. The status line now reads
`MegaDetector + SpeciesNet 2026.08.20c · NVIDIA GeForce RTX 2060 SUPER (8.0 GB) · float16 · batch 32`,
from `torch.cuda.get_device_properties`, and says `CPU only — no GPU in use` when there is no card. The
shared-card warning is calibrated to what a run now needs (`RUN_VRAM_GB = 4.5`) instead of a guess, and
says what actually happens - several times slower, not "may fail".

### Correction: the published pipeline is the default (2026-08-23, ticket 19)

The section above made three number-changing settings the default. That was the wrong call and is
reversed. The researcher's instruction on being shown the drift: *"i want the exact papers result to be
pass to the app"* — and it beats the reason recorded above, which was speed. A distance tool whose
numbers are *nearly* the published pipeline's is worth less than a slow one whose numbers are exactly
them; the app's whole claim is that it runs the paper's method.

**Research fidelity is now the default and reproduces the published pipeline exactly**: bfloat16
autocast over fp32 weights (`29_testsplit_revision/eval_intervals_rollfix.py`), RoMa at
`roma_outdoor`'s own defaults, 864 and symmetric (`transport/matchers.py`). On a card whose bfloat16 is
emulated it takes the emulation and the cost. Verified on the workstation: same settings, and distances
within **2.3 cm** of what the app produced before any of this work — RoMa's own spread between repeats
of one setting is 2.7 cm.

**The two fixes that cannot change a number stay, and they are most of the win**: `kde_chunked` (bit-
identical, and without it the published settings do not run at all on 8 GB — they die with
`CUDA error: out of memory` before the first photo) and `empty_cache()` after the batch probe. The
published settings went from **33 s a photo to about 9**, with the numbers untouched. The rest of the
speedup, down to ~2 s, is what fast fidelity buys, and it is now opt-in:
`CAMTRAP_FIDELITY=fast` or `"fidelity": "fast"` in `config.json`.

Fast fidelity is never silent. `photos.fidelity` records which settings produced every measured photo,
switching fidelity re-measures a folder rather than mixing two kinds of metres, the CSV carries a
`fidelity` column with a header line saying not to mix them, and the window shows
"⚠ fast settings — not the published pipeline" for as long as it is on.

What is still **not** established: the drift between fidelities is not the same as error against ground
truth, and it was measured on 11 photos of one deer at ~8 m from one camera. Both fidelities should be
scored against the research repo's labelled test split before fast is recommended for real work — the
same run that settles the MD vs MD+SAM3 open item.

## Models load in stages and the card is handed back (2026-08-23, ticket 20)

The five models never had to be resident together, and on an 8 GB card shared with a Windows desktop
that was costing exactly the headroom that decides whether a run executes on the GPU or out of system
memory. A run now happens in two stages, and holds nothing between runs.

**Stage one** is MegaDetector and SpeciesNet — which photos hold an animal, and what it is. They then
leave the card. **Stage two** is RoMa and the unified net, over only the photos stage one found
something in. Measured: peak allocation during the measuring stage is **6.26 GB with the detector
released against 6.99 GB with it resident**. **A folder with no animals never loads stage two at all** —
not "skips the alignment" as before, the weights are never read off disk, which on a real card-dump is
the common case.

**Nothing loads until a run needs it, and everything goes when the run ends.** The window opens without
waiting for 6 GB of weights, and an idle app holds no VRAM: verified on the workstation at 473 MiB idle
(the desktop's own), 1.4–3.3 GB while finding animals, up to 7.8 GB while measuring, and back to
559 MiB the moment the run finished. 11 photos in 92 s against 117 s before.

The cost, and it is a real one: each run reloads what it needs — MegaDetector 14.4 s, SpeciesNet 3.1 s,
RoMa + DINOv2 9.5 s, the unified net ~6.6 s warm — so roughly 20–35 s before a run measures anything,
where before it was paid once at startup. For a folder off an SD card that is nothing; for someone
re-measuring one photo repeatedly it is the worse deal. That is the trade the request asked for, and it
is the right one for a machine whose card is also running the desktop. Unloading itself is free (~80 ms,
reclaiming ~2.8 GB).

Two consequences worth knowing. **Results now name their photo**: the stages finish photos out of order,
so `PhotoResult` carries its `path` and the store files each answer by it — zipping results against the
photo list, as the code did before, would now file every number under the wrong photo. And **the run
says which stage it is in**, because "finding animals 240/400" and "measuring distances 3/12" are very
different waits and an unlabelled first pass looks like a hang.

### Measured and deliberately not taken: RoMa's own empty_cache

`romatch/models/matcher.py` calls `torch.cuda.empty_cache()` once per photo inside `match()`, before the
upsample pass. It cannot change a number. Removing it measured **~11–13% faster** (4.13 / 4.23 s per
photo with it against 3.72 / 3.75 without, two alternated repeats of four photos), about half of which
is the call itself at ~0.22 s per photo.

Left in place. The measurement was taken with the card fully saturated — `mem_get_info` reported exactly
zero free bytes on every run — which is the regime RoMa put that call there to survive, and it is also
the regime the app's own notes call a lottery. Eleven percent is not worth an out-of-memory on the
tightest machine in the department. **ponytail:** revisit on a card with headroom, or once stage two's
peak fits inside what Windows leaves free.

## The models ship with the installer; nobody gets a token (2026-08-24, ticket 21)

The weights live in a private Hugging Face repo and the only way to download them is a read token.
Handing that token to a dozen people hands out a credential that cannot be taken back from any one of
them, and that then lives on in a dozen `config.json` files. So the department is given the **models**
instead of the means to fetch them: `scripts/make_bundle.ps1` builds a ~6.5 GB folder holding the
installer and the weights, the installer copies them in, and no team machine ever has a token.

The app itself still comes from GitHub at install time — that repo is public (checked 2026-08-24; the
HANDOFF note calling it private is stale) — so a team machine needs the internet but no credentials.
Chosen over a fully offline bundle, which would also have to carry the 5.4 GB CUDA environment and a
seeded uv cache: half the size, and far less new machinery to fail on a machine nobody can reach.

**The quiet failure this avoids.** A machine with no token that asks the private repo anyway gets a
401, which the code reports as "the weights repo rejected the access token — check hf_token in
config.json". On a bundled machine that warning would be permanent, wrong, and on screen for ever. The
installer therefore writes `"weights_from": "bundle"` into `config.json` and `weights.ensure` skips the
hub when it sees it — **said, never guessed**. Inferring it from the absence of a token also silences a
developer machine, which has no token either but reaches the hub through a cached `huggingface-cli`
login and must go on seeing new weights versions. The existing tests caught exactly that.

Deliberately not zipped: PowerShell 5.1's `Compress-Archive` fails above 2 GB and the folder is over 6,
and model weights are already compressed — a zip would spend twenty minutes saving nothing and then
break at the end. The folder is copied as it is.

**Not established:** nobody has run the bundled install on a machine that did not already have Git, uv
and the weights. The builder is verified end to end and the app-side logic is unit-tested, but the
6.5 GB copy, the skipped token box and the first start with `weights_from` set have never happened on a
cold machine. That is the next real test, and it is the same second-machine run the installer has been
waiting for since ticket 18.

## The flag photo of the camera you are looking at, and clearing a measurement (2026-08-25, ticket 22)

**The fault.** The window shows the flag photo a number was read against. It built that request out of
two different sources — the camera from the dropdown, the flag photo's name from the displayed photo's
own record — which agree only while the selected camera happens to be the one that measured it. Choose
another camera and the window asked for one camera's flag under another camera's name. Reproduced before
touching anything: `site=MAS_CAM01&image=IMG_2868.JPG` → 200, `site=MAS_CAM02&image=IMG_2868.JPG` → 404.
The engine is right to refuse it; an `<img>` whose request 404s simply renders nothing, so the fault
arrived as silence rather than as an error.

The listing had no way to fix it: `report.folder` reported `flag_image` and never which camera it
belonged to. **`flag_site` now travels beside it** and the window asks for the pair that was actually
measured, whatever the dropdown says. The panel's *Camera* row had the same bug one line down — it read
the dropdown, so a measured photo could be labelled with a camera that had nothing to do with it.

**Clearing.** A re-measure could replace an answer but nothing could take one away, so a wrong flag
photo or a folder measured under the wrong camera left numbers on record with no remedy but editing the
database by hand. `store.clear_measurements(site=... | path=...)` removes the photo rows and their
detections and reports what went.

Only the app's own answers go. The photos on disk are untouched, and so is everything synced from
FlagLabel — cameras, annotations, calibrations, cached flag photos — because they are not this app's to
delete and re-measuring needs every one of them. There is a test for exactly that, because it is the
kind of promise a later refactor breaks quietly.

Refusing is part of the feature: **neither argument** is a 400 rather than "everything" (that would empty
the store, which no button asks for and nobody means by "clear this camera"), both together is a 400,
and **a run in progress** is a 409 — deleting rows a running job is still writing is a race with the
store as the loser. Clearing a camera that has nothing measured answers 0 and is not an error.

In the window: one button under *Measure … again* for a single photo, one at the foot of the Export card
for a whole camera. Both ask twice rather than opening a modal — the window has no dialog of its own and
a browser `confirm()` blocks the whole WebView until answered. The camera button clears the **camera**,
never the filters above it: a date range or a species tick is a way of looking, not a way of choosing
what to delete, and a button that quietly meant "the 43 rows currently on screen" would be the wrong
button.
