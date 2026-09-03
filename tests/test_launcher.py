"""The app starts like an app: no console window, its own icon, one instance.

The desktop shortcut used to point at run.bat, so Windows opened a console for cmd.exe and left it there
for the whole session — closing it killed a run (reported 2026-08-23). These are the pieces that fixed
it, and each one is easy to undo by accident, so each is nailed down here.

The scripts themselves are PowerShell and VBScript: what can be asserted from pytest is their contract,
not their behaviour. The behaviour was checked by hand on the workstation (CONTEXT, ticket 18).
"""

import struct
import sys
import tomllib
from pathlib import Path

import pytest

from camtrap_measure import win_icon

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- no console anywhere -------------------------------------------------------------------------

def test_the_app_has_a_windowed_entry_point():
    """A [project.scripts] console executable is what put a black window behind the app."""
    meta = tomllib.loads(text(ROOT / "pyproject.toml"))
    assert meta["project"]["gui-scripts"] == {"camtrap-measure-app": "camtrap_measure.main:main"}


def test_the_shortcut_goes_through_wscript_not_the_batch_file():
    install = text(SCRIPTS / "install.ps1")
    assert "$Wscript = Join-Path $env:SystemRoot" in install
    assert "scripts\\launch.vbs" in install
    assert "run.bat" not in install  # a .lnk to a .bat is a console window, every time
    for line in install.splitlines():
        if line.strip().startswith("Shortcut ("):
            assert "$Wscript $launch" in line, line


def test_launch_vbs_starts_the_launcher_hidden():
    vbs = text(SCRIPTS / "launch.vbs")
    assert "launcher.ps1" in vbs
    assert "shell.Run ps & args, 0, False" in vbs  # 0 = hidden: no console, not even a flash


def test_the_installer_and_the_uninstaller_are_windowed_too():
    assert "install.ps1" in text(SCRIPTS / "setup.vbs")
    assert ", 0, False" in text(SCRIPTS / "setup.vbs")
    assert "uninstall.ps1" in text(SCRIPTS / "uninstall.vbs")
    assert "setup.vbs" in text(ROOT / "install.bat")


# --- what the launcher must keep doing ------------------------------------------------------------

def test_the_launcher_keeps_every_promise_the_batch_file_made():
    """Ticket 11's launcher rules moved into launcher.ps1; none of them may be lost on the way."""
    ps = text(SCRIPTS / "launcher.ps1")
    assert "ref.txt" in ps  # the rollback pin
    assert "origin/main" in ps
    assert "fetch" in ps and "Offline" in ps  # offline runs the version on this computer
    assert '"sync", "--frozen", "--extra", "inference"' in ps
    assert '"sync", "--frozen", "--offline", "--extra", "inference"' in ps  # the rollback's own sync
    assert "$null = $p.Handle" in ps  # or every step reads as a failure: PowerShell hands back a null code


def test_run_bat_only_delegates_now():
    """The update rewrote run.bat while cmd was reading it by byte offset. It no longer contains one."""
    bat = text(ROOT / "run.bat")
    body = [l for l in bat.splitlines() if l.strip() and not l.strip().lower().startswith("rem")]
    assert body[-1].startswith("powershell") and body[-1].endswith("& exit /b")
    assert "git " not in bat and "uv " not in bat


def test_one_app_at_a_time():
    ps = text(SCRIPTS / "launcher.ps1")
    assert "FindWindowW" in ps and "SetForegroundWindow" in ps


def test_the_uninstaller_removes_what_the_installer_made():
    install, uninstall = text(SCRIPTS / "install.ps1"), text(SCRIPTS / "uninstall.ps1")
    key = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\CamTrapMeasure"
    assert key in install and key in uninstall  # per-user: Settings > Apps without an administrator
    assert "uninstall.vbs" in install  # the UninstallString Windows will run
    assert 'GetFolderPath("Desktop")' in uninstall and 'GetFolderPath("Programs")' in uninstall
    assert ".camtrap-measure" in uninstall and "Answer No to keep them" in uninstall  # data is never assumed


# --- the icon ------------------------------------------------------------------------------------

def test_the_icon_ships_with_the_package_at_the_sizes_windows_asks_for():
    ico = win_icon.ICON
    assert ico.is_file() and ico.parent.parent.name == "camtrap_measure"  # inside the package, not beside it
    blob = ico.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    assert (reserved, kind) == (0, 1)  # a real .ico, not a renamed png
    sizes = {struct.unpack_from("<B", blob, 6 + 16 * i)[0] or 256 for i in range(count)}
    assert {16, 32, 48, 256} <= sizes  # the taskbar, the title bar, Alt-Tab and the big tile


def test_the_shortcut_and_the_window_use_the_same_icon():
    rel = "src\\camtrap_measure\\assets\\camtrap-measure.ico"
    assert rel in text(SCRIPTS / "install.ps1") and rel in text(SCRIPTS / "launcher.ps1")


def test_the_window_says_why_when_it_cannot_wear_its_icon():
    """Cosmetic, so it must not raise — but it must never fail silently either."""
    assert win_icon.apply(title="no window is called this", wait=0.05) is not None
    assert win_icon.apply(ico=ROOT / "nothing.ico", wait=0.05).startswith(("no icon file", "not Windows"))


