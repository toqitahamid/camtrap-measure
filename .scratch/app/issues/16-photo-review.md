# 16 — Check every measured photo, not just the summary

**What to build:** After the first real run the researcher compared the app with FlagLabel: *"i want a
similar or better ui, where i can individually verify and check the animal photo that i gave to get the
measure. not just a summary stat."* The suspicious-only gallery is replaced by a **Review** card that
lists every measured photo and shows one at a time: the frame with its detection boxes labelled
`species · distance`, a table of each box's distance, 90% interval, detector confidence and method, the
alignment score and the flag photo the numbers were read against (one click to see it). Arrow keys walk
the list; three views — All / With an animal / Needs a look. The suspicious rows keep their meaning:
they are marked, on the photo and on the box, and the export gate is unchanged.

**Blocked by:** 15 — Pick the flag photo, pick the folder, measure.

**Status:** done (2026-08-23) — backend, window and tests switched to the review; 155 tests green;
tsc/oxlint/vite clean; CONTEXT section added

- [x] `report.review()` — one entry per measured photo with its boxes, their numbers, and the reasons
      on both the photo and the box it belongs to; empty frames included
- [x] `GET /api/photos` replaces `GET /api/suspicious` (which showed only the suspicious ones);
      `report.suspicious` deleted
- [x] `GET /api/photo?size=thumb|full` (320 / 1600 px, cached) and `GET /api/flag?site=&image=` for
      the reference frame; both still serve nothing that is not in the store
- [x] Window: `ReviewPanel` — photo strip, frame with labelled boxes, per-detection table, flag-photo
      toggle, arrow-key navigation; the "Needs a look" gallery is gone
- [x] Tests rewritten to the review endpoint; CONTEXT records why the suspicious-only gallery lost
