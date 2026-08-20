# 10 — Resume, auto-remeasure, offline polish

**What to build:** Long batches survive real life: a technician cancels a run and later resumes without re-measuring finished photos; photos held for missing calibration are measured automatically after the sync that provides it; and every internet-touching surface degrades politely offline while measurement continues to work.

**Blocked by:** 05 — Measurement run on fake inference.

**Status:** ready-for-agent

- [ ] Cancel mid-run; resume skips already-measured photos
- [ ] App restart mid-run loses at most the in-flight batch
- [ ] After a sync that calibrates held photos, they are measured without being re-requested
- [ ] Offline states covered: launch, sync, weights check — each with a plain notice, none blocking measurement
- [ ] Behaviors asserted through API tests with the fake
