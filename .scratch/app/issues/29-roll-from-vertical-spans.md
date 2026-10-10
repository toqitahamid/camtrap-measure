# 29 — Fit camera roll when vertical spans cover two transects

**What to build:** The flag-photo fit holds camera roll at 0 when direct ground marks (`wire_point`, `f2g_end`)
cover at most one transect (the rollfix rule of research folder 30). Vertical spans also give ground points
(`vspan_proj`), often on every transect. Research folder 47
(`../distance_estimation/experiments/refnet/47_app_roll_rule/`) tested a relaxed rule on held-out flag markers
and it passed. The researcher approved it for the app on 2026-10-10.

**Blocked by:** none. Step 2 of the one-fix-at-a-time plan: first built on the uncommitted `feat/night-chain` tree
(after ticket 28), then ported alone to branch `fix/roll-rule`, cut from `main` at 87b49a8 (after ticket 30).

**Status:** implemented, not committed (2026-10-10, branch `fix/roll-rule`; the researcher approves commits). On
`feat/night-chain`: 406 passed, 10 skipped, and the app's fit equals folder 47's `roll_rule.fit(photo, "new")` model
dict exactly on all 122 flag photos of `flaglabel-dataset/`. On `fix/roll-rule`: tests not yet run. Details in
CONTEXT (2026-10-10, ticket 29).

## Rule

- Fit roll iff the old rule fits it (>= 2 transects with a direct ground mark), or >= 2 transects each carry
  >= 2 ground marks of any source (`wire_point`, `f2g_end`, `vspan_proj`) at >= 2 distinct distances.
  Otherwise roll = 0. Same bounds as before (roll in [-0.4, 0.4] rad). It only relaxes the old rule.
- Code: `calib/model_b.py` `roll_identifiable(ground)`, used by `ModelB.fit`.

## Evidence (folder 47)

- Changes exactly 10 of 122 flag photos (one per camera): MAS_CAM07, 08, 10, 17; TON_CAM12, 18, 19, 23, 25, 29.
- Held-out cross-pair markers: pooled q50 MAE 1.386 -> 0.811 m, paired camera-bootstrap 95% CI of the
  difference [-0.950, -0.252]. No camera got worse.

## Versions

- `calibration.VERSION` = 1 (before: None). Stored in `calibrations.fit_version` and `photos.fit_version`.
- A calibration fitted under another version is fitted again at the next sync (`store.calibration_versions`).
- An answer is current only under its calibration's `fit_version` (`measure.current_answer`), so every stored
  answer is measured once more after the first sync (one full run, about 1.9 s per photo on the dept card). The
  112 unchanged flag photos give the same model, so their answers come back the same; only the 10 changed cameras
  get new numbers.
- `distance.Distance.reference` keys on the fit version too. (On `feat/night-chain`, `lineup.request` does as well;
  `lineup.py` is not on this branch.)

## Paper

- The paper (CV4E, frozen) keeps the old rule. The app no longer reproduces the paper's numbers for the 10
  cameras, which include the test cameras MAS_CAM17 (IMG_2712) and TON_CAM19 (IMG_6156).

## Tests

`tests/calib/test_roll_identifiability.py`: a synthetic annotation with known roll 0.10 rad, wire points on C
only and vertical spans on L, C and R, recovers the roll within 1e-3 rad; spans on one transect hold roll at 0;
a second transect needs two distances; two direct transects fit exactly as the code before (pinned numbers).
`tests/test_measure.py`: a fit under older rules is fitted again at sync and its photos are measured again once.
