# 27 — Measure a whole site folder in one go, each camera against its own flag photo

**What to build:** Seth (department) emailed on 2026-10-05: he wants to choose a site folder that holds all its
camera folders and have every camera measured in one go, each against its own flag photo, matched by name. The
researcher approved the mockup (`.scratch/design/BatchRun.html`: check the cameras, measuring, done, and the
Compare dialog) and the rules below on 2026-10-05.

Separately, the dev store showed a real wrong-camera mistake: the photos in `D:\research\photo\MAS_CAM14`,
stamped "MAS14" in EXIF, were measured as MAS_CAM04. Their match score was 54 to 276 points, against about 8,600
to 9,100 for correct photos, so the alignment warning (MIN_INLIERS) never fired. The camera stamp check below
catches this before anything is measured. MIN_INLIERS is not changed here; that is a separate decision.

**Blocked by:** 15 (pick the flag photo), 22 (flag photo and clearing), 26 (sites) — all done.

**Status:** ready-for-agent

## 1. Site folder detection

- The chosen folder has no JPEGs directly inside, and has subfolders that do: it is a site folder, and MEASURE
  shows the batch table. A folder with JPEGs directly inside works exactly as today.
- A camera folder may hold its photos in a nested subfolder (`MAS_CAM07\filtered\`). The nearest ancestor name
  that matches a camera names it.
- Subfolders with no JPEGs go in "Skipped".

## 2. Name matching

- Normalise: case-insensitive; ignore spaces, `_` and `-`; ignore leading zeros. "mas cam 2", "MAS_CAM2" and
  "mas_cam02" all mean MAS_CAM02.
- The camera name may appear anywhere in the folder name: `MAS_CAM07_filtered`, `2026_MAS_CAM07`,
  "MAS_CAM07 deer only".
- Number boundaries hold: MAS_CAM1 never matches inside MAS_CAM14.
- A name that matches more than one camera goes to "Needs your attention" for the user to choose.
- The row says how it matched when the folder name differs from the camera name.

## 3. Camera stamp check

- Browning writes the camera name into EXIF UserComment, e.g. `C[P] R0S1 T25F:P0000 MAS01   M1`: MAS01 is
  MAS_CAM01. Parse a SITE+number token when present and compare it with the matched camera.
- Mismatch: the row goes to "Needs your attention", unticked, with "The photos say they are from MAS_CAM14" and
  buttons Compare / Use MAS_CAM14 / Keep MAS_CAM04.
- No stamp, no check (other brands). Sample a few photos per folder, not all.

## 4. Unknown or unlabelled camera

- The row reads "No camera with this name" or "not labelled yet", cannot be ticked, and has an **Open FlagLabel**
  button. The engine opens https://flaglabel.vercel.app/ (that URL only) in the default browser.

## 5. Flag photo by date, per photo

- Each photo uses its camera's usable flag photo with the latest capture time on or before the photo's.
  Photos before the first flag photo use the earliest one. Undated photos use the flag photo of the folder's
  first dated photo.
- The row shows the split: "19 Dec 2025 setup visit, 280 photos · 1 Apr 2026 service visit, 32 photos".
- The row's menu can override it with one flag photo for all of its photos.
- The run groups photos by flag photo (the reference is per call to the models).
- "Already measured / out of date" (`measure.current_answer`) compares against each photo's assigned flag photo.
- Single-folder mode stays as today: the user picks the flag photo.

## 6. Duplicates

- Two folders with the same photos (same file name and EXIF capture time), e.g. `MAS_CAM07` and
  `MAS_CAM07_filtered`: "MAS_CAM07_filtered has the same photos as MAS_CAM07. Measure only one." The smaller
  one stays ticked, the other is unticked.

## 7. The confirmation table

- Groups in this order: "Needs your attention", "Ready" (Tick all / Tick none), "Skipped".
- Columns: tick, Folder, Camera (menu), Flag photo chosen by date (menu), Photos, Check. Ready rows show
  "N already measured".
- Footer: "Measure N cameras · M photos", an estimated time, "K photos already measured are skipped", a "Redo
  measured photos too" checkbox, Cancel, and **Measure ticked**.
- Time: the recent measured seconds per photo if there is one, else about 1.9 s per photo (dept card).

## 8. Compare dialog

- One photo from the folder, the matched camera's flag photo and the suggested camera's flag photo, each with
  "Lines up well / Does not line up (N points)". Computed on demand with the RoMa alignment the run uses (about
  1.3 s each; needs the models). While they load, the images show with "Checking…". Buttons: Use X / Keep Y.

## 9. Running

- One queue over the ticked cameras, on the existing run machinery and cancel. One run at a time.
- Overall bar: "N of M photos · camera i of k", with time left. The current camera's row in full; finished
  cameras collapse into "Done: n cameras · deer · need a look" with Show; the rest "Waiting: n cameras".
- **Stop** keeps everything so far; choosing the folder again carries on (measured photos are skipped).

## 10. Done

- Per camera: photos, deer, median distance, needs a look, Open in Table.
- **Go to Results**, and **Review N photos that need a look** (opens TABLE filtered to needs-a-look rows until
  the review feature exists).
- A note listing what was not measured and why.

## 11. Results and Table

- A folder scope includes its subfolders (`report._in_folder`, `report.folder`), so RESULTS, DENSITY and TABLE
  answer for a site folder.

## Constraints

Supabase stays read-only (`supabase_ro.py` and the installer untouched). The engine does the matching, the dates
and the duplicate check; the page renders JSON and posts clicks. Copy short and plain, no em dashes; help in
helpText.ts.

## Tests

Matching (`MAS_CAM07_filtered`, "mas cam 2", MAS_CAM1 vs MAS_CAM14, ambiguous, nested, unknown, unlabelled); EXIF
stamp parsing and mismatch with PIL-written UserComment; flag photo by date (two visits, before the first,
undated); current_answer with assigned flag photos; the duplicate warning; the queue end to end on the fake
backend; folder scope including subfolders.
