"""The app's own icon on its window, its taskbar button and Alt-Tab.

A window opened by pywebview wears the icon of the executable that opened it, which is a generic Python
one. The shortcut can carry the app's icon, but the running window then looks like something else.

pywebview's WinForms form sets its `Icon` property in its constructor: from `webview.start(icon=...)` when
given, else from python.exe. WinForms re-sends that property to the window whenever it needs to, so the
property itself must be ours. An icon sent to the window from outside (WM_SETICON by title, the first
attempt) landed as soon as the window existed, and the constructor then put Python's back a moment later
(seen 2026-09-25: the taskbar showed the Python logo and nothing was logged). So `main` passes the icon to
`webview.start`, and `apply` sets the form's own property again once the window is shown, on its GUI
thread: that also covers a pywebview that ignores the argument.

The process is given an explicit application identity first, which is what Windows groups and pins taskbar
buttons by; the installer stamps the same identity on its shortcuts.

Both are cosmetic and best-effort: they must never stop the app starting. Neither swallows its failure
either: each returns the reason in plain words, and `main` writes it to the launcher's log.
"""

import ctypes
import sys
from pathlib import Path

ICON = Path(__file__).parent / "assets" / "camtrap-measure.ico"
TITLE = "CamTrap Measure"  # the window title main.py opens with; the launcher finds the window by it
APP_ID = "SIU.CamTrapMeasure"  # taskbar identity: install.ps1 puts the same string on its shortcuts


def identify(app_id: str = APP_ID) -> str | None:
    """Name this process to Windows before any window exists. Returns None, or why it could not."""
    if sys.platform != "win32":
        return "not Windows"
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except OSError as e:  # an old or locked-down shell32: the taskbar button is then grouped by executable
        return f"{type(e).__name__}: {e}"
    return None


def _load_icon(ico: Path):
    """The .ico as a .NET System.Drawing.Icon (pythonnet is loaded by pywebview's WinForms backend)."""
    from System.Drawing import Icon

    return Icon(str(ico))


def _on_gui_thread(form, fn) -> None:
    """Run `fn` on the thread that owns `form`: WinForms properties may only be set from there."""
    from System import Action

    form.Invoke(Action(fn))


def apply(window, ico: Path = ICON, wait: float = 60.0, load_icon=_load_icon,
          on_gui_thread=_on_gui_thread) -> str | None:
    """Make `ico` the icon of pywebview `window`'s own form, once it is shown (up to `wait` seconds).

    Uses the form itself, not a window found by title, so a second copy of the app cannot be mistaken
    for this one. Returns None when the icon is set, otherwise the reason in plain words.
    """
    if sys.platform != "win32":
        return "not Windows"
    if not ico.is_file():
        return f"no icon file at {ico}"
    if not window.events.shown.wait(wait):
        return f"the window was not shown within {wait:g}s"
    form = getattr(window, "native", None)
    if form is None or not hasattr(form, "Icon"):
        return f"the window has no WinForms form to set an icon on (got {type(form).__name__})"
    try:
        icon = load_icon(ico)

        def put() -> None:
            form.Icon = icon

        on_gui_thread(form, put)
    except Exception as e:  # a .NET exception arrives as a Python one through pythonnet
        return f"{type(e).__name__}: {e}"
    return None
