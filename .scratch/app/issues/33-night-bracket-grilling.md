# 33 — Night rule: design grilling (2026-10-10/11)

**Result first.** The grilling is complete (2026-10-11). The design is final and is implemented on branch
`fix/night-bracket` (2026-10-11, not committed; `lineup.VERSION` 2); tests and the check job are not yet run.
The **Night rule** is the whole rule for night photos. It has two parts. **Copy**: the camera did not move, so the
night photo copies the nearer day photo's line-up (this is the bracket rule). **Chain**: the camera moved, so the night
photo lines up to the winning day photo, and that line-up is multiplied with the day photo's line-up to the flag
photo. **Fallback**: when the chain fails its check, copy the nearer day photo. A night photo is never lined up to the
flag photo directly (Q10). The final rule is in "Final rule" below; the reasons are in Q1-Q13.
The decisions are summarised in `docs/adr/0001-night-photos-borrow-a-day-line-up.md`. This file records each question,
its options, the data shown and the answer, so the reasons can be read later.

**Terms.** *Line-up*: the homography (a mapping of pixel positions) from a photo to the flag photo, found by RoMa;
its *points* are the matches that agree with it. *Flag photo*: the photo of the calibration flags. *Night photo*: a
photo where the camera fired its IR flash (EXIF Flash bit 0); if the tag is missing, a grayscale thumbnail means night.
*Day photo A* / *B*: the day photo before / after a night photo, in the same camera folder, whose line-up to the flag
photo has >= 4,000 points (Q6; 5,000 before; 3 tries a side; a burst mate within 120 s of a rejected try is skipped).
*Move check*: the B -> A line-up, which tests that the camera did not move between A and B. *Night run*: consecutive
night photos with no day photo between them. `MIN_INLIERS` = 15 is the app's minimum number of points for any line-up.
Earlier text in this log used "anchor" for a day photo and "bracket rule" for Copy; read them as Day photo and Copy.

## Final rule (2026-10-11)

1. Night photo: the camera fired its IR flash (EXIF Flash bit 0); if the tag is missing, a grayscale thumbnail means
   night.
2. Find day photo A (before) and B (after) in the same camera folder. Each needs a line-up to the flag photo of >= 4,000
   points (Q6), up to 3 tries per side; burst mates within 120 s of a rejected try are skipped. At the start or end of a
   deployment the flag photo itself can be A, and a later flag photo of the same camera can be B (Q5). No time limit
   (Q1a).
3. Flag photo = the date rule (research folder 45): the latest flag photo of that camera taken on or before the night
   photo, else the earliest. A and B are always lined up to that same flag photo.
4. Both found: line B up onto A. If the shift is <= 20 px (Q3a), Copy the nearer day photo. If it is > 20 px, line the
   night photo up to A and to B; the side with more points wins (Q3b). If that night -> day line-up has >= 2,000 points
   and a shift p95 < 300 px, Chain through the winner (Q8). Otherwise Fallback: copy the nearer day photo (Q9).
5. Only one found: Copy it.
6. Never line a night photo up to the flag photo directly (Q10).
7. No capture time: place the photo by its file-name number within the folder (camera counter); if that fails (counter
   restart), by file modified time; then apply the rules above (Q13). Only the undated photo is placed this way; the
   dated photos keep capture-time order (review 2026-10-11).
8. Export: one column `check` (Q11); technical detail goes to a researcher log (Q12).

## Starting point

Step 3 of the one-fix-at-a-time plan is the bracket rule (ticket 33; now Copy). A night photo gets no line-up of its
own. It copies the line-up of A or B, as defined above. B is lined up onto A (>= 1,000 points, shift p95 <= 5 px) to check that
the camera did not move. The nearer anchor wins; a tie goes to A.

## Principles stated by the researcher

- "i want the app as simple as possible in ui experience"
- "i can tolerate up to 1 meter error"
- "i need a solution when the camera moved, dont afford a no answer"

## Why the bracket, not the night chain

*Question (researcher):* "if the chain cannot give an answer which the bracket can, why do we need the chain?"

