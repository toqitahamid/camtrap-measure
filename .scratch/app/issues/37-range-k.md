# 37 — Range factor k: the weights manifest widens the 90% range

**The problem:** The retrained distance model (Run 2) gives 90% ranges [q05, q95] that are too narrow: they hold the
true distance less often than 90% of the time. The app shows the raw range, so the ranges it would show for Run 2
promise more than they deliver.

**Evidence (research folder 73, `experiments/refnet/73_range_coverage/` in `../distance_estimation`, 2026-10-13):**

- Held-out tape, 644 contacts on 33 cameras (folder 69 markers; test groups MOR + paper12), colour input. *Coverage* =
  share of contacts with q05 ≤ tape ≤ q95.
  - Current app net: coverage 0.932 (camera-bootstrap CI [0.851, 0.993]), median width 4.76 m.
  - Run 1 (Run 2's held-out twin; same recipe, folder-63 split): 0.874 (seed 1) and 0.860 (seed 2), median width
    2.78 and 2.74 m. The drop against the app net is real (paired CI of the difference excludes 0).
  - Run 2 trained on every flag photo, so it has no held-out tape. Its ranges are 17-26% narrower than Run 1's at
    2-15 m on MAS_CAM07, so Run 1's coverage is likely an upper estimate for Run 2.
- Widening each log arm around q50 by one factor k, with k chosen without the test camera (leave-one-camera-out):
  Run 1 seed 1 needs k = 1.308 (the leave-one-camera-out median over 33 folds; `widen_out.txt`), and its coverage
  becomes 0.901 (median width 3.55 m). The in-sample global k, fitted on all 33 cameras, is 1.304. Separate low and
  high factors did not help (0.890).
- Candidate k for Run 2 ≈ 1.6: Run 1's in-sample global k (1.304) times the ratio of Run 1's to Run 2's log-arm width
  on MAS_CAM07 (1.228). One camera, six photos, not held-out. To be firmed fleet-wide (folder 70 rerun with q05/q95 stored) before
  release. Near the camera (0-5 m) coverage stays about 0.83 under any single k.

**User decisions (2026-10-13):**

1. One symmetric *range factor k* widens each range around its median: lo = q50 · (q05/q50)^k,
   hi = q50 · (q95/q50)^k. q50 (the distance) never changes.
2. k travels with the weights: manifest key `"range_k"` (a float). No key → k = 1.0 exactly, so today's weights
   (manifest 2026.08.20c) and every stored answer are unchanged. ADR 0004.
3. An unusable value (not a finite number with 0 < k ≤ 5) falls back to 1.0; no crash.
4. The research log records the k used; nothing new in the window or the CSV.
5. Staff never see k (later on 2026-10-13): nothing about k appears in the window, the status line or `/api/status`.
   An unusable value's problem goes to the research log (`"range_k_problem"` on each measured-photo line) and the
   launcher log only.

**What was built:**

- `distance.py`: `widen(q05, q50, q95, k)` (pure; k = 1.0 returns the inputs untouched; a bool k raises, checked
  before that shortcut; a None or non-finite value passes through; q50 None, non-finite or ≤ 0 changes nothing; an
  arm ≤ 0 is not scaled; order kept: an inverted arm comes back as q50; an arm past the largest float comes back as
  infinity, never an OverflowError) and `range_factor(manifest)` → (k, problem). `RANGE_K = "range_k"`.
  `RANGE_K_MAX = 5.0` caps k: `usable_range_k` accepts only a finite number (not a bool) with 0 < k ≤ 5; a JSON
  integer too large for a float (10**400) is unusable, not an OverflowError.
- `inference.py`: `Real.__init__` reads k once from the loaded manifest (`self.range_k`, `self.range_problem`).
  `Real.__call__` applies `widen` to each read-out (`_read`: the 5×5 nanmedian at the box's ground contact) before it
  becomes a `Detection`: the one place a range is made. `FakeModels(range_k=...)` puts a key in its stand-in manifest.
  `inference.range_k()`: the running k; 1.0 in Test mode and on the fake. `inference.range_problem()`: why the
  manifest's value was not used, or None. `warmup` writes that problem to the launcher log (`main.say`: stderr and
  `logs\launcher.log`), never to the status line.
- `measure.py`: each measured-photo line of the research log gains `"range_k"` next to `weights_version`, and
  `"range_k_problem"` only when the manifest's value was unusable.
  `current_answer` is unchanged: k lives in the manifest, so a new k ships as a new manifest version, which already
  makes every older answer "Out of date" (ticket 36). Its docstring says so.
- `scripts/upload_weights.py`: `RANGE_K` / `--range-k K` writes `"range_k": K` into the staged manifest only when given
  (refused unless finite with 0 < K ≤ 5; `RANGE_K_MAX` there is a copy of the app's). `stage` checks K first, before
  the multi-GB copy and download. `upload --force` under the repo's own VERSION refuses when the repo manifest's
  range_k (missing = 1.0) differs from the staged one: a range factor change needs a new VERSION. VERSION and UNIFIED
  unchanged; the script was not run.

**Where a range is shown, and how each gets k:** every one reads the stored q05_m/q95_m, so all are widened at the
single source above.

- The window: the photo panel's range text and bar (`frontend/src/Measure.tsx`, `ui.tsx`) and the table's range bar
  (`TableView.tsx`), through `report.DET_KEYS`.
- The CSV export (`report.COLUMNS`: q05_m, q95_m).
- The density estimate (`density.py`): each deer's distance is redrawn with sd = (q95 − q05) / 3.29, so a widened range
  also widens the density's 90% confidence interval. The Density tab was removed from the window in aa52dd7;
  `/api/density` and `/api/density.csv` (`api.py` ~:462, ~:495) still exist, so this is reachable only by direct API
  call.
- Not changed: the Compare dialog (alignment score only); `Distance.read` and `Distance.quantiles` return the raw
  range (nothing in the app calls `read`; `quantiles` is the read-out that `Real.__call__` widens).

**Tests:**

- `test_distance.py`: k = 1 returns the very same values (inverted, NaN, None and zero triples too); k = 1.6 on
  (4, 5, 7) gives (3.4988, 5, 8.5659) and multiplies each log arm by 1.6; order kept (inverted arms → q50); NaN, None,
  zero and negative inputs; invalid k raises (0, -1, NaN, infinity, 5.01, 10**400, true, false); a usable k never
  overflows (an arm past the largest float → infinity); an int k = 1 is the same shortcut; `range_factor` with no key,
  1.6, 2, 5 (the cap), and fourteen unusable values (6, 5.000001, ±10**400 among them).
- `test_lineup.py` (FakeModels, end to end): a manifest without `range_k` stores FakeModels' raw numbers exactly; a new
  version with `range_k` 1.6 redoes every answer, stores and exports widened q05/q95 with q50 unchanged, puts nothing
  new in the CSV or the run status, and logs `range_k` 1.0 then 1.6. An unusable `range_k` (-1) measures with the
  raw range, logs 1.0 with the problem under `range_k_problem`, and puts no k text in `/api/run` or `/api/status`.
- `test_inference.py`: an unusable `range_k` is not on the status line nor in `/api/status`; it is in the launcher
  log; the backend still loads, k = 1.0. The fake and Test mode give k = 1.0 and no problem.
- `test_bundle.py`: the staged manifest has `range_k` only when given; VERSION unchanged; 0, -1, NaN, infinity, 5.01,
  6, 10**400 and true refused; the cap equals the app's. A bad `--range-k` stops `stage` before any copy. `--force`
  under the same VERSION refuses a changed range_k (missing = 1.0) and allows an equal one; a new VERSION may carry
  any k. All with stubs; nothing reaches the hub.
- Full suite on the Delta login node (nice 19, one thread, no torch): 516 passed, 11 skipped (main at 3d829a9: 504
  passed, 11 skipped).

**Order of release:** 1. firm Run 2's k fleet-wide (research). 2. merge this branch. 3. stage and upload Run 2 under a
new VERSION with `--range-k <k>`. Merged before step 3, nothing changes: today's manifest has no `range_k`.

**Status:** implemented, not committed (2026-10-13, branch `fix/range-k` from `main` at 3d829a9; the researcher
approves commits). No frontend change, so no bundle rebuild.
