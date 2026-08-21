# 12 — Guided installer

**What to build:** A department technician stands the app up on a fresh Windows machine alone: an interactive script walks each step with preflight checks — GPU driver and CUDA visibility, disk space for weights, network reachability, Supabase login — and every failed check prints a plain-language fix. Ends with a desktop shortcut and a passing first health check.

**Blocked by:** 03 — Read-only sync and login; 06 — Weights and real detection; 11 — Auto-update launcher.

**Status:** done except end-to-end verification (2026-08-20) — no Windows machine here; acceptance = first dept install following the README

- [x] One-command entry point on a clean machine (installs uv, fetches app, creates launcher shortcut)
- [x] Preflights: GPU/CUDA, disk space, network, login — each failure gives a fix in plain language, not a stack trace
- [x] First-run weights download shown with progress
- [ ] Recipe verified end to end in a clean environment — needs a Windows machine; the Python checks are unit-tested, the PowerShell is not
- [x] Install instructions in the README match the script