@pytest.mark.skipif(sys.platform != "win32", reason="the taskbar identity is a Windows call")
def test_the_process_names_itself_to_windows():
    assert win_icon.identify() is None


def test_main_hangs_the_icon_once_the_window_exists():
    main = text(ROOT / "src" / "camtrap_measure" / "main.py")
    assert "win_icon.identify()" in main  # before the window: Windows reads it when making the taskbar button
    assert "webview.start(_wear_icon)" in main


def test_the_installer_never_asks_through_a_console_it_does_not_have():
    """A window has no stdin: `input()` in the checks raised EOFError before one was read (2026-08-23)."""
    install = text(SCRIPTS / "install.ps1")
    assert '"--preflight", "--no-prompt"' in install
    assert "Ask-Token" in install and "UseSystemPasswordChar = $true" in install  # the one thing it must ask
    main = text(ROOT / "src" / "camtrap_measure" / "main.py")
    assert '"--no-prompt"' in main and "prompt=False if args.no_prompt else None" in main


def test_the_splash_is_not_mistaken_for_the_app():
    """Both windows carried the title "CamTrap Measure", so the splash answered "is it already running?"
    - and the icon code would have dressed the splash instead of the app (2026-08-23)."""
    ps = text(SCRIPTS / "launcher.ps1")
    assert '$Splash = "Starting CamTrap Measure"' in ps
    assert "$Form.Text = $Splash" in ps
    assert win_icon.TITLE == "CamTrap Measure"


def test_the_launcher_waits_for_the_window_not_the_process_it_started():
    """The generated entry point re-runs itself as pythonw: the window belongs to a child process."""
    ps = text(SCRIPTS / "launcher.ps1")
    assert "if ((App-Window) -ne [IntPtr]::Zero) { break }" in ps
    assert "MainWindowHandle" not in ps


def test_the_launcher_log_folder_is_ignored():
    """An untracked logs/ made every install look like a modified clone, which stops its own updates."""
    ignored = [l.strip() for l in text(ROOT / ".gitignore").splitlines() if l.strip() and not l.startswith("#")]
    assert "logs/" in ignored  # exactly that, with no trailing comment: .gitignore has no inline comments


def test_the_running_app_is_found_by_its_process_and_a_real_null_class():
    """`$null` is marshalled as an EMPTY class name, so FindWindowW matched nothing and a second engine
    started on the workstation (2026-08-23). And during model loading there is no window to find at all."""
    ps = text(SCRIPTS / "launcher.ps1")
    assert "[NullString]::Value" in ps and "FindWindowW($null" not in ps
    assert 'Get-Process -Name "camtrap-measure-app"' in ps and "StartsWith($Dir" in ps
# --- the setup log (ticket 23) --------------------------------------------------------------------

def fail_body(install: str) -> str:
    """The body of `function Fail`, up to the next function."""
    return install.split("function Fail", 1)[1].split("\nfunction ", 1)[0]


def test_every_run_writes_the_details_pane_to_a_file():
    """A dept user hit the preflight failure on 2026-09-03 and could send nothing but a photograph of
    the message box: the pane went with the window. Both modes now write the same lines to a file."""
    install = text(SCRIPTS / "install.ps1")
    assert '$LogFile = Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrapMeasure-setup.log"' in install
    detail = install.split("function Detail", 1)[1].split("\nfunction ", 1)[0]
    assert "Log $line" in detail  # every printed line, in the window and in -Console alike
    assert 'Log "== $msg"' in install  # and every step
    assert "Set-Content -Path $LogFile" in install  # overwritten per run: the file is the last run only
    assert "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'" in install


def test_the_log_says_what_the_machine_is():
    """Nobody has written the department's hardware down; the log is where it gets recorded (HANDOFF
    open item 2). Each fact is asked for on its own so a failing query cannot stop an install."""
    install = text(SCRIPTS / "install.ps1")
    for query in ("Win32_OperatingSystem", "Win32_Processor", "Win32_ComputerSystem",
                  "Win32_VideoController", "Get-PSDrive -PSProvider FileSystem"):
        assert query in install, query
    fact = install.split("function Fact", 1)[1].split("\nDetail", 1)[0]
    assert "try { $value = & $get } catch" in fact and '$value = "unknown"' in fact


def test_a_failure_names_the_log_and_leaves_the_window_open():
    body = fail_body(text(SCRIPTS / "install.ps1"))
    assert "$LogFile - send that file to the researcher" in body  # the message box says where to look
    assert "[System.Windows.Forms.Application]::Run($Form)" in body  # ... and stays up to be read
    assert "$Form.Close()" not in body  # closing on OK is what lost the pane
    assert '$StepLabel.Text = "Stopped."' in body


def test_the_preflight_failure_names_the_log_too():
    """The one failure a dept user has actually hit, and the one whose answer is in the pane."""
    install = text(SCRIPTS / "install.ps1")
    line = [l for l in install.splitlines() if "not ready yet" in l]
    assert len(line) == 1 and "$LogFile" in line[0]


def test_the_token_never_reaches_the_log():
    """The log is fed from the details pane, and the token has never been written to the pane."""
    install = text(SCRIPTS / "install.ps1")
    ask = install.split("function Ask-Token", 1)[1].split("\nfunction ", 1)[0]
    assert "Detail" not in ask and "Log " not in ask
    assert "UseSystemPasswordChar = $true" in ask
