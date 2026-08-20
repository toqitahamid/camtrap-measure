"""Launcher: start the HTTP engine in a thread, then open the desktop window."""

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="camtrap-measure")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="serve the API only, no desktop window (Linux dev / headless)",
    )
    args = parser.parse_args()
    url = start_engine()
    if args.no_window:
        print(f"CamTrap Measure engine at {url}  (Ctrl+C to stop)", flush=True)
        threading.Event().wait()
        return
    import webview  # imported late: needs a GUI toolkit (WebView2 on Windows)

    webview.create_window("CamTrap Measure", url, width=1200, height=800)
    webview.start()
