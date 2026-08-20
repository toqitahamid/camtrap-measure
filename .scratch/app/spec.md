# Spec: CamTrap Measure

Status: ready-for-agent

## Problem Statement

The wildlife department runs white-tailed deer distance-sampling surveys with
trail cameras. They can already label flag photos in cloud FlagLabel, but
turning those labels plus a season of animal photos into per-animal distances
currently requires the researcher to run the research pipeline by hand on an
HPC cluster. The department has a Windows machine with a GPU and no way to use
it: no app fits calibrations from their labels, measures their photos, guards
against bad data, or produces the CSV their abundance analysis needs — without
the researcher in the loop for every batch.

## Solution

CamTrap Measure: a Windows desktop app on the department's GPU machine. It
signs into the existing FlagLabel Supabase with their accounts (read-only),
syncs flag annotations, fits the per-photo ground-plane calibration, and
measures local photo folders: MegaDetector finds animals, SpeciesNet names
them, and the unified distance network — aligned to the flag reference via
RoMa — reads a horizontal distance with a 90% interval for each white-tailed
deer. Results accumulate in a local database with one current answer per
photo; a post-run summary and a suspicious-only gallery guard a soft-gated CSV
export. The app updates itself at launch, tolerates offline operation, and
installs via a guided script with preflight checks — no expert in the room.

## User Stories

1. As a department technician, I want to install the app by running one guided script, so that I don't need the researcher present to set up the machine.
2. As a department technician, I want the installer to check my GPU, disk space, network, and login before finishing, so that failures happen during setup with plain-language fixes, not during my first real run.
3. As a department technician, I want to sign in with my existing FlagLabel account, so that I have no new password to manage.
4. As a department technician, I want my session remembered, so that I sign in rarely, not daily.
5. As a department technician, I want a Sync button that pulls the latest flag annotations, so that new flag surveys become usable calibrations without anyone emailing files.
6. As a department technician, I want sync to fit calibrations automatically and show a green/red verdict per camera, so that I know which cameras are ready without understanding the math.
7. As a department technician, I want a red calibration verdict to name the specific flag photo to relabel and why, so that I can fix it in cloud FlagLabel myself.
8. As a department technician, I want to point the app at a photo folder named after a camera, so that measurement starts with one action and no configuration.
9. As a department technician, I want the app to refuse a folder whose name matches no registered camera, so that typos can't silently produce distances under the wrong geometry.
10. As a department technician, I want photos matched to the right calibration by their timestamps, so that photos taken after a camera was re-flagged use the new geometry and older photos keep the old one.
11. As a department technician, I want photos with no valid calibration held — not measured — with a banner naming which flags to label first, so that wrong numbers never enter the results quietly.
12. As a department technician, I want held photos measured automatically after the next sync provides their calibration, so that I don't track a to-do list myself.
13. As a department technician, I want a progress display with a time estimate during a run, so that I know whether to wait or come back later.
14. As a department technician, I want to cancel a run and later resume without re-measuring finished photos, so that a long batch survives interruptions and shutdowns.
15. As a department technician, I want the app to keep working offline for measurement, so that a dead office connection doesn't stop my work.
16. As a department technician, I want an "offline — using calibrations from last sync <date>" notice instead of an error, so that I know exactly what the app is working from.
17. As a department technician, I want a post-run summary — photo and detection counts, distance histogram, per-camera stats — so that I can sanity-check a batch in one glance.
18. As a department technician, I want a gallery showing only suspicious cases with the reason stated, so that I review dozens of images, not thousands.
19. As a department technician, I want misfiled or moved-camera photos flagged when they don't match the camera's flag reference, so that filing mistakes and camera bumps surface instead of poisoning results.
20. As a department technician, I want suspicious rows excluded from export by default with one explicit checkbox to include them, so that questionable data can never enter the analysis silently.
21. As a department technician, I want the CSV to contain only white-tailed deer (and unsure-deer) rows by default, with a toggle for all species, so that I never hand-filter raccoons in Excel.
22. As a department technician, I want a rerun of the same photos to replace the old results, so that the app always holds exactly one current answer per photo.
23. As a department technician, I want to export a CSV for a chosen site and date range, so that I hand the statistician one clean file per reporting period.
24. As a department statistician, I want one row per detected animal with camera, timestamp, species, distance, and interval bounds, so that distance-sampling analysis needs no photo re-inspection.
25. As a department statistician, I want the exported columns and units documented in the export itself, so that the file is unambiguous without the app open.
26. As a department statistician, I want every distance to carry its 90% interval, so that measurement uncertainty can propagate into the abundance estimate.
27. As a department supervisor, I want the app updated automatically at launch, so that fixes arrive without an IT ticket.
28. As a department supervisor, I want an offline launch to skip the update and run the current version, so that updates never block fieldwork-season deadlines.
29. As the researcher, I want the app to choose between MD-only and MD+SAM3 per run, so that the department can trade speed against precision knowingly.
30. As the researcher, I want the method recorded on every result row, so that mixed-method histories stay interpretable.
31. As the researcher, I want model weights fetched from a versioned private Hugging Face repo via a manifest, so that I ship improved weights without touching the department's machine.
32. As the researcher, I want the app to run within an 8 GB VRAM floor with batch size auto-probed at startup, so that it works on whatever card the department turns out to own.
33. As the researcher, I want a loud warning (not a crash) when no GPU is visible, so that a driver problem is diagnosed in one phone call.
34. As the researcher, I want the app structurally unable to write to Supabase, so that a bug in this app can never corrupt the labeling workflow.
35. As the researcher, I want the RoMa match score stored per photo, so that camera-drift patterns can be studied later from the results database.
36. As a FlagLabel labeler, I want my labeling workflow completely unchanged, so that the measurement app's existence costs me nothing.

