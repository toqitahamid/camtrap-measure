# 19 — The app prints the paper's numbers, not nearly the paper's numbers

**What to build:** The researcher, 2026-08-23, on being told the speed work moved distances by a few
centimetres: *"i want the exact papers result to be pass to the app"*. Ticket 18's performance work had
made three changes that alter the numbers — fp16 instead of bfloat16, RoMa's warp at 672 instead of 864,
half-precision weights on the unified net — and made them the default. That is the wrong default for a
measurement tool, however small the difference.

**Blocked by:** none (amends the performance work committed as `f0bea5e`).

**Status:** done (2026-08-23) — 206 tests green; research fidelity verified on the workstation to run
bf16 autocast over fp32 weights with RoMa at 864/symmetric, reproducing the pre-optimisation distances
to within 2.3 cm (RoMa's own repeat spread is 2.7 cm)

## The rule

**The published pipeline is what runs.** `transport/matchers.py` calls `roma_outdoor(device,
use_custom_corr=False)` — its own defaults, 864 upsample, symmetric — and
`29_testsplit_revision/eval_intervals_rollfix.py` runs the unified net under
`torch.autocast("cuda", dtype=torch.bfloat16)` over the fp32 weights `load_unified` returns. Research
fidelity is exactly that, on every card, including one whose bfloat16 is emulated and slow.

## What is still allowed to change

Only what cannot change a number:

- `kde_chunked` — the same sum, computed a band of rows at a time, verified bit-identical against
  `romatch.utils.kde`. Without it the published settings do not run at all on an 8 GB card: they die
  with `CUDA error: out of memory` before the first photo.
- `empty_cache()` after the SpeciesNet batch probe — memory management, no arithmetic.

Together these took the published settings from 33 s a photo to about 9, with the numbers untouched.

## Fast fidelity

The three number-changing settings live on, off by default, behind `CAMTRAP_FIDELITY=fast` or
`"fidelity": "fast"` in `config.json` — for a computer too small for the published settings, where the
alternative is 33 s a photo. It costs about 6 cm on the photos measured so far.

- **Every measured photo records which fidelity produced it** (`photos.fidelity`), and switching
  fidelity re-measures a folder instead of leaving two kinds of metres side by side — the same rule as
  a relabelled calibration.
- **The export names it per row** (`fidelity` column) and the header says not to mix them silently.
- **The window says so while it is on**: "⚠ fast settings — not the published pipeline", beside the
  status line and beside the progress bar. Research fidelity shows nothing, because it is the norm.

## Not done

The centimetres are measured as *drift between settings*, on 11 photos of one deer at ~8 m from one
camera. That is not the same as measuring *error against ground truth*. **ponytail:** score both
fidelities against the research repo's labelled test split — the same run that settles open item 3
(MD vs MD+SAM3) — before anyone is encouraged to use fast fidelity for real work.
