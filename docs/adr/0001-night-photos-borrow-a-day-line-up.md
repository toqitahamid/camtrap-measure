# 0001. Night photos copy or chain from a day photo's line-up (Night rule)

Date: 2026-10-10; final 2026-10-11. Status: accepted; implemented 2026-10-11 on branch `fix/night-bracket`, not committed (ticket 33).

## Context

A night IR photo lines up badly with the daytime flag photo (MAS_CAM07 IMG_0215: 34 points, against 9,465 for a day
photo), so its distance is unreliable. The **Night rule** is the whole rule for night photos. Its first part, **Copy**
(the bracket rule), gives a night photo no line-up of its own: it copies the line-up (homography to the flag photo) of
the day photo before it (A) or after it (B), when B lined up onto A shows the camera did not move. Its second part,
**Chain**, handles a camera that moved: the night photo lines up to the winning day photo, and that line-up is
multiplied with the day photo's line-up to the flag photo.

## Decision

Use the Night rule (Copy + Chain + Fallback). Details after the grilling of 2026-10-10/11 (see
`.scratch/app/issues/33-night-bracket-grilling.md`):

- A night photo is one where the camera fired its IR flash (EXIF Flash bit 0); if the tag is missing, a grayscale
  thumbnail means night.
- Day photos A and B are in the same camera folder and have a line-up to the flag photo of >= 4,000 points, 3 tries a
  side, burst mates within 120 s of a rejected try skipped. No time limit. The flag photo itself can be A at the start
  of a deployment, and a later flag photo of the same camera can be B at the end.
- The flag photo is chosen by the date rule (folder 45): the latest flag photo of that camera on or before the night
  photo, else the earliest. A and B are lined up to that same flag photo.
- The move check is the direct B -> A line-up, with the threshold raised from 5 px to 20 px. At <= 20 px, Copy the
  nearer day photo.
- At > 20 px, line the night photo up to A and to B; the side with more points wins. If that night -> day line-up has
  >= 2,000 points and a shift p95 < 300 px, Chain through the winner. Otherwise Fallback: copy the nearer day photo.
- Only one day photo found: Copy it.
- Never line a night photo up to the flag photo directly (the researcher: "i dont want the night to flag line up which
  the app currently uses. it will bring wrong answer.").
- No capture time: place the photo by file-name number within the folder, else by file modified time, then apply the
  rule.
- What to check by eye goes to the researcher log only, in the app's own logs folder (`research-log.jsonl`, the
  night photo's `night.checks`: `moved` for a Fallback after a move, `unchecked` for one day photo only, `undated`
  for no photo date). No mark in the app UI, and no column in the export. (Amended 2026-10-11. The first version put
  these words in an export column `check`. The user reversed that: "Only save in the log don't include it in the csv
  which the wildlife collaborators will use. Don't need the same information to be saved in three places." The
  night-only `night-rule.jsonl` then became one log for every photo: "A ok but can you make one research log".)

## Consequences

- Copy saves one RoMa line-up per night photo; only moved nights (> 20 px) cost night -> day line-ups. The app needs no
  night -> night links.
- Moved nights (research folder 60; 33 nights, 1,353 night photos, 1,120 animal box points; errors estimated as
  0.671 x reference-map change, about a quarter too low): Chain with Fallback leaves 0 of 896 points with "ok"
  references over 1 m (max 0.997 m); copying the nearer day photo leaves 29 of 1,120 over 1 m (max 3.44 m); copying the
  voted day photo leaves 55 (max 7.65 m). 21% of moved-night photos (286 of 1,353) fall back.
- Where the chain and the bracket both work they agree to a median 0.017 m (p95 0.090 m). 3 of 59 chain-strong photos
  sit elsewhere than the borrowed line-up puts them, by at most 0.122 m at the animal, with no warning.
- Coverage on 17 MAS cameras: 98.8% of night photos (11,283 of 11,415) have a day photo on both sides.
- A photo on a night run with no day photo within hours is still answered; the move check is the only safeguard.
- At 20 px, the borrowed distance can shift by about 0.86 m at 20 m (MAS_CAM07), inside the 1 m tolerance.

## Alternatives considered

- *Night chain for every night photo* (research folder 38): adds a check only, costs a line-up per night photo. Not
  built; Chain is used only on moved nights.
- *Direct night -> flag line-up as a last resort* (first design): rejected by the researcher; it gives wrong answers.
  The fallbacks never triggered in folder 60 (weakest night -> day side 38 points; 0 of 1,353 photos under 15).
- *Flag-frame move check* (compare the day photos' line-ups to the flag photo; folder 58): two line-ups of one photo differ
  by up to 33.7 px (p95 13.3 px); no threshold reproduced the direct verdict (best 144 of 166 nights). Rejected.
- *Time limit on one-sided borrowing*: night runs last days (15 of 25 over 24 h, longest 387.5 h); a limit would refuse
  photos the move check can judge. Rejected.

## Evidence

Research repo `experiments/refnet/` folders 38, 42, 43, 57, 58, 59 (anchor threshold 4,000 points), 60_vote_check
(vote, Chain gate, Fallback).
