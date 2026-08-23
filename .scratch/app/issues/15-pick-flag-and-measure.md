# 15 — Pick the flag photo, pick the folder, measure

**What to build:** The researcher's verdict after the first real session on the dept machine (2026-08-23): no warnings, no holds — "select the site's flags, select the folder of images, it measures". The Measure card becomes: choose a camera → choose one of its labeled flag photos → type the photo folder → Measure. Every JPEG in the folder is measured against that flag photo. Gone: EXIF-date calibration windows, the green/red verdict and its leave-one-out QC, held photos and the post-sync catch-up, the folder-must-be-named-after-the-camera rule. Sync stays a button (pulls annotations, fits every labeled flag photo). A flag photo is unusable only when it cannot be fitted at all (not labeled, too few flags, missing from storage) — those are listed with their reason, not selectable.

**Blocked by:** 14 — Email-code login.

**Status:** done (2026-08-23) — backend, window and tests switched to the explicit flow; 152 tests green; tsc/oxlint/vite clean; CONTEXT section added

- [x] `calibration.fit` keeps labeled/too-few/missing reasons; no EXIF-date requirement, no LOO rule; `cameras()` lists each site's flag photos (newest first) with `ok`/`reason`, no verdict
- [x] `measure.start(folder, site, flag, method, rerun)`: explicit calibration, no holds; `start_held` and `window_for` removed; skip-if-already-answered still keyed on (method, flag photo, annotation version)
- [x] `/api/run` takes `site` + `flag`; `/api/sync` returns no `remeasure`; `/api/cameras` is the flags listing
- [x] Window: Measure card = camera select → flag photo select → folder → method → Measure; Cameras card = Sync + counts; no held/verdict UI
- [x] Tests rewritten to the explicit flow; CONTEXT records the decision and why it beats tickets 04/05/10's windows
