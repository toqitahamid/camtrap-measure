"""A new version waiting, and the restart that applies it.

The launcher starts the app at once from what is on disk and fetches in the background (2026-09-29). When the
fetch finds a newer version it writes a small JSON file, and the next launch checks it out and installs it
before the app starts. The launcher names that file, and its own launch.vbs, to the app through two variables
set for the app's process only:

- CAMTRAP_UPDATE_FILE: where the launcher writes {"commit", "describe", "ref", "found"}; absent = no update.
- CAMTRAP_LAUNCH_VBS: what the desktop shortcut runs; "Restart now" runs it again.

Started any other way (a developer's `camtrap-measure`), neither is set: no notice, no restart.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Windows process flags: the new launcher must outlive this process, which is about to end, and must not be
# killed with it. uv's entry point puts the app in a job object; breaking away from it is asked for, and a job
# that forbids it is retried without (the launcher then still waits for this process by its id).
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def waiting(path: str | None = None) -> dict:
    """{"ready": bool, "commit": str | None, "describe": str | None}: is a newer version fetched and waiting?"""
    path = path if path is not None else os.environ.get("CAMTRAP_UPDATE_FILE")
    none = {"ready": False, "commit": None, "describe": None}
    if not path:
        return none
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))  # PowerShell 5.1 may write a BOM
    except FileNotFoundError:
        return none
    except (OSError, ValueError) as e:  # a half-written file reads as "nothing yet"; the next poll sees it whole
        print(f"update file {path} not readable: {e}", file=sys.stderr, flush=True)
        return none
    commit = data.get("commit") if isinstance(data, dict) else None
    if not commit:
        return none
    return {"ready": True, "commit": commit, "describe": data.get("describe") or commit[:10]}


def can_restart() -> bool:
    vbs = os.environ.get("CAMTRAP_LAUNCH_VBS")
    return bool(vbs) and Path(vbs).is_file()


def relaunch(popen=subprocess.Popen) -> None:
    """Start the launcher again, told to wait for this process to end before it does anything.

    Raises RuntimeError when there is no launcher to start (the app was not started by it).
    """
    vbs = os.environ.get("CAMTRAP_LAUNCH_VBS")
    if not vbs or not Path(vbs).is_file():
        raise RuntimeError("This copy was not started from the desktop icon. Close it and open it again.")
    wscript = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wscript.exe"
    args = [str(wscript), vbs, "-AfterPid", str(os.getpid())]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        popen(args, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True)
    except OSError:  # the job forbids breaking away: wscript is then still a job member, see the docstring
        popen(args, creationflags=flags, close_fds=True)
