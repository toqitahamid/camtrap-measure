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
    assert "$LogCandidates = @(" in install
    detail = install.split("function Detail", 1)[1].split("\nfunction ", 1)[0]
    assert "Log $line" in detail  # every printed line, in the window and in -Console alike
    assert 'Log "== $msg"' in install  # and every step
    assert "Set-Content -Path $candidate" in install  # overwritten per run: the file is the last run only
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


def test_the_preflight_failure_points_at_the_list_and_the_log():
    """The one failure a dept user has actually hit. Its message box now lists the failed checks itself
    (see the message-box test below), and Fail adds the log's path to every failure."""
    install = text(SCRIPTS / "install.ps1")
    line = [l for l in install.splitlines() if "not ready yet" in l]
    assert len(line) == 1 and "listed below" in line[0]
    assert "$send = \"The full record is in $LogFile" in fail_body(install)


def test_the_token_never_reaches_the_log():
    """The log is fed from the details pane, and the token has never been written to the pane."""
    install = text(SCRIPTS / "install.ps1")
    ask = install.split("function Ask-Token", 1)[1].split("\nfunction ", 1)[0]
    assert "Detail" not in ask and "Log " not in ask
    assert "UseSystemPasswordChar = $true" in ask


def test_the_log_goes_where_a_person_can_be_told_to_look():
    """2026-09-25: the dept user found no log on the Desktop; the researcher asked for the root of a drive.
    The root of D: takes files from any signed-in user on the dept image. The root of C: takes new folders
    but not new files without an administrator (Authenticated Users hold AD there, not WD), so C: gets a
    folder. The Desktop and TEMP come last, for a machine without a writable D:."""
    install = text(SCRIPTS / "install.ps1")
    block = install.split("$LogCandidates = @(", 1)[1].split("\n)", 1)[0]
    lines = [l.strip() for l in block.strip().splitlines()]
    assert lines[0] == r'"D:\CamTrapMeasure-setup.log",'
    assert lines[1] == r'"C:\CamTrapMeasure-log\CamTrapMeasure-setup.log",'
    assert "Desktop" in lines[2] and "TEMP" in lines[3]
    assert "New-Item -ItemType Directory -Force -Path (Split-Path $candidate -Parent)" in install
    assert "foreach ($miss in $logMisses) { Detail $miss }" in install  # a fallback is never silent


def test_a_failure_shows_what_went_wrong_in_the_message_box():
    """2026-09-25, the researcher: show the error in the installer window, not only in the log. The failed
    checks and their fixes are collected as they reach the pane and printed in the message box itself."""
    install = text(SCRIPTS / "install.ps1")
    detail = install.split("function Detail", 1)[1].split("\nfunction ", 1)[0]
    assert "$trimmed.StartsWith($Cross)" in detail and "$trimmed.StartsWith($Arrow)" in detail
    assert "$Cross = [string][char]0x2717" in install and "$Arrow = [string][char]0x2192" in install
    body = fail_body(install)
    assert '"What went wrong:`r`n"' in body
    assert '::Show("$msg`r`n`r`n$found$send"' in body


def test_the_checks_output_is_read_as_utf8():
    """The pane showed each check mark as mojibake: Python's output was read in the ANSI code page."""
    install = text(SCRIPTS / "install.ps1")
    assert '$env:PYTHONUTF8 = "1"' in install
    run = install.split("function Run", 1)[1].split("\nfunction ", 1)[0]
    assert run.count("-Encoding UTF8") == 3
    assert "Get-Content $out -ErrorAction" not in run  # every read of the output names its encoding


# --- the install folder (ticket 24) ---------------------------------------------------------------

