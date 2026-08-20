# 08 — SAM3 precise method

**What to build:** The run screen offers a method choice — fast (detector box) or precise (SAM3 ground-contact mask, slower) — and every result row records which method produced it, so mixed histories stay interpretable.

**Blocked by:** 07 — Real distance.

**Status:** done (2026-08-20) — GPU smoke on DeltaAI GH200 (jobs 2988962 + 2989015, ~75 s) runs both methods on the MAS_CAM22 deer: md 6.7 m [4.9, 9.2], sam3 6.4 m [4.7, 8.7]

- [x] Method selector on the run screen with plain-language speed/precision hint
- [x] SAM3 weights via the manifest; loaded only when the precise method is chosen
- [x] Precise method reads distance at mask ground contact; fast method at box bottom
- [x] Method recorded on every row; rerun with the other method adds rows, does not replace the first method's
- [ ] Default method set from the research-repo comparison once available (constant, one-line change) — constant in place (`inference.DEFAULT_METHOD = "md"`); the comparison itself is CONTEXT open item 2, still to run
