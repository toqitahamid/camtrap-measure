# 09 — Summary, suspicious gallery, gated export

**What to build:** After a run, a technician sees a one-glance summary (photos, detections, distance histogram, per-camera stats) and a gallery of only the suspicious cases, each stating its reason (poor reference match, low confidence, unsure species, held). Export produces a documented CSV — white-tailed-deer-and-unsure rows by default with a show-all-species toggle — and suspicious rows are excluded unless an explicit checkbox includes them: questionable data never enters the analysis silently.

**Blocked by:** 05 — Measurement run on fake inference.

**Status:** done (2026-08-20) — tests/test_report.py asserts every rule through the API over a scripted backend

- [x] Post-run summary: counts, distance histogram, per-camera stats
- [x] Suspicious gallery with per-case reason; nothing else requires review
- [x] Export dialog: site + date range; deer-default species filter with show-all toggle
- [x] Soft gate: suspicious rows excluded by default, one checkbox includes them, exclusion count shown
- [x] CSV columns and units documented in the export artifact itself
- [x] Gate and filter rules asserted through API tests with the fake