*Data.* Where both work, they agree to a median 0.017 m (p95 0.090 m; research folder 43). The chain adds one thing, a
check, and costs one RoMa line-up per night photo. Coverage of the bracket on 17 MAS cameras (folder 57; PARTIAL, a
Level 1 upper bound): 11,283 of 11,415 night photos (98.8%) have a day photo before and after, with no gap limit.

*Decision:* the bracket is the main method. The night chain is not built. Status: decided.

## Check job 3355652 (the branch, before these decisions)

- It reproduces folder 43: same anchors and verdicts on 184 photos; Q1 median 0.015 / p95 0.090 / max 0.186 m;
  3 of 59 risk cases; day photos bit-identical to main 3c30e63.
- 1 test fails: `tests/test_report.py:254` expects no `lineup` key.
- 102 of 184 night photos read "camera moved" at 5 px. The count is inflated by selection: MAS_CAM04 and MAS_CAM24
  give 49 of them.
- MAS_CAM07 IMG_0214 / 0215 / 0216, near deer: 9.25 / 9.25 / 9.13 m (folder 43 calibration); 8.84 / 8.87 / 8.81 m
  (step 2 calibration).

## Q1. Only one side has an anchor

*Options:* (a) no answer; (b) borrow the one side, with a flag; (c) borrow the one side within a time limit.
*First choice:* (c).

### Q1a. The time limit

*Data.* Night runs are often days long, because the camera does not trigger by day. Of 25 runs in folder 43, 15 last
over 24 h and 4 over 100 h (longest 387.5 h, MAS_CAM24). The gap from a run's edge to the nearest day photo has a
median of 10.8 h. A limit of the order of hours would refuse many photos that the move check can judge.
*Decision:* no time limit. The move check is the safeguard. Status: decided.

### Q1b. A flag in the UI for one-sided answers

*Decision:* no flag. The reason is kept in the export only (simple UI). Status: decided.

## Q2. Check the move through the flag photo instead of a B -> A line-up

*Proposal.* Compare the two anchors' line-ups to the flag photo, which saves the B -> A call. Tested in research
folder 58 on 166 nights.

*Data.* Two line-ups of the same day photo to the flag photo differ by up to 33.7 px (p95 13.3 px), so comparing two
of them adds their noise. The direct B -> A line-up repeats within p95 0.86 px and costs about 0.3 s per night. No
threshold reproduces the direct verdict (best 144 of 166). "Not comparable" (B -> A under 1,000 points) never
occurred (minimum 4,838 points).

*Decision:* rejected; keep the direct B -> A line-up. Status: decided.

## Q3a. The move threshold

*Decision:* raise it from 5 px to 20 px.

*Data* (folder 43; 86 deer boxes on moved nights; |q50 near - q50 far| in metres, the gap between borrowing from A
and from B):

| B -> A shift | boxes | median | max | over 1 m |
|---|---|---|---|---|
| 5-20 px | 35 | 0.09 | 0.69 | 0 |
| 20-50 px | 28 | 0.23 | 2.08 | 4 |
| over 50 px | 23 | 2.11 | 4.71 | 18 |

*Caveat:* the 5-20 px row rests on 6 nights. *Rough rule:* 1 px of vertical error at ground distance d moves the
distance by (d^2 + h^2) / (f h). For MAS_CAM07 (h 0.76 m, f 3067 px), 5 px gives 0.06 / 0.22 / 0.48 / 0.86 m at
5 / 10 / 15 / 20 m. This fits the 1 m tolerance. Status: decided.

## Q3b. The camera moved by more than 20 px

*Options:* (a) vote: line the night photo up to A and to B, and borrow from the one with more points; (b) find the
moment of the move with night -> night line-ups; (c) today's direct night -> flag line-up.

*Decision:* (a). (c) was first kept as the last resort and was then rejected (Q10). (b) is dropped, because the vote
already gives each photo its side. The vote picks the side; Q8 and Q9 decide whether the night photo copies or chains.
Status: decided.

## Q4b. Number of tries per side

*Data.* 48 of 49 anchor searches succeeded on the first try. The only rejections were 4,799 and 4,594 points
(TON_CAM30 IMG_3451, side B).
*Decision:* keep 3. Status: decided.

