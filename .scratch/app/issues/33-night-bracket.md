# 33 — Night photos borrow a day photo's line-up (the bracket rule)

**What to build:** A night IR photo lines up badly with the daytime flag photo. On the labpc, MAS_CAM07 IMG_0215
(night) got 34 points against IMG_0001, where a day photo gets 9,465; `distance.MIN_INLIERS` = 15 lets it through,
and the burst IMG_0215 / IMG_0216 of one still deer read 6.6 m and 9.9 m. The researcher decided (2026-10-10) that
the *bracket rule* is the main way to measure night photos: a night photo gets no RoMa line-up of its own. It uses
the line-up (homography to the flag photo) of a day photo of the same camera, when the day photos before and after
it agree that the camera did not move.

This is step 3 of the one-fix-at-a-time plan, branch `fix/night-bracket` from `main` at 3c30e63 (steps 1, 2 and 2b
in). Only the bracket and its flags. Left out, each for a later step if wanted: the night chain (night -> day links,
the 2,000-point gate, the night -> night fallback), spot checks and burst sharing (research folder 46), borrowing
for frame-filling photos, hidden feet ("nearer than"), the frontend "Lined up" line.

**Blocked by:** none (30, 29, 32 are in `main`).

**Status:** final Night rule implemented, not committed (2026-10-11, branch `fix/night-bracket`; the researcher
approves commits). It replaces the first design below (5 px, 5,000 points, no answer on a move): see "Decisions after
grilling" and CONTEXT.md "Night photos: the Night rule". `lineup.VERSION` = 2. Tests rewritten
(`tests/test_lineup.py`), `tests/test_report.py` fixed for the `check` column; neither run yet (login node). Check job
`logs/night_bracket_check/` updated to the final rule, not submitted. First design: implemented 2026-10-10, check job
3355652 (1 test failed: the `lineup` column).

## Evidence

Research `../distance_estimation/experiments/refnet/43_bracket_rule` (pre-registered, job 3350827), against the
app's own night chain (folder 38 V3, validated in folder 42):

- Q1 PASS. At 73 MegaDetector box-bottom points on 59 photos, |q50 bracket - q50 chain|: median 0.017 m, p95
  0.090 m, max 0.186 m.
- Q2 FAIL (the risk). 3 of 59 photos with a strong chain sit elsewhere than the borrowed day line-up puts them
  (ground-map p95 0.218-0.444 m); the bracket gives no warning. At their animals the q50 moves by at most 0.122 m.
  MAS_CAM09 IMG_1114, TON_CAM02 IMG_4244, TON_CAM05 IMG_2275.
- Q3. 15 photos the chain cannot measure get a number, among them MAS_CAM07 IMG_0214-0216: near deer q50 9.25 /
  9.25 / 9.13 m (B IMG_0235 -> flag 9,456 points; B -> A 9,386 points, 4.37 px).
- Q4. Of 25 nights, 12 agree, 12 moved (5.71-296 px between the day photos), 1 has no day photo after it.

Folder 43's own conclusion was "do not replace the night link". The researcher chose the bracket anyway, for its
simplicity and the Q1 agreement, and accepts the Q2 risk; this ticket records it.

## Decisions

1. **Day or night.** EXIF Flash bit 0 (Browning writes 13 at night, 16 by day); a photo without the tag is night when
   the mean HSV saturation of a small thumbnail is below 0.05. A photo that cannot be read is lined up as a day photo,
   as before (superseded 2026-10-11, review fix 4: no answer this run, read again next run). Source: folders 38 and 43 use Flash bit 0; the colour fallback is ticket 28's (`lineup.read_night`,
   reused verbatim).
2. **Before and after: the anchors.** Walk the photo's camera folder, in capture-time order, backward (A) and forward
   (B) from the night photo. The anchor is the first day photo whose line-up to the flag photo has >= 5,000 points.
   At most 3 day photos are tried per side; one within 120 s of a rejected one is the same burst and is skipped.
   Source: folder 43 "Anchors", which is `find_anchor` of folder 38 and ticket 28's `Planner.find_anchor` (reused
   verbatim). Every photo of one night gets the same anchors, so the walk per photo equals folder 43's walk per night.
   - *Same camera* = the same folder, as ticket 28 and folder 46 do. A camera split over two folders (two card dumps)
     brackets within each folder only.
   - *Flag photo*: the job's, given by the date rule (`batch.assign`, kept by folder 45). The anchors line up with that
     same flag photo. They are not limited to its date period: folder 43 did not limit them, and the 5,000-point
     line-up to this flag photo and the B -> A test are the position checks.
   - *No maximum time gap.* Folder 43 set none; its agree nights span up to 2.3 days and its risk cases had gaps of
     9-29 h. A gap limit is untested.
