"""The app's own icon on its window, its taskbar button and Alt-Tab.

A window opened by pywebview wears the icon of the executable that opened it, which is a generic Python
one — the shortcut can carry the app's icon, but the running window then looks like something else. So
the icon is hung on the window itself once it exists, and the process is given an explicit application
identity first, which is what Windows groups and pins taskbar buttons by.

Both are cosmetic and best-effort: they must never stop the app starting. Neither swallows its failure
either — each returns the reason in plain words, and `main` writes it to stderr, which the launcher folds
into logs\\launcher.log.
"""

import ctypes
import sys
import time
from pathlib import Path

ICON = Path(__file__).parent / "assets" / "camtrap-measure.ico"
TITLE = "CamTrap Measure"  # the window title main.py opens with; FindWindowW matches on it
APP_ID = "SIU.CamTrapMeasure"  # taskbar identity: same string on the shortcut would let a pin group with it

WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010


def identify(app_id: str = APP_ID) -> str | None:
    """Name this process to Windows before any window exists. Returns None, or why it could not."""
    if sys.platform != "win32":
        return "not Windows"
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except OSError as e:  # an old or locked-down shell32: the taskbar button is then grouped by executable
        return f"{type(e).__name__}: {e}"
    return None


def apply(title: str = TITLE, ico: Path = ICON, wait: float = 10.0) -> str | None:
    """Hang `ico` on the window titled `title`, waiting up to `wait` seconds for it to appear.

    Returns None when both sizes are set, otherwise the reason in plain words.
    """
    if sys.platform != "win32":
        return "not Windows"
    if not ico.is_file():
        return f"no icon file at {ico}"

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_uint]
    user32.SendMessageW.restype = ctypes.c_void_p
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    # Handles are pointers: left as the default c_int they would be cut in half on 64-bit Windows.

    deadline = time.monotonic() + wait
    while True:
        hwnd = user32.FindWindowW(None, title)
        if hwnd or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    if not hwnd:
        return f"no window titled {title!r} appeared within {wait:g}s"

    for which, px in ((ICON_BIG, 32), (ICON_SMALL, 16)):  # the title bar takes 16, Alt-Tab and the taskbar 32
        handle = user32.LoadImageW(None, str(ico), IMAGE_ICON, px, px, LR_LOADFROMFILE)
        if not handle:
            return f"Windows could not read {ico}"
        user32.SendMessageW(hwnd, WM_SETICON, which, handle)
    return None