## Q5. The flag photo as an anchor (researcher's idea)

Use the flag photo as anchor A for night photos before the first day photo of a deployment, and the next flag photo
of the same camera as anchor B at the end. The move check is the same; B -> A is then B's own anchor line-up to the
flag photo.
*Decision:* yes. Status: decided.

## Q6. Anchor threshold: 5,000 points or lower

5,000 was chosen in folder 38 and not tuned. Research folder 59 (CPU, saved links) tested whether a lower threshold
raises distance error.
*Options:* (a) keep 5,000; (b) lower to 4,000; (c) lower to 3,000 or below.
*Decision (2026-10-11):* (b), the researcher's choice.

*Data* (folder 59). Same-position pairs, ground-map p95 of the line-up, and distance error:

| Weakest link | pairs / chains | ground-map p95 median (max) | error at 15 m | max error at animal points |
|---|---|---|---|---|
| >= 5,000 (baseline) | | 0.088 m | 0.287 m | 0.327 m |
| 4,000-4,999 | 3 photos, 3 cameras | 0.132 m (0.187 m) | 0.230 m | 0.160 m |

Repeat noise of night chains by weakest link:

| Weakest link | p95 | chains over 1 m |
|---|---|---|
| 4,000-4,999 | 0.133 m | 0 |
| 3,000-3,999 | 0.393 m | 1 of 62 |
| 2,000-2,999 | 0.538 m | 3 of 65 |

*Gain:* +11 bracket nights and +471 night photos, over 206 nights on 61 cameras.
*Caveat:* the direct same-position sample at 4,000-4,999 is only 3 photos on 3 cameras.
*Why not lower:* below 3,000 there is no same-position evidence for 1,000-2,999; the one link under 1,000 is off
1.47 m at 15 m; the gain there is only +3 photos.
Status: decided (closed). Not yet in the code.

## Q7. The vote rule (superseded by Q8-Q10, 2026-10-11)

First design: borrow from the side with more points. If both sides have fewer than 15 points (`MIN_INLIERS`), try the
direct night -> flag line-up. If that also has fewer than 15 points, borrow the NEARER day photo's line-up.
Q7 is superseded: Q10 removes the direct night -> flag step, and Q8 and Q9 replace the "fewer than 15 points" tests.
The fallbacks never triggered in folder 60: the weakest night -> day side had 38 points, and 0 of 1,353 photos had
fewer than 15.
Status: superseded.

## Q8. Chain through the winning side, with a gate

*Rule.* After the vote (Q3b), line the night photo up to the winning day photo and multiply that line-up with the day
photo's line-up to the flag photo. Use the chain only if the night -> day line-up has >= 2,000 points and a shift
p95 < 300 px. Otherwise go to Q9.
*Data* (research folder 60_vote_check; CPU, saved links; 33 moved nights on 27 camera folders, 1,353 night photos,
1,120 animal box points; reference = research night chain V3; distance errors are estimated as 0.671 x the
reference-map change, which understates real errors by about a quarter):

| Method | points over 1 m | max error |
|---|---|---|
| Copy the voted day photo | 55 of 1,120 | 7.65 m |
| Copy the nearer day photo | 29 of 1,120 | 3.44 m |
| Chain through the voted side (gate >= 2,000 points, shift < 300 px), else copy the nearer | 0 of 896 points with "ok" references | 0.997 m |

All 8 remaining points over 1 m are in one night (MAS_CAM02 2026-01-23, 95.6 px move). The vote side agrees with the
chain side on 1,094 of 1,199 photos. Night -> day line-ups are strong (median about 5,300 points). The shift cap
catches 2 broken links that passed 2,000 points: MAS_CAM32 IMG_0046 (2,407 points, 2,094 px) and TON_CAM11 IMG_2944
(2,061 points, 1,829 px). MAS_CAM07 IMG_1915: A 5.97 m, B 5.56 m, chain 6.19 m (night -> A has 946 points, so it
falls back).
Status: decided.

## Q9. Fallback when the chain fails its check

