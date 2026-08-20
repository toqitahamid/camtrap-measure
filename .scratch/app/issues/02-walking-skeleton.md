# 02 — Walking skeleton

**What to build:** A department user double-clicks the launcher and a desktop window opens showing a page served by the local engine; the engine answers a health request the page displays. The complete tracer: launcher → uv-managed Python engine → HTTP API → built React page → pywebview window, plus a green API test harness.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Launcher script starts the engine and opens the desktop window
- [ ] Window shows the React page (built assets served by the engine, no dev server)
- [ ] One API endpoint round-trips to the page (e.g. app version shown)
- [ ] API test harness runs and passes on a machine with no GPU
- [ ] Works on Windows (WebView2); develops on Linux without the window
