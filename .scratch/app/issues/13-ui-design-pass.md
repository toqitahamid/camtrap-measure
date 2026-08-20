# 13 — UI design pass

**What to build:** The modern-UI requirement, applied once across all finished screens: a small design system (color/spacing/type tokens, bundled font — offline-safe), dark mode, polished progress and summary components, consistent layout. No behavior changes.

**Blocked by:** 09 — Summary, suspicious gallery, gated export.

**Status:** ready-for-agent

- [ ] Design tokens + bundled font; no network fetch at runtime
- [ ] All screens restyled consistently (login, sync, cameras, run, summary, gallery, export, settings)
- [ ] Dark mode
- [ ] No behavior or API changes; existing tests stay green