## Implementation Decisions

- Architecture: Python engine (uv-managed) exposing a localhost HTTP API; a
  React + TypeScript page (Vite-built, served as static files) as the entire
  UI; a pywebview window as the desktop shell. All logic lives in Python; the
  frontend renders JSON and posts clicks. No router, no state library.
- Three seams (confirmed): (1) the HTTP API is the primary test surface;
  (2) an inference boundary — photos in, detections with distances out —
  isolates all GPU/torch code behind one interface with a fake for tests;
  (3) a read-only Supabase wrapper exposing exactly three operations: select
  annotations, select sites, download storage object. No write method exists;
  a guard test asserts the surface stays read-only and that no other Supabase
  client is constructed.
- Auth: Supabase email auth with existing FlagLabel accounts; session cached.
  RLS verified sufficient (authenticated reads all annotations, sites, photos
  bucket); no policy changes, no service key.
- Calibration: port of the research 4-param ground-plane fit and QC from the
  research repo, consuming schema-v2 annotation JSON from Supabase rows.
  Calibration validity windows keyed on the flag photo's EXIF capture date
  (read from the downloaded storage image at sync). A photo is matched by
  folder-name camera + its own EXIF timestamp to the latest window at or
  before it; no window means held, never guessed. EXIF survival through
  Supabase Storage is ticket zero; fallback is a captured-at column filled at
  upload time by cloud FlagLabel.
- Camera identity: folder name equals the Supabase site string, validated
  against the sites table. Unknown folder names are refused.
- Measurement pipeline: MegaDetector always; SAM3 optional per run as the
  precise-but-slower method; SpeciesNet species per detection; RoMa-aligned
  reference (the deploy path) with per-camera reference features cached; the
  unified net returns distance plus q05/q95 per animal. RoMa match score is
  stored and doubles as the misfile/moved-camera alarm. Default method is
  decided by a planned MD-vs-SAM3 comparison on existing labeled research
  data, not assumed.
- Performance envelope: 8 GB VRAM floor, FP16, batch size auto-probed at
  startup, models loaded once and kept resident, JPEG decode prefetched in
  worker threads, incremental result writes, runs cancelable and resumable.
  CPU fallback runs with a loud warning.
- Results store: local SQLite is the single record (one GPU machine). Key is
  photo + detection + method; a rerun replaces prior rows for what it
  measures. CSV is an export view over the store, never the store.
- Export: generic documented CSV — photo, camera, timestamp, species,
  distance_m, q05_m, q95_m, confidence, method, flag — one row per detection.
  Default filter: white-tailed deer plus deer-family and unsure labels;
  unsure also appears in the suspicious gallery. Soft gate: suspicious rows
  excluded by default, included only via explicit checkbox.
- Suspicious criteria: low RoMa match score, low detector confidence, unsure
  species, and held photos. Thresholds are app constants tuned during
  development, surfaced in the gallery reason text.
- Distribution: auto-update at launch via uv upgrade from the app's Git
  remote inside the launcher script; offline launch skips it. Weights come
  from a private Hugging Face model repo through a versioned manifest checked
  at startup, cached locally, excluded from code updates. Install is a guided
  interactive script with preflight checks (GPU/CUDA visibility, disk space,
  network, Supabase login) and plain-language failure guidance.
- Offline posture: only sync, the update check, and first weights download
  need connectivity; each fails politely. Measurement is fully local.

## Testing Decisions

- Tests exercise external behavior through the HTTP API with the inference
  boundary and Supabase wrapper faked — never implementation internals. A
  test states a user-visible rule (held photos excluded, rerun replaces,
  suspicious rows gated, unknown folder refused) and asserts it end to end
  through the API.
- The calibration fit arrives with its research-repo unit tests; they come
  along in the port. App-level calibration behavior (verdicts, windows,
  holds) is still tested through the API.
- The Supabase wrapper guard test asserts a read-only surface and exactly one
  client construction site.
- The real inference implementation is exercised by a small GPU smoke test
  (marked, skipped where no CUDA), mirroring the research repo's practice of
  guarding GPU tests; it checks wiring, not model quality.
- The frontend gets no test suite; it must build, and it stays dumb enough
  that the API tests cover the behavior. Prior art: the research repo tests
  pure logic and leaves UI glue untested (FlagLabel does the same).

## Out of Scope

- Any change to cloud FlagLabel or the Supabase schema/RLS (one exception:
  the captured-at fallback if ticket zero shows EXIF is stripped).
- Per-detection review/edit workstation (accept/reject each animal).
- Distance-package-shaped export; revisit after a statistician runs a season.
- Multi-machine result sharing; SQLite on the one GPU machine is the record.
- Non-deer survey workflows beyond the show-all-species toggle.
- macOS/Linux packaging; the target is the department's Windows machine.
- Signed installers, SmartScreen remediation, delta updates, staged rollouts.
- Camera-drift *auto-detection* between surveys (RoMa alarm on measured
  photos is in; proactive drift monitoring is not).

## Further Notes

- Ticket zero (EXIF survival on one SRF storage image) gates the calibration-
  window design and should run before any calibration code is written.
- The MD-vs-SAM3 default-method comparison runs in the research repo on
  existing labeled data; the app ships with both methods regardless, so this
  never blocks the build.
- Department hardware facts (GPU model, photo volume) are unknown; collect at
  first install and revisit the performance envelope then.
- The research repo remains the source of model weights and method truth;
  this repo copies the minimal inference/calibration code it needs and pins
  the source commit in comments rather than sharing packages.
