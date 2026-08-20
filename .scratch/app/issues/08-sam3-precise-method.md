# 08 — SAM3 precise method

**What to build:** The run screen offers a method choice — fast (detector box) or precise (SAM3 ground-contact mask, slower) — and every result row records which method produced it, so mixed histories stay interpretable.

**Blocked by:** 07 — Real distance.

**Status:** ready-for-agent

- [ ] Method selector on the run screen with plain-language speed/precision hint
- [ ] SAM3 weights via the manifest; loaded only when the precise method is chosen
- [ ] Precise method reads distance at mask ground contact; fast method at box bottom
- [ ] Method recorded on every row; rerun with the other method adds rows, does not replace the first method's
- [ ] Default method set from the research-repo comparison once available (constant, one-line change)