*Rule.* Copy the nearer day photo.
*Options.* (a) copy the nearer; (b) copy the voted side.
*Data* (folder 60, same sample as Q8). Nearer: 8 points over 1 m (max 1.56 m). Voted: 11 (max 4.27 m).
21% of moved-night photos (286 of 1,353) fall back.
*Decision:* (a). Status: decided.

## Q10. Never line a night photo up to the flag photo directly

The researcher: "i dont want the night to flag line up which the app currently uses. it will bring wrong answer."
*Decision:* the Night rule has no direct night -> flag step, not even as a last resort. This replaces the Q7 fallback.
Status: decided.

## Q11. Export column

Users are wildlife staff, not the researcher. The export gets one column `check`, in plain words:
- Empty when the number is fine.
- "Check by eye: camera moved" for Fallback after a move.
- "Check by eye: camera move not checked" when only one day photo exists.
- "Check by eye: no photo date" when the order came from the file number or file time (Q13).
The app UI shows no mark (Q1b). The old column `lineup` goes away.
Status: decided.

## Q12. Technical detail goes to a researcher log

Which day photo, how many points, how many px, Copy or Chain: all go to a log in the app's own logs folder, not next
to the export, so general users never see it. Status: decided.

## Q13. Photos with no capture time

*Rule (option a).* Place the photo by its file-name number within the folder (camera counter). If that fails (counter
restart), place it by file modified time. Then apply the normal rule, and mark the export "Check by eye: no photo
date" (Q11). Status: decided.
*Implementation (review 2026-10-11).* Each undated photo is placed alone, between the dated photos with the next lower
and next higher file number when those two are neighbours in time; else after the dated photo with the latest file
modified time not after its own. The dated photos are never reordered: the first code sent a whole folder to number or
file-time order for one undated photo. A photo whose day or night cannot be read at the moment it is measured gets no
answer that run (never the direct line-up, which could be a night -> flag link) and is read again next run.

## Open follow-ups

- Rebuild the frontend (no "Lined up" line yet).
- Ticket 33 follow-ups C (one SQLite connection per run) and D (re-plan a no-day-photo answer only when a day photo
  arrives on its missing side).
- ~~Implement the Night rule (Q1, Q3a, Q3b, Q5, Q6, Q8-Q13).~~ Done 2026-10-11 (not committed). Choices made in the
  code beyond this log: a flag photo enters the time order at its EXIF capture time; a flag photo takes no part in the
  vote (no night photo is linked to any flag photo); "not comparable" goes to the vote; no answer only with no day
  photo and no dated flag photo on either side; the Chain gate is shift p95 < 300 px as written here (folder 60's code
  used <= 300; no link sat at exactly 300); a vote tie goes to the nearer (folder 60's tie rule). Review 2026-10-11:
  a flag photo of another pixel size than the night photo is passed over as A or B; a folder photo with a flag
  photo's capture time is that flag photo, whatever its name (a renamed copy never votes); a night photo that copies
  the flag photo itself keeps an empty match score, and the frontend rebuild reads night rows by `align_status`.
- ~~Fix `tests/test_report.py` for the `lineup` key.~~ Done (the `check` column).
- The vote check is closed (Q8, Q9; folder 60).

## Evidence

Research repo `experiments/refnet/`: 38, 42, 43 (rule and check against the chain), 57 (coverage, `anchor_gap/`),
58 (flag-frame move check, `moved_cost/`), 59 (anchor threshold, Q6), 60_vote_check (vote, Chain gate, Fallback;
Q8, Q9).

## Note (2026-10-11, after the grilling): Q11's export decision reversed

The user reversed Q11's export column. The words "Check by eye: ..." no longer go to the CSV `check` column: "Only
save in the log don't include it in the csv which the wildlife collaborators will use. Don't need the same
information to be saved in three places." The checks (`moved`, `unchecked`, `undated`) now live only in the
researcher log (Q12, `night-rule.jsonl`, field `checks`) and in the stored line-up detail the app needs. The record
above is kept as history.

Later the same day Q12's log changed too: the night-only `night-rule.jsonl` became one researcher log,
`research-log.jsonl`, with one line per measured photo, day or night, and its reasons ("A ok but can you make one
research log"). A night photo's checks are now its line's `night.checks`.
