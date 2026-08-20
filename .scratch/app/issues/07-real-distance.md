# 07 — Real distance

**What to build:** Measured animals get real distances: each photo is aligned to its camera's flag reference (RoMa, per-camera reference features cached), the unified network reads horizontal ground distance with a 90% interval at each animal's ground contact, and the alignment score is stored per photo — doubling as the misfile/moved-camera alarm.

**Blocked by:** 06 — Weights and real detection.

**Status:** ready-for-agent

- [ ] Reference features computed once per calibration and cached
- [ ] Distance + q05/q95 per animal from the unified net via aligned reference (deploy path)
- [ ] Match score stored per photo; low score marks the photo suspicious
- [ ] Inference code ported from the research repo, source commit pinned; paper checkpoint via the weights manifest
- [ ] GPU smoke test extended to the full distance path
