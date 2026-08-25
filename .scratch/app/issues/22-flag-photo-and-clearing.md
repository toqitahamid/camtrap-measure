# 22 — The flag photo of the camera you are looking at, and a way to take a measurement back

**What to build:** The researcher, 2026-08-25: *"when i slect the diferent camera from the list and click
the flag photo button why dont it shows me the flags image. it oly shows me the flag image for the one
which i selected for to do the measurement"*, and *"i also need a clear option to clear the measurement
of all image from one camera or a individul image"*.

**Blocked by:** 16 — Photo review; 09 — Summary, gallery, export.

**Status:** done (2026-08-25) — 235 tests green; both verified live against the real store, the clear
only on a camera with nothing measured so no real result was destroyed to prove it works.

## The flag photo fault

Reproduced before anything was changed:

```
/api/flag?site=MAS_CAM01&image=IMG_2868.JPG  -> 200
/api/flag?site=MAS_CAM02&image=IMG_2868.JPG  -> 404
```

`Measure.tsx` built that URL out of two different sources: the **camera from the dropdown**, and the
**flag photo's name from the displayed photo's own record**. They agree only while the selected camera
is the one the photo was measured under. Choose another and the window asks for one camera's flag under
another camera's name — the engine refuses it, correctly, and an `<img>` whose request 404s renders
nothing at all. Silence, not an error.

The listing had no way to fix it: `report.folder` reported `flag_image` but never which camera it
belonged to. It now reports `flag_site` beside it, and the two travel together — the window asks for the
pair that was actually measured, whatever the dropdown says.

The same mistake was one line further down: the panel's **Camera** row also read the dropdown, so a
measured photo could be labelled with a camera that had nothing to do with it. It now names the camera
the number was read under.

## Clearing

A re-measure could replace an answer but nothing could take one away, so a wrong flag photo or a folder
measured under the wrong camera left numbers on record with no remedy but editing the database by hand.

`store.clear_measurements(site=... | path=...)` removes the photo rows and their detections and returns
what it removed. **Only the app's own answers go.** The photos on disk are untouched, and so is
everything synced from FlagLabel — cameras, annotations, calibrations, cached flag photos — because
those are not this app's to delete and re-measuring needs every one of them. A test asserts exactly
that, because it is the kind of thing a later refactor breaks quietly.

Guards, each with a test:

- **Neither argument is refused**, not treated as "everything": that would empty the store, which no
  button asks for and nobody would mean by "clear this camera". Both together is refused as a
  contradiction.
- **A run in progress is refused (409)** — deleting rows a running job is still writing is a race with
  the store as the loser.
- **Clearing nothing is not an error**: a camera with no measurements answers `0`, it does not fail.
- A cleared photo is **measured again** by the next run rather than skipped as current.

## In the window

Two buttons, both two-click rather than modal — the window has no dialog of its own, and a browser
`confirm()` blocks the whole WebView until it is answered.

- **One photo**: under *Measure … again* in the measurement panel, shown only for a photo that has an
  answer to clear.
- **One camera**: at the foot of the Export card in Results, where a reviewer is already looking at a
  camera's numbers and deciding they are wrong.

The camera button clears the **camera**, never the filters above it. A date range or a species tick is a
way of looking, not a way of choosing what to delete, and a button that quietly meant "the 43 rows
currently on screen" would be the wrong button.