def test_the_installer_asks_where_in_a_dialog_with_a_folder_picker():
    """2026-09-25: a dept machine failed the 20 GB check with everything on C:. The researcher asked to pick
    the place at install time: a box to type in, a Browse button, and a live line saying where and how much room."""
    install = text(SCRIPTS / "install.ps1")
    dialog = install.split("function New-FolderDialog", 1)[1].split("\nfunction ", 1)[0]
    assert '"Where should $Name be installed?"' in dialog
    assert "New-Object System.Windows.Forms.FolderBrowserDialog" in dialog
    assert '$go.Text = "Install"' in dialog and '$stop.Text = "Cancel"' in dialog
    assert "add_TextChanged({ Show-Where })" in dialog  # the where-and-free-space line follows the typing
    where = install.split("function Where-Text", 1)[1].split("\nfunction ", 1)[0]
    assert "$MinFreeGB" in where and "Free-GB" in where  # a warning, not a stop
    assert "if (-not $Root) { exit 0 }" in install  # Cancel touches nothing
    ask = install.split("function Ask-Folder", 1)[1].split("\nfunction ", 1)[0]
    assert "Read-Host" in ask  # -Console asks too, Enter takes the suggestion


def test_the_question_comes_before_anything_is_written():
    """Cancel must leave nothing behind, so the question comes before the log and the main window."""
    install = text(SCRIPTS / "install.ps1")
    asked = install.index("$Root = Ask-Folder (Default-Parent)")
    assert asked < install.index("$Form = New-Object System.Windows.Forms.Form")
    assert asked < install.index("foreach ($candidate in $LogCandidates)")


def test_install_to_skips_the_question_and_camtrapmeasure_is_appended():
    install = text(SCRIPTS / "install.ps1")
    params = install.split("param(", 1)[1].split("\n)", 1)[0]
    assert "[string]$InstallTo" in params
    assert "$asked = if ($InstallTo) { $InstallTo } elseif ($env:CAMTRAP_INSTALL_DIR)" in install
    resolve = install.split("function Resolve-InstallRoot", 1)[1].split("\nfunction ", 1)[0]
    assert '-ieq "CamTrapMeasure") { return $p }' in resolve  # a folder already so named is used as it is
    assert 'return (Join-Path $p "CamTrapMeasure")' in resolve


def test_the_choice_is_proved_by_writing_a_file_there():
    """The root of C: takes new folders but not new files: only a real write answers the question."""
    probe = text(SCRIPTS / "install.ps1").split("function Test-InstallRoot", 1)[1].split("\nfunction ", 1)[0]
    assert "New-Item -ItemType Directory" in probe and "Set-Content -LiteralPath $probe" in probe
    assert "Remove-Item -LiteralPath $probe" in probe


def test_everything_big_goes_under_the_chosen_folder():
    install = text(SCRIPTS / "install.ps1")
    assert '$Dir = Join-Path $Root "app"' in install
    assert '"CAMTRAP_DATA_DIR"      = (Join-Path $Root "data")' in install
    assert '"UV_CACHE_DIR"          = (Join-Path $Root "uv-cache")' in install
    assert '"UV_PYTHON_INSTALL_DIR" = (Join-Path $Root "python")' in install


def test_the_folders_are_remembered_as_user_variables_and_the_launcher_reads_them():
    """No administrator: user scope only. Set in this process too, because step 7 starts the app from here;
    read back by the launcher itself, because Explorer may still hold the old environment."""
    install = text(SCRIPTS / "install.ps1")
    assert '[Environment]::SetEnvironmentVariable($n, $Layout[$n], "User")' in install
    assert 'Set-Item -Path "env:$n" -Value $Layout[$n]' in install
    assert '"Machine")' not in install
    launcher = text(SCRIPTS / "launcher.ps1")
    for name in ("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"):
        assert f'"{name}"' in launcher
    assert '[Environment]::GetEnvironmentVariable($n, "User")' in launcher
    assert launcher.index('GetEnvironmentVariable($n, "User")') < launcher.index('"sync", "--frozen"')


def test_a_repair_stays_where_the_app_already_is():
    """Never move a user's data: an install from before ticket 24 keeps its app and data where they are."""
    install = text(SCRIPTS / "install.ps1")
    assert "(Get-ItemProperty -Path $Key -ErrorAction Stop).InstallLocation" in install
    assert "if ($known -and (Test-Path -LiteralPath $known)) {\n    $Dir = $known" in install
    repair = install.split("if ($Repair) {", 1)[1].split("} else {", 1)[0]
    assert "SetEnvironmentVariable" not in repair and "Ask-Folder" not in repair


