# 25 — Distance sampling: deer density from the measured distances

**What to build:** Seth (department, 2026-09-28) asked for distance sampling. The app already has a distance
and a 90% interval for every deer; camera-trap distance sampling (CTDS; Howe et al. 2017, Methods Ecol Evol
8:1558) turns those into a density with a confidence interval. The researcher chose (2026-09-28): an in-app
estimate AND a CSV ready for R's `Distance` package; camera field of view and active days per camera,
prefilled and editable. How Seth's cameras trigger is not known yet, so the snapshot interval is an input.

**Blocked by:** 07/08 results store and the Results screen (done).

**Status:** done (2026-09-28) — 305 passed, 1 skipped (15 in tests/test_density.py: a simulated half-normal survey recovers the planted 3.0 deer/km² within 15%, hazard-rate fitted and chosen by AIC, truncation, a zero-deer camera in the effort, seeded interval); `npm run build` and oxlint clean; the real engine on the workstation store (37 of 38 deer, MAS_CAM01 + MAS_CAM04) shows hazard-rate, 7.6 deer/km², 90% range 6.1 to 11, P 0.606, radius 10.1 m, in about 4 s; screenshot of the DENSITY screen in Chrome.

## The screen

A fourth section, DENSITY, after RESULTS in the tab row. Same filter bar as Results (camera, captured
from/to); species is fixed to white-tailed deer, suspicious rows never enter.

Left, SURVEY SETUP:
- Snapshot interval, seconds (default 2). One line under it: "Time between photos in a burst or time-lapse.
  Check the camera settings."
- Truncation distance, metres (default: the 95th percentile of the distances, rounded up to the metre).
- Per camera table: camera, active days (prefilled from first to last photo of that camera, whole days),
  field of view in degrees (prefilled from a camera-model table only where the value is documented; else
  42 and marked "check"). Editable; saved locally.
- "Uses N of M deer": M deer rows in the filters, how many are beyond truncation, how many are suspicious.
- Button: Export for R Distance.

Right:
- DETECTION FUNCTION: histogram of distances (to w), scaled to the fitted pdf, with the fitted curve.
  Model name and its parameter; the chosen model's AIC against the other.
- DENSITY: deer per km² and a 90% interval; one small line "includes distance measurement error".
  Under it: detection probability P and effective detection radius.

Empty states: no deer measured; fewer than 20 deer after truncation ("too few for a density; 60 to 80 is
the usual minimum") still shows the numbers but warns.

## The method

- Point-transect detection function on distances r ≤ w: half-normal g = exp(-r²/2σ²) and hazard-rate
  g = 1 - exp(-(r/σ)^-b), fitted by maximum likelihood of f(r) = r g(r) / ∫0^w r g(r) dr; pick by AIC.
- P = 2 ∫0^w r g(r) dr / w².
- Effort per camera k: snapshot moments T_k / t (T_k active seconds) times θ_k / 2π.
- D = n / (π w² P Σ_k (T_k / t)(θ_k / 2π)), in /m², shown per km².
- Every photo in a camera's folder counts as one snapshot moment; each deer box is one animal. Availability
  is taken as 1 (said in the CSV header and help text).
- 90% interval: 1000 bootstraps resampling cameras with replacement (fewer than 3 cameras: resample deer),
  each deer's distance redrawn from Normal(distance, (q95 - q05) / 3.29), detection function refitted each
  time; percentile interval. Seeded, so the same inputs give the same interval.

## The R export

CSV in the `Distance` package's flat-file format, one row per deer within w, plus one row per camera with no
deer (distance NA) so its effort counts: Region.Label, Area, Sample.Label (camera), Effort (camera's
snapshot moments × θ/2π), object, distance, size (1), photo, timestamp. Header comment lines with the
snapshot interval, truncation, and how to call `ds(..., transect = "point")` then `dht2` with
`er_est = "P2"`. Verified against the package docs.

Checked against the docs (2026-09-28; distancesampling.org: the "camera trap distance sampling" vignette, the
`DuikerCameraTraps` and `dht2` reference pages). The columns, the NA row for a camera with no detections,
`ds(..., transect = "point")` and `dht2(..., er_est = "P2")` are as the ticket says. One difference, kept on
purpose: the package's example keeps **Effort = snapshot moments only** ("the number of 2-second time-steps over
which the camera operated") and passes the field of view as `sample_fraction = viewangle / 360` to `dht2`. This
file folds θ/360 into Effort instead, as the ticket says, because each camera may have its own lens; the header
says to leave `sample_fraction` at 1. The two give the same density when every camera shares one lens. `Area` is
0: `dht2` then reports density only. Units: `convert_units("meter", NULL, "square kilometer")`, as in the vignette.

## Follow-up (2026-09-28, later): the inputs from the images; one photo per snapshot moment

The researcher asked for the three survey inputs to come from the images, not from Seth. Done; each can still
be typed over. Details and reasons are in CONTEXT.md, "The survey inputs come from the images".
- Snapshot interval: the median gap between a camera's distinct capture seconds (gaps of 60 s or less, pooled),
  whole seconds, at least 1. Workstation: 3 s from 12 gaps.
- Active days: from the flag photo of the setup visit to the last photo in the camera's folders, fractional,
  cut by the date filter. Workstation: MAS_CAM01 33.79, MAS_CAM04 29.5.
- Field of view: 2 atan(cx / f) from the flag calibration fit. Workstation: 35.5 and 34.1 degrees.
- Bug fixed: every photo counted as a snapshot moment, so a three-shot burst counted its deer three times. Only
  the first photo of each t-second moment counts now, in the estimate and the R file.
- Live: 0.22 deer/km² (90% range 0.15 to 0.35) from 12 deer, down from 7.6 at one and two active days with
  every burst photo counted.
- 313 passed, 1 skipped.
