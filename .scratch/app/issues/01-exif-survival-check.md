# 01 — EXIF survival check

**What to build:** Verify that a flag photo uploaded through cloud FlagLabel to Supabase Storage still carries its EXIF capture date, so calibration validity windows can be keyed on it.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] One department-uploaded flag image downloaded from the private storage bucket
- [x] EXIF DateTimeOriginal present and plausible
- [x] Outcome recorded in CONTEXT.md; window design confirmed or fallback chosen

## Answer

Resolved 2026-08-20. SRF_CAM08/IMG_3792.JPG downloaded via signed URL: full 44-tag EXIF intact, DateTimeOriginal 2026-03-13 12:37:33, camera Browning BTC-7E, 1920x1080. Uploads preserve bytes verbatim. Windows key on EXIF as designed; no captured-at column needed. Bonus: store EXIF Make/Model per photo in results (free fleet inventory). Filename-order heuristic disproved (flag photo #3792, mid-sequence).
