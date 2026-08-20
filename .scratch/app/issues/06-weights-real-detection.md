# 06 — Weights and real detection

**What to build:** First run on a real machine downloads model weights from the private Hugging Face repo via a versioned manifest and caches them; measurement runs now use real MegaDetector for detection and SpeciesNet for species. Models load once and stay resident; batch size is auto-probed at startup; a machine without a visible GPU warns loudly and falls back to CPU.

**Blocked by:** 05 — Measurement run on fake inference.

**Status:** done (2026-08-20) — weights uploaded to `toqi/camtrap-measure-weights`; GPU smoke passed on DeltaAI GH200 (job 2988630)

- [x] Weights manifest checked at startup; missing/updated files downloaded with resume; cached locally; offline uses cache
- [x] Real inference implements the boundary for detection + species (distance still faked/absent)
- [x] Models resident after first load; FP16; batch size auto-probed against available VRAM (8 GB floor)
- [x] No CUDA → loud warning, CPU fallback still works
- [x] GPU smoke test (skipped where no CUDA) checks wiring end to end
