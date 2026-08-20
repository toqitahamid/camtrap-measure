# 02 — Walking skeleton

**What to build:** A department user double-clicks the launcher and a desktop window opens showing a page served by the local engine; the engine answers a health request the page displays. The complete tracer: launcher → uv-managed Python engine → HTTP API → built React page → pywebview window, plus a green API test harness.

**Blocked by:** None — can start immediately.

**Status:** done (Windows window run unverified — no Windows box here)

- [x] Launcher script starts the engine and opens the desktop window
- [x] Window shows the React page (built assets served by the engine, no dev server)
- [x] One API endpoint round-trips to the page (e.g. app version shown)
- [x] API test harness runs and passes on a machine with no GPU
- [ ] Works on Windows (WebView2) — needs a run of `run.bat` on the dept machine
- [x] Develops on Linux without the window (`uv run camtrap-measure --no-window`)

## Result

`run.bat` → `uv run camtrap-measure` → uvicorn thread on a free localhost port → pywebview window.
`GET /api/health` returns `{status, version}`; React page shows it. Built UI committed at
`src/camtrap_measure/ui/` so a fresh clone needs no Node. Tests: `uv run pytest` (3 tests,
TestClient + one real-HTTP engine start). Frontend typechecks via `tsc -b` in `npm run build`.
