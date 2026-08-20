# 04 — Calibration fit, windows, verdicts

**What to build:** After Sync, every camera shows a green/red calibration verdict. The app fits the 4-parameter ground-plane calibration per flag photo from the synced annotations, reads each flag photo's EXIF capture date from storage to open a validity window, and explains any red verdict in plain language naming the photo to relabel in cloud FlagLabel.

**Blocked by:** 01 — EXIF survival check; 03 — Read-only sync and login.

**Status:** done (2026-08-20)

- [x] Calibration fit and QC ported from the research repo with their unit tests, source commit pinned
- [x] Fit runs automatically as part of Sync for new/changed annotations
- [x] Validity window per calibration keyed on flag photo EXIF capture date
- [x] Per-camera green/red verdict in the UI; red states the reason and the photo to fix
- [x] Cameras list shows calibration date and window for each camera
- [x] All behavior tested through the API with a faked Supabase wrapper