3. **The agreement test.** Link B -> A (B the target, A the reference, both banner-cropped, seeded) has >= 1,000
   points and shift p95 <= 5 px. Shift = p95 of |H(p) - p| over a 40 px grid of B's cropped frame. Source: folder 43
   `bracket_rule.py`, `link("bracket", c, anc["B"], anc["A"])`, `LINK_OK`, `SAME_PX`, `lineup.shift_p95`. Under
   1,000 points the shift is not measured, only guessed (folder 38 sub-test D): no answer.
4. **Which day line-up.** The anchor nearer in time to the night photo; a tie goes to A. Its line-up to the flag
   photo is the night photo's homography. Source: folder 43 "near H" (Q1 measured with it; the far H was worse:
   median 0.023, p95 0.129 m).
5. **No answer** (no distance; the detections, species and boxes are kept, as for a photo that does not line up):
   - camera moved: B -> A shift > 5 px;
   - not comparable: B -> A under 1,000 points (a B -> A link that failed because a photo would not decode counts
     here: 0 points);
   - no day photo before, after, or either: an anchor is missing (a day photo that would not decode is a rejected try);
   - no capture time: the photo cannot be placed among the day photos.
   The weak direct night -> flag line-up is never used.
6. **Stored per photo** (columns of `photos`): `alignment_version`, `night` (1, 0), `align_source` (direct /
   bracket), `align_status` (ok / none), `anchor` (the day photo borrowed from), `align_detail` (JSON: before,
   after, side, gap_s, points and px of B -> A, why), `align_folder` (only on a no-day-photo answer: the folder's
   state then). `match_score` of a bracket answer is the borrowed day photo's points against the flag photo. A day
   photo whose own line-up found no homography is `direct` / `none` (never `ok`), with its own points as
   `match_score`; its reason reads "lines up poorly" (under 15 points) or "did not line up", as before ticket 33.
   **Shown:** "needs a look" reasons in plain words with their thresholds (`report.reasons`), and the export's new
   `lineup` column ("direct", "night: line-up of day photo IMG_0235.JPG", "night, not lined up"). An answered night
   photo carries no flag: folder 43's Q2 risk is not visible per photo.
7. **Links are kept.** Every measured link (photo -> flag photo, B -> A) is stored in a `links` table, keyed by both
   files' paths and modification times, the *setting* and `lineup.LINK_VERSION`. The setting
   (`inference.Real.link_setting`) is the fidelity, RoMa's refinement resolution (`distance.upsample_res`; fast
   fidelity picks it by the card) and the weights manifest version, so "Measure again" after a weights update or a
   fidelity change lines the photos up again. Day photos line up through the same store, so a day photo's own answer
   and the night photos borrowing from it use one stored homography.
   Day or night is kept in a `nights` table, keyed by path, size and modification time.
   - *A photo that will not decode* (Pillow raises OSError, ValueError or SyntaxError) gives a failed link: no
     homography, 0 points. The run goes on. The failed link **is stored**, with both files' mtimes, so a broken file
     is not decoded again on every run; a file rewritten (copied again) has a new mtime and is tried again. A file that
     was gone or locked (FileNotFoundError, PermissionError) gives a failed link for that run only, **not stored**: it
     says nothing about the file. In the real app MegaDetector and SpeciesNet set Pillow's LOAD_TRUNCATED_IMAGES on
     import, so a cut-short JPEG decodes with a grey tail instead of failing; only worse damage fails there.
