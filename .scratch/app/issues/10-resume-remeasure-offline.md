# 10 — Resume, auto-remeasure, offline polish

**What to build:** Long batches survive real life: a technician cancels a run and later resumes without re-measuring finished photos; photos held for missing calibration are measured automatically after the sync that provides it; and every internet-touching surface degrades politely offline while measurement continues to work.

**Blocked by:** 05 — Measurement run on fake inference.

**Status:** done (2026-08-20) — no separate resume: Measure skips photos with a current answer; sync re-tries held photos

- [x] Cancel mid-run; resume skips already-measured photos
- [x] App restart mid-run loses at most the in-flight batch (results are written per photo: at most the photo in flight)
- [x] After a sync that calibrates held photos, they are measured without being re-requested
- [x] Offline states covered: launch, sync, weights check — each with a plain notice, none blocking measurement (weights check + sync + a run asserted end to end; the launcher's own update skip is ticket 11)
- [x] Behaviors asserted through API tests with the fake
