# 0002. A weak day photo borrows a day photo's line-up (day rule)

Date: 2026-10-12. Status: accepted; implemented 2026-10-12 on branch `fix/day-borrow`, not committed.

## Context

Until now every day photo lined up directly with the flag photo, however few points that line-up had. When an
animal fills the frame it hides the background, and the photo's own line-up breaks with no warning. All 8 verified
weak frame-filling day photos (86-2,339 points) had broken homographies (a shift of 400-5,300 px, against 20-120 px
for strong neighbours). TON_CAM04 IMG_0982 / IMG_0981 read 9.30 / 10.48 m where their burst mates read
11.18-11.40 m. A wrong camera behaves the same way: 54-276 points, above `distance.MIN_INLIERS` = 15, so a
plausible wrong distance with no reason. Night photos already avoid their own line-up through the Night rule
(ADR 0001).

## Decision

Decided 2026-10-12:

- A day photo keeps its direct line-up only when it has a homography and at least 4,000 points (the Night rule's
  `DAY_MIN`). Otherwise the day rule runs.
- The day rule uses the Night rule's search for day photos A and B (same folder, 4,000 points to the flag photo,
  3 tries a side, burst mates skipped, flag photos as A or B, the same pixel size).
- Both found: line B up onto A. Within 20 px with 1,000 points or more: Copy the nearer. Otherwise Fallback: copy the
  nearer, logged as `moved`. No vote and no Chain ("no chain").
- One found: Copy it.
- None found: keep the own line-up from 2,500 points with a homography; otherwise no distance, with a reason that
  goes to the researcher log only.
- No window change and no CSV change. A stored direct day answer under 4,000 points is measured again once.

Amended after review, user approval 2026-10-12:

- Burst first: on each side the weak photo's own burst (dated photos within 120 s of it, nearest first) is tried
  first, with no burst-mate skip and a budget of 3 tries of its own. Then the normal search goes on beyond the burst.
  Before, one rejected weak frame hid every strong frame within 120 s of it.
- Wrong-camera guard: a flag photo stands as A or B only when the other side is a real day photo with 4,000 points.
  Otherwise the photo keeps its own line-up from 2,500 points, or has no distance.
- A day photo whose own line-up failed only for the moment (a file locked or gone) keeps no answer and is tried
  again on the next run.

## Consequences

- Day photos no longer always line up directly. About 3.5% of day animal photos (of 1,087; 14% of those with a box
  share of 50% or more) now carry a neighbour's line-up. 99.3% of frame-filling day photos have a clearer photo within
  120 s, so most get a Copy.
- A day photo can now have no distance where it had one before: no neighbour and fewer than 2,500 points. On a wrong
  camera this replaces a silent wrong distance. The cost: a right-camera photo under 2,500 points with no clear
  photo near it loses its number (small dawn or dusk animals at 1,122-4,000 points were usually right).
- By day a flag photo no longer stands alone. On a wrong camera no photo copies the wrong flag photo's identity
  line-up. The cost: a weak photo between a flag photo and no strong day photo (a deployment's first frames before
  any clear day photo, or a service visit with two flag photos around it) uses its own line-up from 2,500 points, or
  has no distance, where the identity would have been right.
- `lineup.VERSION` stays 2. `lineup.current` calls only weak direct day answers out of date, so no night answer is
  measured again. Reversing the rule later needs the opposite: a stale rule for `day_borrow` answers.
- New RoMa line-ups per weak day photo. Its neighbours' links to the flag photo are not always ones their own
  answers use: a neighbour with no animal (an empty frame) is never lined up for its own answer, so each try on one
  is a new line-up, and so is B onto A. Burst first allows up to 6 tries a side instead of 3. Every link is kept in
  the store and reused by later runs and by the other frames of the burst.

## Alternatives considered

- *Chain and vote by day, as at night*: rejected by the user ("no chain"). A weak own line-up is the problem, so a
  link from the weak photo to a day photo is not trusted either.
- *Keep the own line-up whenever there is no neighbour*: rejected. A wrong camera (54-276 points) would keep its wrong
  distance. 2,500 points keeps the small-animal cases that were right.
- *Bump `lineup.VERSION`*: rejected. Every night answer would be measured again for a change that does not touch
  night photos.

## Evidence

A read-only check of the day animal photos (2026-10-12): of 1,087 day animal photos (median 8,211 points), 3.5% had
under 4,000 points, rising to 14% when the animal's box covered half the frame or more, and all 8 verified weak
frame-filling photos had broken line-ups; 99.3% of frame-filling day photos have a clearer photo within 120 s. The
Night rule's thresholds come from research folders 38, 58, 59 and 60 (ADR 0001).
