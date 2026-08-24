# 20 — The models load in stages, and the card is handed back afterwards

**What to build:** The researcher, 2026-08-23: *"istead of loaing all five models in the the vram, can we
split the model task. like first we will run megadetector/speciecnet for getting the bounding box and
the speciesname. and then we will do the measurement one by one. and when i measure a photo or multiple
photo, after the measurement is complete the vram of gpu or ram should be freed up. and for photos with
no animal the entire pipeline should skip"*.

**Blocked by:** 19 — research fidelity (this keeps its settings untouched).

**Status:** done (2026-08-23) — 216 tests green; verified end to end on the workstation: idle app holds
473 MiB (nothing), detector stage 1.4–3.3 GB, measuring stage up to 7.8 GB, back to 559 MiB the moment
the run finishes. 11 photos in 92 s against 117 s before.

## What changed

**Nothing is loaded until a run needs it.** Constructing the backend touches no weights, so the window
opens without waiting for 6 GB of models and an idle app holds no VRAM at all. `warmup()` now only
settles which backend and which weights version — 24 s, and none of it on the card.

**A run happens in two stages.** Stage one is MegaDetector and SpeciesNet: which photos hold an animal
and what it is. Those two then leave the card. Stage two is RoMa and the unified net, over only the
photos stage one found something in. Measured on the dept's 8 GB card: peak allocation during the
measuring stage is **6.26 GB with the detector released against 6.99 GB with it resident** — 0.73 GB of
headroom on the card where headroom is the whole game.

**A folder with no animals never loads the measuring models.** Not "skips the alignment" as before —
the 6 GB of weights are never read off disk. On a real card-dump, where most frames are empty, that is
the common case.

**When the run ends, both stages go.** `inference.release()` in the run's `finally`: references dropped,
`gc.collect()`, `torch.cuda.empty_cache()`. Verified to return the card to its baseline.

## What it costs

Every run reloads what it needs. Measured per stage on this machine: MegaDetector 14.4 s, SpeciesNet
3.1 s, RoMa + DINOv2 9.5 s, the unified net ~6.6 s warm (~19 s the first time in a process, most of it
`import transformers`). So a run pays roughly 20–35 s of loading before it measures anything, where
before it paid that once at startup. For a folder off an SD card that is nothing. For someone
re-measuring a single photo over and over it is the worse deal, and the honest trade of the request.

Unloading itself is free: ~80 ms for the drop plus `empty_cache`, reclaiming ~2.8 GB.

## Consequences elsewhere

- **Results now name their photo.** The stages finish photos out of order — an empty frame is done in
  stage one while a photo with a deer waits for stage two — so `PhotoResult` carries its `path` and the
  store files each answer by it. Zipping results against the photo list, as before, would now file
  every number under the wrong photo.
- **The run says which stage it is in** (`phase`, `phase_done`, `phase_total`), and the window shows it.
  "Finding animals 240/400" and "Measuring distances 3/12" are different waits, and without the label a
  long first pass looks like a hang.
- **The status line says what is resident**, from `inference.live()` rather than the warmup snapshot:
  "models unloaded — no GPU memory held" when idle. The claim is checkable on screen.
- The SpeciesNet batch size is not known until SpeciesNet has been loaded once, so `batch` is null until
  the first run.

## Not done

**RoMa's own `torch.cuda.empty_cache()`, once per photo inside `match()`.** Measured (2026-08-23):
removing it is ~11–13% faster (4.13/4.23 s per photo with it, 3.72/3.75 without), and about half of that
is the call itself at ~0.22 s per photo. It cannot change a number. It was left in place because the
measurement was taken with the card fully saturated — the regime RoMa put that call there to survive —
and 11% is not worth an out-of-memory on the tightest machine we have. **ponytail:** revisit on a card
with headroom, or once stage two's peak fits.
