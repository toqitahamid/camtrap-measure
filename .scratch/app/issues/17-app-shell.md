# 17 — The window becomes an app: rail, folder picker, measure one or all

**What to build:** The researcher's verdict on the scrolling page (2026-08-23): *"instead of writing the folder
dir location, i want to select the folder… instead of measuring all image at once, i want to have an option to
individually measure each image, and have an option to measure all image at once… professional apps are not
vertical and take all the space of the window."* Design settled on the canvas
(https://claude.ai/code/artifact/c45a02ab-37a5-4d4e-96f1-e2c7f6b5badb — direction A, "field instrument", with
direction C's icon rail and data grid): a full-window shell, nothing scrolls but the photo list and the table.

**Blocked by:** 16 — Check every measured photo.

**Status:** done (2026-08-23) - engine, shell and three sections built; 169 tests green; tsc/oxlint/vite clean; CONTEXT section added

## The shell

Six regions, top to bottom, left to right — no page scroll at any window size:

1. **Section rail** (62 px, full height) — MEASURE / TABLE / RESULTS, account at the foot.
2. **Title bar** (46 px) — wordmark, version, sync status, Sync.
3. **Context bar** (58 px) — camera · flag photo · **photo folder + Browse…** · method · Measure all.
   The same bar in every section: they all act on one camera, one flag photo, one folder.
4. **Work area** — per section (see below).
5. **Status bar** (28 px idle / 46 px running) — models, device, counts; during a run it is the progress strip.

Sections: **MEASURE** = photo list · frame with boxes · measurement panel. **TABLE** = the same photos as
sortable rows (file, time, species, distance, 90%, confidence, alignment, status) with tick boxes and a
preview pane. **RESULTS** = counts, histogram, per-camera table, CSV export.

## Engine contract (what the window may call)

```
POST /api/folder/pick   → {folder: str|null, reason: str|null}
        Native folder dialog through pywebview. folder=null with a reason when there is no native window
        (--no-window, a browser): the window then falls back to the typed path.

GET  /api/folder?path=&site=&flag=&method=
        → {folder, total, unreadable, rows: [Row]}
        EVERY JPEG in the folder, name order, each joined with its stored answer for THIS flag photo and
        method. A folder with no answers yet lists every file with measured=false — this is what the list
        and the table render before anything is measured.
        Row = {name, path, captured_at, measured, stale, match_score, method, flag_image,
               reasons: [str], detections: [Det]}
        Det = {idx, x1, y1, x2, y2, species, confidence, distance_m, q05_m, q95_m, method, match_score,
               reasons: [str]}
        stale=true: measured, but against another flag photo or an older annotation version.

POST /api/run {folder, site, flag, method, rerun, photos?: [str]}
        photos = absolute paths, a subset of the folder. Given, they are measured whatever they already
        hold (an explicit pick IS the intent to measure); omitted, the whole folder under the rerun rule.

GET  /api/photo?path=&size=thumb|full
        Serves a measured photo OR any JPEG directly inside a folder /api/folder has listed this session.

GET  /api/flag?site=&image=&size=      unchanged (ticket 16)
GET  /api/run, POST /api/run/cancel, /api/status, /api/cameras, /api/methods, /api/summary,
     /api/export.csv                    unchanged
```

`GET /api/photos` and `report.review` go: `/api/folder` is the same view, scoped to the folder the user
picked, which is what every section of the new window works on.

- [x] Engine: `dialogs.pick_folder` through pywebview, `GET /api/folder`, `POST /api/run {photos}`,
      `/api/photo` serving any JPEG in a folder the window has listed
- [x] Window: the shell (rail, title bar, context bar with Browse, run bar, status bar) and the three
      sections, each a file of its own; `ui.tsx` holds the engine's JSON as types and the shared formatters
- [x] `GET /api/photos` and `report.review` deleted - `/api/folder` is the same view, folder-scoped
- [x] 169 tests green; tsc/oxlint/vite clean; CONTEXT section written
