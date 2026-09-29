"""Launcher: open the desktop window at once, then start the HTTP engine behind it.

The window comes first, with a small Starting page, because the engine's imports can take half a minute on a
cold disk right after an update (2026-09-29: about two minutes from the click to a window, with nothing on
screen, and the researcher clicked again). So nothing heavy is imported at module scope: `.api` and uvicorn
are imported inside `start_engine`, after the window exists.
"""

import argparse
import os
import socket
import sys
import threading
import time

_T0 = time.monotonic()  # when this process reached the launcher code: the timings below count from here

# How long the server may take to answer once the engine is imported. The import itself is not under this
# limit: on a cold disk it is the slow part, and it either finishes or raises. Measured on the dev PC
# (2026-09-29): the server is up 0.1 s after the import, warm; the installed app's cold start after an update
# ran about ten times slower than warm. Sixty seconds keeps a wide margin over both.
ENGINE_START_TIMEOUT = 60.0

# The window's first page, before the engine is up. Inline and in the app's own colours
# (frontend/src/index.css: --bg, --text, --dim, --amber, --line, --bad), so it needs no server and no files.
_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>CamTrap Measure</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #0e1013; color: #e8eaed;
               font-family: "Segoe UI", system-ui, sans-serif; cursor: default; user-select: none; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  .box {{ max-width: 520px; padding: 0 24px; text-align: center; }}
  .mark {{ color: {mark}; font-weight: 600; letter-spacing: .12em; font-size: 15px; }}
  .line {{ margin-top: 14px; font-size: 20px; }}
  .hint {{ margin-top: 8px; color: #a3abb5; font-size: 14px; line-height: 1.5; }}
  .bar {{ margin: 24px auto 0; width: 220px; height: 3px; background: #262b32; overflow: hidden;
          border-radius: 2px; }}
  .bar i {{ display: block; width: 40%; height: 100%; background: #e8a13c;
            animation: go 1.4s ease-in-out infinite; }}
  @keyframes go {{ from {{ transform: translateX(-100%); }} to {{ transform: translateX(250%); }} }}
</style></head>
<body><div class="box">
  <div class="mark">CAMTRAP MEASURE</div>
  <div class="line">{line}</div>
  <div class="hint">{hint}</div>
  {bar}
</div></body></html>
"""

STARTING_PAGE = _PAGE.format(
    mark="#e8a13c", line="Starting&hellip;", hint="This can take a few minutes after an update.",
    bar='<div class="bar"><i></i></div>',
)
FAILED_PAGE = _PAGE.format(
    mark="#e36a60", line="The app could not start.",
    hint="Close this window and open the app again. If it keeps happening, run the installer again. "
         "The details are in logs\\launcher.log in the app folder.",
    bar="",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _since(t: float) -> str:
    return f"{time.monotonic() - t:.1f} s"


def start_engine(port: int | None = None, timeout: float = ENGINE_START_TIMEOUT) -> str:
    """Import the engine, serve the API on localhost in a daemon thread; return its base URL.

    `timeout` covers the server coming up after the import, not the import (see ENGINE_START_TIMEOUT).
    """
    t = time.monotonic()
    import uvicorn

    from .api import app

    say(f"engine imported in {_since(t)} ({_since(_T0)} after start)")
    port = port or _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    up = time.monotonic()
    thread.start()
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("the engine stopped as it was starting")
        if time.monotonic() > up + timeout:
            raise RuntimeError(f"engine failed to start within {timeout:g}s")
        time.sleep(0.05)
    say(f"engine up in {_since(up)} ({_since(_T0)} after start)")
    return f"http://127.0.0.1:{port}"


def shutdown(exit_process=os._exit) -> None:
    """End the process when the window closes, so the GPU is handed back.

    The models hold a CUDA context worth gigabytes, and the driver only reclaims it when the process
    really dies — on a shared 8 GB card that is the difference between the next program running and
    not. Tearing a CUDA context down can hang on Windows, and the engine, the model loader and any
    run are all daemon threads that a clean interpreter exit would have to wait on, so this stops the
    run and then leaves hard. Nothing is buffered: the store commits and closes per photo, so at worst
    the photo in flight is unmeasured, which is what a cancel already means.
    """
    from . import measure

    measure.cancel()
    for _ in range(20):  # let the photo in flight finish writing its row; 2 s is one photo's worth
        if not (measure.current and measure.current["status"] == "running"):
            break
        time.sleep(0.1)
    exit_process(0)


def say(msg: str) -> None:
    """A line for whoever reads the logs: stderr, and the launcher's log when the launcher names it.

    The launcher sends stderr to logs\\app.err and only copies that into logs\\launcher.log when the app
    dies while starting, so a cosmetic failure in a running app would sit where nobody looks.
    """
    print(msg, file=sys.stderr, flush=True)
    log = os.environ.get("CAMTRAP_LAUNCHER_LOG")
    if not log:
        return
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  app: {msg}\n")
    except OSError as e:
        print(f"could not write to {log}: {e}", file=sys.stderr, flush=True)


def _wear_icon(window) -> None:
    """Set the app's icon on its window; waits for the window to be shown (see win_icon.apply)."""
    from . import win_icon

    why = win_icon.apply(window)
    if why:  # cosmetic, so it never stops the app - but it is said out loud, into the launcher's log
        say(f"window icon not set: {why}")


def _bring_up(window, engine=None, wear_icon=None) -> None:
    """Runs on its own thread once the GUI loop starts (pywebview gives it one).

    The window is already on screen with the Starting page. The engine starts only once the window is shown,
    so its imports, and the model loader it starts, do not compete with the window for the disk. Then the
    window goes to the engine's page, or to a page that says the app could not start.
    """
    engine, wear_icon = engine or start_engine, wear_icon or _wear_icon
    if window.events.shown.wait(60):
        say(f"window shown in {_since(_T0)}")
    else:
        say("the window was not shown within 60 s; starting the engine anyway")
    wear_icon(window)
    try:
        url = engine()
    except Exception as e:  # the window stays open to say so; the log gets the reason
        import traceback

        say(f"engine did not start: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        window.load_html(FAILED_PAGE)
        return
    window.load_url(url)


def run_window() -> None:
    """Open the desktop window at once with the Starting page, and bring the engine up behind it."""
    import webview  # imported late: needs a GUI toolkit (WebView2 on Windows)

    from . import dialogs, win_icon

    why = win_icon.identify()  # before the window exists: Windows reads this when it makes the taskbar button
    if why:
        say(f"application identity not set: {why}")
    webview.settings["ALLOW_DOWNLOADS"] = True  # the CSV export is a plain download link
    dialogs.window = webview.create_window(  # Browse… opens its dialog on this window
        win_icon.TITLE, html=STARTING_PAGE, width=1200, height=800, background_color="#0e1013"
    )
    # The icon given here is what the form is built with, before it is shown; _wear_icon sets it again.
    webview.start(_bring_up, (dialogs.window,), icon=str(win_icon.ICON))
    shutdown()  # webview.start() returns once the window is closed


def main() -> None:
    parser = argparse.ArgumentParser(prog="camtrap-measure")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="serve the API only, no desktop window (Linux dev / headless)",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="installer checks: GPU, disk, network, weights token, FlagLabel login; exit 1 if any hard check fails",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="with --preflight: ask nothing, check what is already stored (the installer's window has no console)",
    )
    args = parser.parse_args()
    if args.preflight:
        from . import preflight  # imports the engine lazily: this runs before the first launch

        raise SystemExit(preflight.run(prompt=False if args.no_prompt else None))
    if args.no_window:
        url = start_engine()
        print(f"CamTrap Measure engine at {url}  (Ctrl+C to stop)", flush=True)
        threading.Event().wait()
        return
    run_window()