8. **Versions.** `lineup.VERSION` = 1 (new). `measure.current_answer` asks `lineup.current`:
   - an answer under VERSION 1 is current, except a no-day-photo answer whose folder changed since (a photo added,
     removed or changed), which is measured again;
   - an answer from before (no version): current when it had no line-up (no animal, `match_score` empty) or was a
     day photo; a night photo is measured again, once. Whether it was night is read from the file once, at the next
     run, and kept on the row. A listing does not open files: until that run, such a row shows "Out of date". A photo
     the run cannot read is out of date for that run, and nothing is kept on the row, so the next run reads it again
     (before: it was kept as a day photo for good).
   - A borrowed day line-up changes only when the flag photo, its calibration, the fidelity or the line-up versions
     change, and each of these already re-measures the night photo. An edited day photo or a photo inserted inside an
     old night is not noticed: "Measure again" (rerun) re-plans it.
9. **Run order.** No two passes. The planner is lazy: a night photo asks for its anchors' links when it is measured,
   the link is measured once, kept, and the day photo reuses it whenever it is measured itself. The answer does not
   depend on the order, because each link is seeded and depends only on its two files.
10. **Incremental runs.** A whole-folder run skips current answers. A night photo that had no day photo after it is
    measured again once a photo arrives in its folder (decision 8), and gains a bracket if the new day photos close
    it.
11. **One photo alone.** Picked photos and one photo are planned from the camera folder on disk, as a whole run is,
    so the answer is the same. Compare (`Real.align_score`) is unchanged: it scores one photo's own direct line-up,
    which answers "is this the right camera", not a distance.

## Tests

`tests/test_lineup.py`: day/night from Flash and from colour; the shift; a day photo lines up directly; a day photo
with no homography is direct / none with the poor / failed line-up reason; the near anchor's line-up (A nearer, B
nearer, a tie), with no link from the night photo; 5.00 px agrees and 5.01 px is moved; 999 B -> A points is not
comparable; no day photo before / after / either; the anchor search (5,000, 3 tries, burst mates); undated; one
B -> A link per night; a later planner reuses stored links; a link is measured again under another fidelity or
weights version; a day photo that will not decode is a rejected try, kept, and tried again once rewritten; a locked
photo's failed link is not kept; `current` for old day / night / empty answers and the version; an old answer whose
photo cannot be read is not kept as day; a no-day-photo answer goes stale when a photo is added, a bracket answer
does not; FakeModels end to end (staging, reasons, export column); the same answer measured alone and with its folder;
a day photo added later gives the night photo a bracket on the next run while the day photos are skipped; an old night
answer is measured again once and an old day answer is not; a broken anchor does not stop a run; "Measure again"
after a weights update lines up again, with the same weights it reuses the links.

Check job (`logs/night_bracket_check/`), GPU checks first: on folder 43's photos, the app's planner and net reproduce
folder 43's anchors, B -> A test and near-H q50 (calibrations fitted with the code folder 43 ran), then Q1 median /
p95 |dq50| against the chain, IMG_0214-0216, and the Q2 risk cases (a chain link with no homography is recorded and
skipped); answer counts by reason; MAS_CAM07 IMG_0235 and IMG_0124 (day) read by main's `Distance.read` in its own
process (`day_main.py`, main 3c30e63) against this branch's `Distance.read` and the planner's direct H + `Real._read`
(np.array_equal on H and quantiles); the same three photos end to end through `measure.start` (a failure is recorded
in e2e.json and summary.txt). Each output file is written as its step ends; summary.txt is written last whatever
fails. Then the suite on branch and on main, each cut at 900 s.

## Decisions after grilling (2026-10-11), implemented 2026-10-11 (not committed)

The grilling is complete. The code and the text above still follow the first design (5 px, 5,000 points, no chain, no
flag-photo day photos, export column `lineup`). The grilling (`33-night-bracket-grilling.md`; ADR
`docs/adr/0001-night-photos-borrow-a-day-line-up.md`) set the **Night rule**, with two parts: **Copy** (the bracket rule)
and **Chain**, plus a **Fallback**:

- Night photo: the camera fired its IR flash (EXIF Flash bit 0); if the tag is missing, a grayscale thumbnail means night.
- Day photos A (before) and B (after) in the same camera folder: line-up to the flag photo >= 4,000 points (Q6; 5,000
  before), up to 3 tries a side, burst mates within 120 s of a rejected try skipped. No time limit (Q1a).
- The flag photo itself can be A at the start of a deployment, and a later flag photo of the same camera can be B at the
  end (Q5). The flag photo is chosen by the date rule (folder 45): the latest on or before the night photo, else the
  earliest. A and B are always lined up to that same flag photo.
