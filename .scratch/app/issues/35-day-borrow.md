# 35 — Day borrow: a weak day photo borrows a day photo's line-up

**The problem:** A day photo always lined up directly with the flag photo. A frame-filling animal hides the
background, so the photo's own line-up breaks with no warning. All 8 verified weak frame-filling day photos
(86-2,339 points) had broken homographies (shift 400-5,300 px, against 20-120 px for strong neighbours). TON_CAM04
IMG_0982 / IMG_0981 read 9.30 / 10.48 m while their burst mates read 11.18-11.40 m.

**Evidence (read-only check, 2026-10-12):** 1,087 day animal photos, median 8,211 points, 3.5% under 4,000. At a
box share of 50% or more (n = 43), 14% under 4,000. 99.3% of frame-filling day photos have a clearer photo within
120 s. Small animals at dawn or dusk with 1,122-4,000 points were usually right (within about 30 px of strong
neighbours). A wrong camera gives 54-276 points, and its neighbours fail too.

**User decisions (2026-10-12):**

1. Trigger: the direct line-up is kept only with a homography and at least 4,000 points (`DAY_WEAK` = `DAY_MIN`).
2. The day rule uses the Night rule's search (`find_day`) for A and B. Both found: B onto A within 20 px with 1,000
   points or more: Copy the nearer; otherwise Fallback (copy the nearer, log `moved`). One side: copy it. No Chain
   and no vote by day ("no chain").
3. No neighbour: keep the own line-up from 2,500 points with a homography (log that it was kept); otherwise no
   distance, with a reason in the researcher log only.
4. No frontend change. 5. The CSV export unchanged. 6. No GPU validation now ("not needed now"); unit tests only.

**What was built:**

- `lineup.py`: `DAY_WEAK`, `DAY_KEEP` (2,500), source `DAY_BORROW` ("day_borrow"), path `OWN`. `Planner.day_rule`
  replaces `Planner.direct`. The Night rule's Copy / one-side / Fallback code moved into
  `Planner._borrow`, which both rules call; the vote and Chain run only for a night photo. `weak_direct` + `current`:
  a direct answer with match score under 4,000 is out of date under any version (also from before line-up versions).
  `VERSION` stays 2, so no night answer is measured again. `night_detail` is now `rule_detail`.
- `measure._log_measured`: a day-rule answer writes its detail under `day_borrow` in research-log.jsonl.
- `report.reasons`: `day_borrow` is read like `night` (ok = lined up), with day messages for no neighbour, an
  unplaced photo and an unlistable folder.
- Docstrings in `inference.py` and `distance.py`. Docs: CONTEXT.md "Day borrow", ADR 0002.

**Tests changed, and why:**

- `test_a_day_photo_with_no_line_up_of_its_own_is_not_lined_up`: was direct, status none, with "lines up poorly"
  (3 points) or "did not line up" (40 points). Now day rule, no neighbour, no homography: no distance, the day
  reason, a `day_borrow` log object. The flag photo is made undated so it cannot stand as A.
- `test_a_day_photo_with_a_reason_gets_a_log_line_with_that_reason`: a day photo with 9 points alone in its folder
  had a distance and "lines up poorly"; now no distance and the day reason.
- `test_old_answers_measure_again_once_for_night_photos_and_never_for_day_photos`, renamed `..._and_weak_direct_day_photos`:
  the day answer from before line-up versions has 37 points, so it is now measured again once.
- `test_a_day_photo_that_will_not_decode_does_not_stop_the_run`: unchanged. It measures only the night photo, so the
  day rule never runs there.

**Review fixes (user approval 2026-10-12; the Night rule's code paths unchanged):**

- *Wrong-camera guard* (replaces the open question below). By day a flag photo stands as A or B only when the other
  side is a real day photo with 4,000 points; otherwise `_own_or_none`, with the flag photos found in `flag_only`.
  The reviewer's probe (flag photo 09:00, wrong-camera photos 10:00 / 11:00 / 12:00 at 100 points) copied the
  identity three times; now each has no distance. A deployment start (flag photo A, a strong day photo B) still
  Copies or Falls back; a service visit (two flag photos, no real day photo) does not stand.
- *Burst first* (review M1, `Planner.find_near`). On each side the weak photo's own burst (dated photos within 120 s,
  nearest first) is tried first, with no burst-mate skip; then `find_day` goes on beyond the burst. Counting: the
  burst has its own TRIES budget (3), and its rejected tries neither count against the normal search's 3 nor make
  photos beyond the burst into burst mates. Why: the normal budget and the burst-mate skip were tuned to find an
  anchor across time (folder 38); counting burst frames against them would let a weak burst use up the side and
  bring M1 back (in the probe at 2 min spacing, IMG_0 is 120 s from the rejected IMG_1 and would be skipped).
  The cost stays bounded: at most 6 line-ups to the flag photo a side, each kept in the store.
- *L1*: when the photo's own line-up failed only for the moment (a link not kept: the photo or the flag photo gone
  or locked; `Planner.unreached`), `day_rule` returns UNREAD, so no answer is kept and the next run tries again.
- *L2*: CONTEXT.md and ADR 0002 now say that tries on empty-frame neighbours, and B onto A, are new RoMa line-ups,
  and when `align_folder` is set.
- *L3 tests*: burst first (probe at 2 s and 2 min; the burst's own tries), an undated weak photo (check `undated`),
  an unplaced weak photo (a flag photo's capture time), a Fallback to the flag photo as the nearer side, the guard
  (probe, deployment start, service visit), a locked own line-up.

**Blocked by:** none.

**Status:** implemented with the review fixes, not committed (2026-10-12, branch `fix/day-borrow` from `main` at
67ee52b; the researcher approves commits). Login node: `tests/test_lineup.py` 94 passed (whole file); with
`test_measure.py`, `test_report.py`, `test_batch.py`, `test_clear.py`, `test_api.py`, `test_split_export.py` and
`test_density.py`: 232 passed, 1 skipped (Windows file attributes). No frontend change, so no bundle rebuild. No GPU
check (user: not needed now).

**Closed (2026-10-12):** a dated flag photo of a wrong camera no longer lends its identity line-up (guard above).
