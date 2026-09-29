# 26 — Export one file per site or per camera; say where unlabelled cameras get their flag photo

**What to build:** Seth (department) asked for two things; the researcher approved both on 2026-09-29.

1. The export as one file per site, or one file per camera, not only one combined file.
2. The status bar says "141/167 cameras labelled", and Seth asked where in the app to put the flag photos
   of the other cameras. They cannot go in through the app: flag photos are uploaded and marked in
   FlagLabel, and Sync brings them in. The app stays read-only toward Supabase, so the answer is to say so
   where he looks, not to add a way in.

**Blocked by:** 09 — Summary, gallery, export; 22 — Flag photo and clearing (done).

**Status:** done (2026-09-29) — 324 passed, 1 skipped (11 in tests/test_split_export.py: site derivation, the site column, one file per site and per camera into a tmp folder with the right rows, dates / species / needs-a-look / folder applied per file, " (2)" instead of overwriting, a missing folder refused, the site-level summary, Open folder only for a folder the split wrote to); `npm run build`, tsc and oxlint clean. Real engine on the workstation store: 141/167 cameras labelled, 26 listed as "not labelled yet"; split by camera wrote `camtrap-measure_MAS_CAM01_start_end.csv` (11 rows) and `..._MAS_CAM04_...` (27); split by site wrote `camtrap-measure_MAS_start_end.csv` (38 rows), and again as `... (2).csv`. Screenshots of the Results export choice, the site filter, "Saved 1 file to ...", and the Camera list, from headless Edge.

## Sites

Camera names are SITE_CAMnn. The dept has 5 sites: MAS, MOR, SHB, SRF and TON. The site is the part before
the last "_CAM"; a name with no "_CAM" is its own site. One small, tested function says this
(`report.site_of`), and everything else asks it.

## 1. The split export

- The export CSV gets a `site` column next to `camera`, documented in the header lines.
- RESULTS gets an export choice: "All combined (one file)", "One file per site", "One file per camera".
  - All combined is the current download link, unchanged.
  - The other two open the native folder chooser (as Browse does); the engine then writes one CSV per site
    or camera into that folder, named like the combined file: `camtrap-measure_MAS_<from>_<to>.csv`,
    `camtrap-measure_MAS_CAM01_<from>_<to>.csv`.
  - Each file has the same header lines and the same filters as the screen: dates, species, the rows that
    need a look, the folder. Only a site or camera with rows to write gets a file.
  - Then the screen says "Saved N files to <folder>" with a button that opens the folder in Explorer.
  - An existing file is never overwritten silently.
- The Camera filter on RESULTS gets site entries ("MAS, all 31 cameras"), so the numbers on screen read at
  site level too. The same filter feeds the export.
- New endpoint: a POST that writes the split export into a folder and answers with the count and paths.

## 2. Cameras with no labelled flag photo

- The Camera list on MEASURE shows every camera. One with no usable flag photo is disabled and reads
  "not labelled yet"; hovering it, or its help, says "Label its flag photo in FlagLabel, then press Sync."
  Unlabelled means the same as the "labelled" count in the status bar: no flag photo with a usable
  calibration.
- The Camera, Flag photo and Sync help say where flag photos come from: added and marked in FlagLabel,
  then Sync. No web address is given unless one can be found for certain in the repos.
- Nothing here writes to Supabase; `supabase_ro.py` is untouched.

## Tests

Site derivation; the site column; the split writing one file per site and per camera into a tmp folder with
the right rows; the screen's filters applied per file; no file overwritten.
