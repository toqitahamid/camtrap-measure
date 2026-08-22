# 12 — Guided installer

**What to build:** A department technician stands the app up on a fresh Windows machine alone: an interactive script walks each step with preflight checks — GPU driver and CUDA visibility, disk space for weights, network reachability, Supabase login — and every failed check prints a plain-language fix. Ends with a desktop shortcut and a passing first health check.

**Blocked by:** 03 — Read-only sync and login; 06 — Weights and real detection; 11 — Auto-update launcher.

**Status:** done (2026-08-21) — ran on the Windows workstation; fixes: onnx/protobuf lock, Python 3.12 pin, no-admin Git+uv (CONTEXT "Windows acceptance"); only the real mailbox sign-in remains (ticket 14)

- [x] One-command entry point on a clean machine (installs uv, fetches app, creates launcher shortcut)
- [x] Preflights: GPU/CUDA, disk space, network, login — each failure gives a fix in plain language, not a stack trace
- [x] First-run weights download shown with progress
- [x] Recipe verified end to end on the Windows workstation (2026-08-21) — except the sign-in step, which needs a FlagLabel mailbox
- [x] Install instructions in the README match the script
