# 0004. The range factor k travels in the weights manifest, not in the code

Date: 2026-10-13. Status: accepted; implemented 2026-10-13 on branch `fix/range-k`, not committed.

## Context

The app shows each animal's 90% range [q05, q95] exactly as the distance model reads it. The retrained model (Run 2)
gives ranges that are too narrow. On held-out tape (research folder 73: 644 contacts on 33 cameras), the current app
model's range holds the truth 93.2% of the time (median width 4.76 m), but Run 2's held-out twin, Run 1, only 87.4%
(seed 1) and 86.0% (seed 2). Run 2 is narrower still, so its coverage is likely lower.

Widening each log arm around q50 by one factor k fixes this: lo = q50 · (q05/q50)^k, hi = q50 · (q95/q50)^k. The right k
belongs to one set of weights. Run 1 needs k = 1.308 (the leave-one-camera-out median; coverage then 0.901; the in-sample global k is 1.304). Run 2
needs about 1.6 (an estimate from one camera). The current app model needs no widening.

## Decision

Decided 2026-10-13: k is a key of the weights manifest, `"range_k"` (a float), written by
`scripts/upload_weights.py --range-k`. The app reads it once when the models are set up (`inference.Real`) and widens
every read-out with `distance.widen` before the range is stored. With no key, k = 1.0 and the range is the raw one,
bit for bit. k is capped: only a finite number with 0 < k ≤ 5 (`distance.RANGE_K_MAX`) is used. Any other value falls
back to 1.0.

Staff never see k (decided 2026-10-13): nothing about k appears in the window, the status line or
`/api/status`. An unusable value's problem goes to the research log (`"range_k_problem"` on each measured-photo line)
and the launcher log only.

## Consequences

- A k always goes with the weights it was fitted on. A new model with its own k is one upload; no app release is needed.
- The current manifest (2026.08.20c) has no key, so every current answer stays exactly as it is.
- k needs no stale rule of its own. It lives in the manifest, so a new k ships as a new manifest version, and a new
  version already makes every older answer "Out of date" (the public-weights change). Changing k under an unchanged version would
  leave old answers looking current, so `upload_weights.py --force` refuses when the repo's manifest names the same
  version with another range_k (a missing key counts as 1.0).
- Every range shown comes from the stored q05/q95, so the window and the CSV use the widened range. So does the
  density's per-deer distance spread, now reachable only by direct API call (`/api/density`, `/api/density.csv`; the
  Density tab was removed in aa52dd7). The research log records the k used on each measured-photo line.

## Alternatives considered

- *A constant in `distance.py`*: rejected. A model upload would need an app release too, and an app that got the new
  code before the new weights (or the reverse) would widen the wrong model's range.
- *Separate low and high factors*: rejected on the research evidence. Under leave-one-camera-out they gave lower
  coverage than one symmetric k (folder 73: 0.890 against 0.901 for Run 1 seed 1).
- *Equal-tailed factors* (each arm set so it misses at most 5%): rejected on the same evidence; wider and no better
  (folder 73, Run 1 seed 1: coverage 0.885, median width 3.77 m).
