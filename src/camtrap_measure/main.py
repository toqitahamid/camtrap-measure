"""Launcher: start the HTTP engine in a thread, then open the desktop window."""

import argparse
import os
import socket
import threading
import time

import uvicorn

from .api import app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_engine(port: int | None = None) -> str:
    """Serve the API on localhost in a daemon thread; return its base URL."""
    port = port or _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("engine failed to start within 10s")
        time.sleep(0.05)
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
    args = parser.parse_args()
    if args.preflight:
        from . import preflight  # imports the engine lazily: this runs before the first launch

        raise SystemExit(preflight.run())
    url = start_engine()
    if args.no_window:
        print(f"CamTrap Measure engine at {url}  (Ctrl+C to stop)", flush=True)
        threading.Event().wait()
        return
    import webview  # imported late: needs a GUI toolkit (WebView2 on Windows)

    from . import dialogs

    webview.settings["ALLOW_DOWNLOADS"] = True  # the CSV export is a plain download link
    dialogs.window = webview.create_window("CamTrap Measure", url, width=1200, height=800)  # Browse… opens its dialog
    webview.start()
    shutdown()  # webview.start() returns once the window is closed
