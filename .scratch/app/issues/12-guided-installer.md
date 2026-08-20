# 12 — Guided installer

**What to build:** A department technician stands the app up on a fresh Windows machine alone: an interactive script walks each step with preflight checks — GPU driver and CUDA visibility, disk space for weights, network reachability, Supabase login — and every failed check prints a plain-language fix. Ends with a desktop shortcut and a passing first health check.

**Blocked by:** 03 — Read-only sync and login; 06 — Weights and real detection; 11 — Auto-update launcher.

**Status:** ready-for-agent

- [ ] One-command entry point on a clean machine (installs uv, fetches app, creates launcher shortcut)
- [ ] Preflights: GPU/CUDA, disk space, network, login — each failure gives a fix in plain language, not a stack trace
- [ ] First-run weights download shown with progress
- [ ] Recipe verified end to end in a clean environment
- [ ] Install instructions in the README match the script
