# 13 — UI design pass

**What to build:** The modern-UI requirement, applied once across all finished screens: a small design system (color/spacing/type tokens, bundled font — offline-safe), dark mode, polished progress and summary components, consistent layout. No behavior changes.

**Blocked by:** 09 — Summary, suspicious gallery, gated export.

**Status:** done (2026-08-20) — `frontend/src/index.css` tokens + bundled Inter; dark mode follows the OS; tests and `tsc`/`oxlint`/`vite build` green

- [x] Design tokens + bundled font; no network fetch at runtime
- [x] All screens restyled consistently (login, sync, cameras, run, summary, gallery, export; there is no settings screen)
- [x] Dark mode
- [x] No behavior or API changes; existing tests stay green