def test_the_data_folder_is_never_hardcoded_except_as_the_default():
    for name in ("install.ps1", "uninstall.ps1"):
        lines = [l for l in text(SCRIPTS / name).splitlines()
                 if ".camtrap-measure" in l and not l.lstrip().startswith("#") and "%USERPROFILE%" not in l]
        assert len(lines) == 1, (name, lines)
        assert "CAMTRAP_DATA_DIR" in lines[0] or "if (-not $Data)" in lines[0], (name, lines)


def test_the_uninstaller_finds_the_data_and_cleans_up_the_variables():
    uninstall = text(SCRIPTS / "uninstall.ps1")
    assert '$Data = [Environment]::GetEnvironmentVariable("CAMTRAP_DATA_DIR", "User")' in uninstall
    for sub in ('"uv-cache"', '"python"'):
        assert sub in uninstall  # software under R goes with the app, not with the data
    removed = uninstall.index("foreach ($p in $Software)")
    cleared = uninstall.index("[Environment]::SetEnvironmentVariable($n, $null, \"User\")")
    assert removed < cleared < uninstall.index("Also delete your measurements")  # only once the app is gone


def test_the_log_records_the_chosen_folder_and_its_free_space():
    install = text(SCRIPTS / "install.ps1")
    assert 'Fact "Install folder"' in install and 'Fact "Data folder"' in install
    assert "GB free on $([System.IO.Path]::GetPathRoot($path))" in install


def test_the_new_installer_code_is_ascii():
    """install.ps1 has no byte order mark, so PowerShell 5 reads it in the ANSI code page."""
    install = text(SCRIPTS / "install.ps1")
    start = install.index("# --- where it goes")
    end = install.index("$Ico = Join-Path $Dir")
    assert install[start:end].isascii()


def test_settings_apps_names_the_lab_as_publisher():
    """2026-09-25, the researcher: Settings > Apps shows the lab, not the whole university."""
    install = text(SCRIPTS / "install.ps1")
    assert 'New-ItemProperty -Path $Key -Name "Publisher" -Value "BASE Lab, SIU Carbondale"' in install
    assert "Southern Illinois University" not in install


def test_the_uninstaller_copy_knows_it_is_the_copy_by_a_flag_not_by_its_path():
    """2026-09-25: Uninstall in Settings did nothing. TEMP used the short 8.3 name SIU856~4 (account
    name over 8 characters) while the copy's $PSScriptRoot was the long form, so the path test said "not in
    TEMP", the copy tried to copy itself onto itself and died hidden. The first stage now passes -FromTemp."""
    un = text(SCRIPTS / "uninstall.ps1")
    assert "param([switch]$Yes, [switch]$FromTemp)" in un
    assert "if (-not $FromTemp) {" in un
    assert '$argv += "-FromTemp"' in un
    assert '-notlike "$env:TEMP*"' not in un
    assert "Nothing was removed." in un  # a copy with no marker stops instead of deleting its own folder


def test_every_installer_window_shows_itself_despite_the_hidden_start():
    """2026-09-25: INSTALL.bat did nothing. setup.vbs starts PowerShell hidden, Windows applied that to the
    first window shown, and since ticket 24 that is the folder question, a modal dialog nobody could see.
    Measured under the same hidden start: only an explicit ShowWindow as the window loads made it visible."""
    install = text(SCRIPTS / "install.ps1")
    assert "public static extern bool ShowWindow" in install
    assert "[CamTrap.Win]::ShowWindow($this.Handle, 5)" in install
    assert "Show-Now $box" in install and "Show-Now $Form" in install
    assert "$prime" not in install


def test_the_installer_uses_standard_windows_colours():
    """2026-09-25, the researcher: the dark installer was not readable. System colours only."""
    install = text(SCRIPTS / "install.ps1")
    assert "FromHtml" not in install
    assert "BackColor = [System.Drawing.ColorTranslator]" not in install
    assert "$Details.BackColor = [System.Drawing.SystemColors]::Window" in install
