# 05 — Measurement run on fake inference

**What to build:** A technician points the app at a photo folder named after a camera and runs a measurement: the folder is validated against the camera registry, each photo is matched by its EXIF timestamp to the right calibration window, photos without a valid window are held with a banner naming which flags to label, progress streams live, and one row per detected animal lands in the results database — with a rerun replacing prior rows. All through a faked inference boundary, so the whole app is demoable and testable without a GPU.

**Blocked by:** 04 — Calibration fit, windows, verdicts.

**Status:** ready-for-agent

- [ ] Inference boundary defined: photos in → detections out (box, species, confidence, distance, q05/q95, match score); fake implementation for tests
- [ ] Folder whose name matches no registered camera is refused with a clear message
- [ ] Photo → calibration window matched by folder camera + photo EXIF timestamp
- [ ] No valid window → photo held, banner names the flags to label first; held photos never get numbers
- [ ] Progress display with counts and time estimate during a run
- [ ] Results keyed by photo + detection + method; rerun replaces
- [ ] EXIF Make/Model stored per photo
- [ ] All rules asserted through API tests with the fake
