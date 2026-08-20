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

## Auth

Dept's existing FlagLabel logins (Supabase email auth), session cached. RLS
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
3. Dept hardware facts (GPU model, photo volume) — collect at first install.
4. Distance-ready export (Q12b) — after first season with a statistician.

## Supabase is read-only from this app (hard constraint)

CamTrap Measure never writes to Supabase — not annotations, sites, storage, or
anything else. Enforced structurally: a single sync module wraps the Supabase
client and exposes only three read operations (select annotations, select
sites, download storage object); no write method exists to call. A test asserts
the wrapper surface stays read-only and that no other Supabase client is
constructed anywhere in the codebase. DB-level enforcement (RLS) deliberately
untouched: the same user accounts must keep writing via cloud FlagLabel.
