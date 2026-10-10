# 32 — Project vertical spans 4.8 span lengths down, not 6.8

**What to build:** A vertical span (the 6.35 cm flag cloth) also gives a ground point, `vspan_proj`: the span axis
continued down from its bottom end (`calib/data.py`, `from_annotation`). The app placed that point
(49.53 - 6.35) / 6.35 = 6.8 span lengths below, from the flag's nominal size. Research folder 49
(`../distance_estimation/experiments/refnet/49_projected_ground_check/`) found that the labelled ground contacts lie
4.5-4.8 span lengths below (three measures: 4.59 on 10 flags with both labels, 4.50 on 66 flag-to-ground spans,
4.81 on 2,226 spans read through a calibration fitted without projected points). Folder 52
(`../distance_estimation/experiments/refnet/52_app_ratio_4p8/`) tested ratio 4.8 on the app's full path and it
passed. Its patched loader (`ratio_patch.py`) changed one line, `drop_px = 4.8 * L`; this ticket ships that line.

**Blocked by:** 29 (the roll rule). Both change how a flag photo is fitted. Ticket 29 sets `calibration.VERSION` = 1; this ticket bumps it to 2.

**Status:** implemented, not committed (2026-10-10, branch `fix/roll-rule`, after ticket 29; the researcher approves
commits). Tests not yet run. Details in CONTEXT (2026-10-10, ticket 32).

## Rule

- `calib.data.VSPAN_PROJ_RATIO` = 4.8. `vspan_proj` lies `VSPAN_PROJ_RATIO * L` pixels below the span's bottom end,
  along the span axis (L = span length in pixels). Weight unchanged (0.5).
- The ratio no longer follows `reference_dimensions_cm`; folder 52 used the fixed 4.8 too. The flag body height
  still sets the span's size observation, and `wire_above_ground` the flag-to-ground length.
- The size model (`model_b.FLAG_MID_M` = 0.46 m, from 49.53 cm) is not changed; folder 52 did not change it either.

## Evidence (folder 52, pre-registered, job 3352606)

- Truth: held-out direct ground contacts (`wire_point`, `f2g_end`), which do not depend on the ratio. 120 cross pairs
  (one flag photo measured against the other flag photo of its camera), 905 marker reads, 60 cameras.
- Pooled q50 MAE 0.549 -> 0.426 m, paired camera-bootstrap 95% CI of the difference [-0.156, -0.092]. 90% coverage
  0.982 -> 0.989. Intervals 0.26 m narrower. PASS on all three pre-registered conditions.
- Far (>= 8 m, 210 reads, 48 cameras): 0.825 -> 0.686 m. Paper test cameras (12): 0.613 -> 0.471 m.
- 51 of 60 cameras improve; none gets worse by more than 0.30 m (largest loss MAS_CAM21, +0.101 m).
- Median signed q50 error +0.312 -> +0.065 m: under 6.8 the calibrations read the ground too far.
- The roll decision is the same under 6.8 and 4.8 on all 122 flag photos (120 fit roll under ticket 29's rule).

## Versions

- Every calibration with vertical spans changes (folder 52: roll by a median 0.25 deg, camera height by a median
  0.024 m, pitch by +0.38 deg). This ticket bumps `calibration.VERSION` from 1 (ticket 29) to 2, so a database
  fitted under ticket 29 alone is fitted again once and every answer is measured once more.

## Paper

- The paper (CV4E, frozen) keeps 6.8. The net was trained on 6.8 prompts; a net retrained on 4.8 prompts might gain
  more (folder 52, not tested).

## Tests

`tests/calib/test_data.py`: the projected point lies 4.8 span lengths below the span, along a leaning axis.
`tests/calib/test_roll_identifiability.py`: the synthetic flags stand (4.8 + 1) x 6.35 = 36.8 cm high, so their
spans project onto the true ground under the app's ratio; the pinned old-rule numbers set the ratio back to 6.8 and
the flags to 49.53 cm, the code they were pinned from.
