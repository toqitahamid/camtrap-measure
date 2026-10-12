# 34 — The camera is set from the folder name

**The problem:** In one camera's folder (not a site folder) the Camera menu was never set from the folder. With no
pick the window used the first camera with a usable flag photo (`usable[0]`, e.g. MAS_CAM01), and
`measure.prepare` never compares folder and camera. A wrong camera gives a plausible wrong distance with no
warning: day photos line up to the wrong flag photo with about 54 to 276 points (the right camera: about 8,600 to
9,100; `batch.COMPARE_GOOD` notes), which passes `distance.MIN_INLIERS` = 15. The CSV then names the wrong camera.

**What was built:**

- `batch.folder_camera(folder, cameras)`: the one camera the folder's name names, else the nearest of the
  `DEPTH` (3) folders above it that names one (`MAS_CAM07\DCIM\100BMCIM` is MAS_CAM07). It reuses the site
  folder's matcher (`batch.matches` via the shared `batch._named`), so "mas cam 2" is MAS_CAM02 and MAS_CAM1 is
  never found in MAS_CAM12. None when no name fits, or when the nearest name that fits fits two cameras.
- `GET /api/site` answers a single folder with `{status: "single", camera}` (camera or null). The window already
  asks this for every folder, so no new endpoint. Old bundles ignore the extra field.
- Window: the Camera menu shows the camera picked by hand, else the named camera. With neither it shows
  *Pick a camera* and Measure all, the row buttons and *Measure this photo* stay disabled. The photos are still
  listed. A new folder forgets the hand pick and the name picks again. Flag-photo logic unchanged.
- Site folders: the menu is hidden there; a row's camera changes only where its name fitted two cameras (below).
- "Clear this measurement" stays enabled with no camera (`Measure` prop `clearBusy`).

**Lettered names (checked 2026-10-12):** FlagLabel has 167 cameras (`data/flaglabel_supabase` manifest, labels,
sites.json), none lettered. The field folders MAS_CAM10A/B/C, MAS_CAM12A/D/E and TON_CAM08A/B are deployments of
MAS_CAM10, MAS_CAM12 and TON_CAM08; research folder 62 mapped them by stripping the letter
(`re.match(r"^((MAS|TON)_CAM\d+)")`). `matches` finds MAS_CAM10 in "MAS_CAM10B" as whole words, so these folders
already gave their camera, in both modes. Added to `matches`: the most specific name wins (a camera found only
inside a longer camera's name at the same place is dropped), so a lettered FlagLabel camera, if one is ever added,
takes its own folder instead of making it ambiguous. A test against the old matcher proves that a name that fitted
none or one camera fits the same: site rows change only where they were ambiguous.

**Blocked by:** none.

**Status:** implemented, not committed (2026-10-12, branch `fix/camera-from-folder` from `main` at 6e15ed0; the
researcher approves commits). On the login node `tests/test_batch.py`, `test_api.py`, `test_measure.py` and
`test_report.py`: 95 passed, 1 skipped (8 new tests; 2 old assertions now expect the `camera` field). Frontend not type-checked or built
here (no Node on Delta): run `npm run build` on the lab PC and commit `src/camtrap_measure/ui/` with it.