- Both found: line B up onto A. <= 20 px (was 5 px; Q3a): Copy the nearer. > 20 px: line the night photo up to A and
  to B; more points wins (Q3b). If that night -> day line-up has >= 2,000 points and shift p95 < 300 px: Chain through
  the winner (Q8). Otherwise Fallback: copy the nearer day photo (Q9).
- Only one found: Copy it (no UI mark; the researcher log's `night.checks` says `unchecked`; the export column that said
  "Check by eye: camera move not checked" was removed 2026-10-11, see follow-up F).
- Never line a night photo up to the flag photo directly (Q10). This replaces the earlier "fewer than 15 points ->
  direct night -> flag -> nearer" steps (Q7, superseded; they never triggered in folder 60).
- The move check stays the direct B -> A line-up (flag-frame check rejected, folder 58).
- No capture time: place the photo by file-name number within the folder, else by file modified time (Q13).
- Export: one column `check` (Q11), removed 2026-10-11 (user decision, follow-up F): the checks `moved`,
  `unchecked` and `undated` go only to the researcher log in the app's own logs folder, not next to the export (Q12).
  No mark in the app UI. Since 2026-10-11 that log is `research-log.jsonl`, one line per measured photo ("A ok but
  can you make one research log"); a night photo's line carries the Night-rule detail under `night`.
- Evidence (folder 60, CPU): 0 of 896 reference-ok points over 1 m with Chain + Fallback, against 29 of 1,120 for
  Copy of the nearer day photo.

## Review fixes (2026-10-11, not committed, not run: login node)

Applied after a review of the final rule; CONTEXT.md "Night photos: the Night rule" carries the result.

1. Check job `check_moved.py`: a planner lists each camera folder once (`Planner.camera`), but later nights' photos
   were copied in after it was built, so (review count) 237 of 1,353 photos (205 of 1,120 points; M2 case 3) were "unplaced" and
   silently dropped. Now every photo of M2 and M1 is copied first, then planned; the summary reports the "unplaced"
   and "unread" counts (must be 0).
2. M2's label: a job flag photo standing as B was labelled "no flag photo used". Now each side is named: "A = job
   flag", "B = job flag", "B = later flag", "A = earlier flag".
3. One undated photo no longer reorders the folder. Dated photos keep capture-time order; each undated photo is
   placed alone by its file number between dated neighbours, else by file modification time (`Camera._place`).
   `detail.order` is the night photo's own placement.
4. Day or night unreadable now (`Planner.night` None): no direct line-up (it could be a night -> flag link) and no
   night = 0. The line is `unread`; `measure._job` keeps no answer and counts the photo unreadable; the next run reads
   it again (as review fix B for old answers).
5. `log_night` catches any exception. Duplicates: a line is written only when an answer is measured, so a run that
   skips current answers adds none; "Measure again" adds a timestamped line. Growth is unbounded (follow-up G).
6. A flag photo of another pixel size than the night photo is passed over as A or B (identity maps the flag photo's
   pixels; any other use would be a night -> flag link). Applied to later flag photos too, for the same reason.
7. Renamed flag-photo copy: a folder photo with a flag photo's capture time is that flag photo, whatever its name.
   Capture time alone, not time + pixel size: it holds even when the synced flag photo was resized. Cost: a different
   photo taken in the same second as a flag photo is left out of the A/B search (the flag photo stands there).
8. Export header: "no photo date" now says "placed by its file number or file time".
9. `Camera` catches the ValueError of an unlistable folder: the night photo gets no distance, why `no_folder`, with
   `align_folder` = "unreadable" so it is planned again next run.
10. A night photo that copies the flag photo itself keeps `match_score` empty (no line-up points of its own; B's
    points would describe a line-up it did not use). The frontend change goes to the rebuild (follow-up F).

## Follow-ups

- C. One SQLite connection per run (or per planner) instead of one per `store.link` / `store.night` call.
- D. A no-day-photo answer is planned again when any photo arrives in its folder; re-plan it only when a day photo
  arrives on its missing side. Re-planning cost: each such answer is planned from scratch, its links from the store.
- E. After the upgrade, a listing shows night answers from line-up version 1 or before as "Out of date" until the
  next run measures them again (by design: they were measured under another rule).
- F. Frontend rebuild: `linesUp` (frontend/src/ui.tsx:255) reads an empty `match_score` as "No". For a night row it
  must read `align_status` (ok -> "Good"), so a night photo that copies the flag photo itself does not show "Lines
  up: No". Also the "Lined up" line (Q11 keeps it out of the UI marks).
  **Status (2026-10-11): source fixed, bundle not rebuilt, not committed** (branch `fix/lines-up` from `main`
  1ac10b8). Affected: only an answered night photo whose borrowed line-up is the job's flag photo itself (Copy with
  the flag photo nearer, One side with only the flag photo, Fallback with the flag photo nearer). Its `match_score` is
  empty (`lineup.IDENTITY` has no inliers), so the window said "No" (Measure panel, table cell and detail, the cell
  in red). A Chain never uses the flag photo; a later flag photo standing as B has measured points; day photos are
  unchanged. Fix: `Row` gains `align_source` and `align_status` (the engine already sent them), and `linesUp` reads a
  night row by them first: ok -> "Good", else "No". No new UI element. The committed bundle
  (`src/camtrap_measure/ui/assets/`) keeps the old rule until `cd frontend && npm ci && npm run build` runs on a
  machine with Node and the rebuilt `ui/` is committed. Test
  `test_a_night_photo_that_copies_the_flag_photo_itself_is_listed_as_lined_up_with_no_points` pins the listing fields
  `linesUp` reads (passed alone on the login node, 1.6 s). Left open: the "Lined up" line (not built).
  **No-animal photos (researcher's option (a), 2026-10-11):** a measured photo with no animal also had an empty
  `match_score` and showed "No" (since 2026-09-29, day or night). Empty frames are never lined up, so `linesUp` now
  returns the empty mark "–" (`NONE`) when `measured` and `detections` is empty, before the night rule. "–" is not a
  warning: the Measure panel warns and the table colours red only on "Check" or "No"; the table cell shows "–" in
  `--faint`, as the empty "Sure" cell beside it. Unchanged: a photo not yet measured ("–" as before) and a night photo
  with no answer ("No"; it keeps its boxes, so `detections` is not empty). Test
  `test_a_measured_photo_with_no_animal_is_listed_apart_from_a_night_photo_with_no_answer` pins those listing fields
  (passed alone on the login node, 1.3 s). No backend change.
  **Now (user decisions 2026-10-11, branch `fix/lines-up`, not committed): the line is removed.** "I want to simplify
  the ui": the "Lines up" table column, the detail-pane line, the Measure panel line, its help topic, `linesUp` and the
  `Row` fields `align_source` / `align_status` are gone, so the fix above is moot. The export's `check` column and
  `report.check_text` are removed too: "Only save in the log don't include it in the csv which the wildlife
  collaborators will use. Don't need the same information to be saved in three places." The checks stay in the
  researcher log's `night.checks` field (`moved`, `unchecked`, `undated`, with `path`, `side`, `anchor`) and in the stored
  `align_detail`. The two tests were rewritten for what they still pin: the night photo that copies the flag photo is
  exported with its distance and its check is in the log only; a night photo with no answer is a CSV row with an
  empty distance, and an empty frame is no row. The same day the user also removed "Needs a look", the CSV's warning
  text, `#` lines, `flag` column and SAM3, cut the CSV to seven columns, removed the Table's export button and five
  repeated read-outs, and removed the DENSITY tab: the app gives distances only, and density estimation is the
  wildlife staff's own task (CONTEXT.md, "Window and CSV simplified"). Last, the night-only `night-rule.jsonl`
  became one researcher log, `research-log.jsonl`: one line per measured photo, day or night, with its reasons (the
  only place they are written), the Night-rule detail under `night` for a night photo, and one line per unreadable
  file per run ("A ok but can you make one research log").
- G. The researcher log is never trimmed. Since 2026-10-11 it is `research-log.jsonl` with one line per photo
  measured (night photos only before), so it grows by about one line per photo, every run that measures; a
  "Measure again" adds a line per photo again. Still not built: rotation or trimming.
- H. A flag-photo copy in the folder that lost its capture time (re-saved without EXIF) is not recognised as a flag
  photo and could vote; a file hash would catch it. Not built.
