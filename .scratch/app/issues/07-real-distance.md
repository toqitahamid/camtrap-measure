# 07 — Real distance

**What to build:** Measured animals get real distances: each photo is aligned to its camera's flag reference (RoMa, per-camera reference features cached), the unified network reads horizontal ground distance with a 90% interval at each animal's ground contact, and the alignment score is stored per photo — doubling as the misfile/moved-camera alarm.

**Blocked by:** 06 — Weights and real detection.

**Status:** done (2026-08-20) — GPU smoke passed on DeltaAI GH200 (jobs 2988718/2988726): deer at 6.7 m [4.9, 9.2], 493–509 inliers

- [x] Reference features computed once per calibration and cached
- [x] Distance + q05/q95 per animal from the unified net via aligned reference (deploy path)
- [x] Match score stored per photo; low score marks the photo suspicious (threshold `distance.MIN_INLIERS`; the gallery/export gate that consumes it is ticket 09)
- [x] Inference code ported from the research repo, source commit pinned; paper checkpoint via the weights manifest
- [x] GPU smoke test extended to the full distance path
