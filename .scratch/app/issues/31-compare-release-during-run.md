# 31 — Compare can drop the models while a run is using them

**The problem:** `inference.alignment` (Compare's scores, via `api.site_compare` → `batch.compare`) ends with
`finally: release()` (inference.py:494-495). `Real.release` sets `_detect`, `_dist` and `sam3` to None and empties
torch's cache. `api._models_free` refuses Compare while a run is *already* running, but nothing stops a run from
*starting* while Compare is lining up (seconds, longer if it first loads RoMa). Then:

1. Compare's `measuring()` and the run's `detecting()` can both be on the card at once, which ticket 20 forbids
   (the detector and the distance models are never on the card together).
2. When Compare finishes, its `release()` drops the run's models. The run keeps its local `md` or `dist`, so
   nothing crashes, but that memory is no longer handed back by the run's own `release()`.
3. Any later `self.measuring()` or `self._sam3()` in the run loads a second copy. Under the precise method,
   `_precise` calls both per photo (inference.py:374 and `_sam3`), so a second RoMa + distance net + SAM3 (3.4
   GB) can sit beside the first. On the dept's 8 GB RTX 2060 SUPER that overflows into system memory (the 10x
   slow-down measured 2026-08-23) or runs out of memory.

The reverse order is covered: `_models_free` returns 409 to Compare while a run is running.

**What to build (to decide):** either `measure.start` / `batch.start` also refuse while `inference._aligning` is
held (a 409, like Compare gets), or Compare releases only what it loaded itself, and never while a run is
running. The first is one check per start route; the second keeps a run startable at any time.

**Not to be confused with** ticket 30's `distance._aligning` lock: that one serialises line-ups so their torch
draws do not interleave; it does not stop `release()`.

**Blocked by:** none. Found in review of ticket 30 (2026-10-10); deliberately not fixed on `fix/fixed-seed`.

**Status:** open.
