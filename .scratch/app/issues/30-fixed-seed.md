# 30 — A fixed seed for every line-up

**What to build:** RoMa samples its matches with `torch.multinomial` (romatch/models/matcher.py, `sample`).
Unseeded, the same photo lined up twice in one run gets two different sets of matches and so two different
homographies: a re-run, or Compare after a measurement, can give a different inlier count and a different
distance. MAGSAC is already deterministic on the same matches; the spread is RoMa's draw alone.
`Distance.align` seeds torch (`distance.seed()`, `distance.SEED` = 0, every device) before RoMa matches, inside
`torch.random.fork_rng`, so torch's global random state is the same after a line-up as before it. A module lock
is held from the seed through the homography, because torch's generators are process-wide and Compare and a
measurement can align in two threads. Every RoMa match in the app goes through `align`: a measurement
(`Distance.read`) and Compare (`inference.Real.align_score`).

This is step 1 of the one-fix-at-a-time plan: only the seed, cut from `main` at 4af290e on branch
`fix/fixed-seed`. It is the seeding part of the `feat/night-chain` working tree (ticket 28), without the night
chain, borrowing, hidden feet, new store columns or versions. It settles ticket 08's open choice ("fixed seed,
or matches averaged over draws") for repeatability; averaging over draws would also shrink the draw's error,
which a seed does not.

**Where it is repeatable.** On the same computer, with the same software, device and fidelity. Proven only on
one GH200 within one process (research folder 53). Another GPU (the dept's RTX 2060 SUPER), the CPU fallback or
another torch version may draw different matches from the same seed.

**What it does not do.** Seeding makes a re-run of the same photo reproducible. It does not make two different
photos of a still deer agree when their line-up to the flag photo is weak (a night photo against a day flag
photo): each still gets its own draw, and the draws can land far apart. That needs the night chain (ticket 28),
a later step.

**Stored answers.** No version bump (option a): answers already in the store were measured unseeded and stay; new
measurements are seeded. `measure.current_answer` has no alignment version on `main`, so nothing re-measures. The
alternative (option b) is an `alignment_version` column in `photos`, written by `_job` and compared in
`current_answer`, as ticket 28 does; then every stored answer is measured once more on the next run. At the
app's own estimate of 1.9 s per photo on the dept card (CONTEXT, ticket 27 "Time estimate"), that is about 90 min
for the 2,835 photos of MAS_CAM07_filtered alone. (a) is the default because an old answer is one draw of the
same random line-up the seed now fixes: not wrong, only not repeatable. Choose (b) if a folder must be repeatable
end to end.

**Blocked by:** none.

**Status:** done (2026-10-10), uncommitted, waiting for the researcher's approval. 376 passed, 11 skipped (dev
.venv, no torch or OpenCV; 4 new tests in tests/test_distance.py, 1 of them torch-only and skipped there). GPU:
research folder 53, job 3352633: seeded re-runs identical on 3 MAS_CAM07 photos; unseeded differ by up to 4.81 m
q50 on night photos, 6.2 cm on a day photo. That job ran before review trimmed the seed to torch alone and added
the fork and the lock; neither changes the seed or the draws after it. Found alongside: ticket 31. Notes in
CONTEXT (2026-10-10, ticket 30).
