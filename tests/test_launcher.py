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


def test_the_log_goes_in_the_install_folder():
    """2026-09-25, the researcher: "write the log inside the camtrap measure folder". R for an install made
    by ticket 24 or later, the app folder for an older one; the Desktop and TEMP come last."""
    install = text(SCRIPTS / "install.ps1")
    block = install.split("$LogCandidates = @(", 1)[1].split("\n)", 1)[0]
    lines = [l.strip() for l in block.strip().splitlines()]
    assert len(lines) == 3
    assert lines[0] == '(Join-Path $LogHome "CamTrapMeasure-setup.log"),'
    assert "Desktop" in lines[1] and "TEMP" in lines[2]
    assert "$LogHome = if ($Root) { $Root } else { $Dir }" in install
    assert r'"D:\CamTrapMeasure-setup.log"' not in install and "CamTrapMeasure-log" not in install
    # the folder is known first: the question, then the candidates, then the header
    assert install.index("$Root = Ask-Folder (Default-Parent)") < install.index("$LogCandidates = @(")
    assert install.index("$LogCandidates = @(") < install.index("foreach ($candidate in $LogCandidates)")
    # an old install's log sits in its clone: kept out of git, or the launcher stops updating a "changed" clone
    assert r'".git\info\exclude"' in install
    assert 'Add-Content -LiteralPath $gitExclude -Value "CamTrapMeasure-setup.log"' in install
    assert "$logParent = Split-Path $candidate -Parent" in install
    # a drive root (D:\) is never passed to New-Item: it fails there with "not of a legal form"
    assert "if (-not (Test-Path -LiteralPath $logParent)) {" in install
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
    """2026-09-25: a dept machine failed the free-space check with everything on C:. The researcher asked to pick
    the place at install time: a box to type in, a Browse button, and a live line saying where and how much room."""
    install = text(SCRIPTS / "install.ps1")
    dialog = install.split("function New-FolderDialog", 1)[1].split("\nfunction ", 1)[0]
    assert '"Where should $Name be installed?"' in dialog
    assert "New-Object System.Windows.Forms.FolderBrowserDialog" in dialog
    assert '$go.Text = "Install"' in dialog and '$stop.Text = "Cancel"' in dialog
    assert "add_TextChanged({ Show-Where })" in dialog  # the where-and-free-space line follows the typing
    where = install.split("function Where-Text", 1)[1].split("\nfunction ", 1)[0]
    assert "$NeedGB" in where and "Free-GB" in where  # a warning, not a stop
    assert "$NeedGB = 14" in install  # models 6.5 + PyTorch 6 + results 1 + base 0.3, as in preflight.py
    assert "if (-not $Root) { exit 0 }" in install  # Cancel touches nothing
    ask = install.split("function Ask-Folder", 1)[1].split("\nfunction ", 1)[0]
    assert "Read-Host" in ask  # -Console asks too, Enter takes the suggestion


def test_the_question_comes_before_anything_is_written():
    """Cancel must leave nothing behind, so the question comes before the log and the main window."""
    install = text(SCRIPTS / "install.ps1")
    asked = install.index("$Root = Ask-Folder (Default-Parent)")
    assert asked < install.index("$Form = New-MainForm")
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


def test_no_script_saves_an_environment_variable_for_the_whole_account():
    """2026-09-25: the three folders were saved as user variables and leaked into everything under the
    account; on a developer's PC, uv in the dev repo used the installed app's cache and Python. Now they are
    only ever set for a process. Clearing a leftover one (value $null) is the one user-scope write allowed."""
    import re
    for p in SCRIPTS.glob("*.ps1"):
        for line in text(p).splitlines():
            for m in re.finditer(r"SetEnvironmentVariable\((.*)\)", line):
                if '"User"' in m.group(1) or '"Machine"' in m.group(1):
                    assert ", $null, " in m.group(1), (p.name, line)
    install = text(SCRIPTS / "install.ps1")
    assert 'Set-Item -Path "env:$n" -Value $Layout[$n]' in install  # this process: its uv steps and step 7


def test_the_installer_writes_the_layout_file_outside_the_clone_without_a_bom():
    """In R, not in R\\app: an untracked file in the clone makes it look changed and stops its updates."""
    install = text(SCRIPTS / "install.ps1")
    assert '$LayoutFile = Join-Path $Root "camtrap-install.json"' in install
    assert "camtrap-install.json" not in install.split('$Dir = Join-Path $Root "app"', 1)[1].split("$LayoutFile", 1)[0]
    for key in ('"data"      = $Layout["CAMTRAP_DATA_DIR"]', '"uv_cache"  = $Layout["UV_CACHE_DIR"]',
                '"uv_python" = $Layout["UV_PYTHON_INSTALL_DIR"]'):
        assert key in install
    assert ("[IO.File]::WriteAllText($LayoutFile, ($saved | ConvertTo-Json), "
            "(New-Object System.Text.UTF8Encoding $false))") in install
    # written before any uv step, so a failure stops the install before anything big happens
    assert install.index("[IO.File]::WriteAllText($LayoutFile") < install.index('Run "uv" @("sync", "--frozen")')


def test_the_installer_removes_leftover_variables_only_inside_r_and_only_once_the_launcher_reads_the_file():
    """A rerun on an install made before the layout file: the variables go, but only after step 2 put a
    launcher there that reads the file (an older one, left by a failed update, still reads the variables)."""
    install = text(SCRIPTS / "install.ps1")
    after_update = install.split('Step "Getting the app into $Dir"', 1)[1].split("# --- 3. environment", 1)[0]
    assert '-Pattern "camtrap-install.json" -SimpleMatch' in after_update
    assert "if (Is-Inside $v $Root) {" in after_update
    assert '[Environment]::SetEnvironmentVariable($n, $null, "User")' in after_update
    before_update = install.split('Step "Getting the app into $Dir"', 1)[0]
    assert "SetEnvironmentVariable" not in before_update


def test_the_folder_question_suggests_a_known_install_from_the_file_or_the_registry():
    install = text(SCRIPTS / "install.ps1")
    find = install.split("function Find-KnownRoot", 1)[1].split("\nfunction ", 1)[0]
    assert "(Get-ItemProperty -Path $Key -ErrorAction Stop).InstallLocation" in find
    assert '(Join-Path $r "camtrap-install.json")' in find
    default = install.split("function Default-Parent", 1)[1].split("\nfunction ", 1)[0]
    assert "$before = Find-KnownRoot" in default
    assert "GetEnvironmentVariable" not in default


def launcher_layout(launcher: str) -> str:
    return launcher.split("# --- where the data and uv's folders are", 1)[1].split("# --- the splash", 1)[0]


def test_the_launcher_resolves_the_layout_file_then_leftover_variables_then_nothing():
    launcher = text(SCRIPTS / "launcher.ps1")
    block = launcher_layout(launcher)
    assert '$LayoutFile = Join-Path $InstallRoot "camtrap-install.json"' in block
    assert "$InstallRoot = Split-Path $Dir -Parent" in block
    # the order: not installed -> the file -> (only for R\app) the old variables -> nothing
    order = ["if (-not $IsInstalled) {", "elseif (Test-Path -LiteralPath $LayoutFile) {",
             '-ine "app") {', 'GetEnvironmentVariable($n, "User")', 'Log "layout: none (no $LayoutFile']
    at = [block.index(s) for s in order]
    assert at == sorted(at), at
    for name in ("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR"):
        assert f'"{name}"' in block
    # the old variables: only inside R, written to the file first, then removed; the process gets them
    assert "if (Is-Inside $v $InstallRoot) { $legacy[$n] = $v }" in block
    written = block.index("[IO.File]::WriteAllText($LayoutFile, ($out | ConvertTo-Json), "
                          "(New-Object System.Text.UTF8Encoding $false))")
    assert written < block.index('[Environment]::SetEnvironmentVariable($n, $null, "User")')
    assert 'Set-Item -Path "env:$n"' in block
    # never blocks the start, and says what it used
    assert "try {" in block and "} catch {" in block and "carrying on" in block and "Stop-With" not in block
    assert 'Log "layout: CAMTRAP_DATA_DIR=$env:CAMTRAP_DATA_DIR' in block
    # before any uv or git step
    assert launcher.index("# --- where the data and uv's folders are") < launcher.index('Capture "git"')
    assert launcher.index("# --- where the data and uv's folders are") < launcher.index('"sync", "--frozen"')


def test_only_the_installed_copy_has_its_layout_read_or_written():
    """A developer's run.bat in their own clone must never read, write or delete anything here."""
    launcher = text(SCRIPTS / "launcher.ps1")
    which = launcher.split("# --- which copy this is", 1)[1].split("# --- where the data", 1)[0]
    assert '"InstallLocation"' in which
    assert "GetFullPath($InstalledAt)" in which and "GetFullPath($Dir)" in which
    block = launcher_layout(launcher)
    assert block.index("if (-not $IsInstalled) {") < block.index("Test-Path -LiteralPath $LayoutFile")


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
    # the layout file first, then an old variable inside R, then the default
    read = uninstall.index("([IO.File]::ReadAllText($LayoutFile) | ConvertFrom-Json).data")
    legacy = uninstall.index("if (Is-Inside $v $Root) { $Data = $v }")
    default = uninstall.index('if (-not $Data) { $Data = Join-Path $env:USERPROFILE ".camtrap-measure" }')
    assert read < legacy < default
    assert '$LayoutFile = Join-Path $Root "camtrap-install.json"' in uninstall
    assert 'foreach ($sub in @("uv-cache", "python", "camtrap-install.json"))' in uninstall  # go with the app
    removed = uninstall.index("foreach ($p in $Software)")
    cleared = uninstall.index("[Environment]::SetEnvironmentVariable($n, $null, \"User\")")
    assert removed < cleared < uninstall.index("Also delete your measurements")  # only once the app is gone
    assert "if (Is-Inside $v $Root) {\n" in uninstall  # only the ones inside R


def test_the_uninstaller_copy_is_started_with_quoted_arguments():
    """A TEMP path with a space reached powershell.exe as two arguments: Start-Process quotes nothing."""
    uninstall = text(SCRIPTS / "uninstall.ps1")
    assert '$line = ($argv | ForEach-Object { Quote-Arg $_ }) -join " "' in uninstall
    assert "-ArgumentList $line" in uninstall and "-ArgumentList $argv" not in uninstall
    body = lambda s: s.split("function Quote-Arg(", 1)[1].split("\n}", 1)[0]
    assert body(uninstall) == body(text(SCRIPTS / "install.ps1"))  # the same rules, copied


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
    assert "Show-Now $box" in install and "Show-Now $form" in install
    assert "$prime" not in install


def test_the_installer_uses_standard_windows_colours():
    """2026-09-25, the researcher: the dark installer was not readable. System colours only."""
    install = text(SCRIPTS / "install.ps1")
    assert "FromHtml" not in install
    assert "BackColor = [System.Drawing.ColorTranslator]" not in install
    assert "$script:Details.BackColor = [System.Drawing.SystemColors]::Window" in install


def main_form(install: str) -> str:
    return install.split("function New-MainForm", 1)[1].split("\nfunction ", 1)[0]


def test_the_main_window_has_copy_log_and_open_log_folder():
    """2026-09-25, the researcher: a way to hand the pane over without selecting text in it."""
    install = text(SCRIPTS / "install.ps1")
    form = main_form(install)
    assert '$copy.Text = "Copy log"' in form and "[System.Windows.Forms.Clipboard]::SetText($script:Details.Text)" in form
    assert '$script:CopyButton.Text = "Copied"' in form
    assert "New-Object System.Windows.Forms.Timer" in form and "Start-Sleep" not in form  # the caption comes back by itself
    assert '$open.Text = "Open log folder"' in form and '"/select,`"$($script:LogFile)`""' in form
    assert "$open.Visible = $false" in form
    assert "if ($Form -and -not $script:LogOff) { $script:OpenLogButton.Visible = $true }" in install
    assert "Show-Now $form" in form  # the hidden start (see the test above)
    assert "BackColor = [System.Drawing.Color]" not in form and "ForeColor = [System.Drawing.Color]" not in form


def test_the_main_window_can_always_be_closed():
    """2026-09-25, the researcher, after a stopped run: "there should be a button to cancel or close this
    window". Cancel while steps run asks first and stops the running child; Close once stopped or done."""
    install = text(SCRIPTS / "install.ps1")
    form = main_form(install)
    assert '$close.Text = "Cancel"' in form
    assert "$form.add_FormClosing({ param($sender, $e) Confirm-Cancel $e })" in form  # the title-bar X too
    confirm = install.split("function Confirm-Cancel", 1)[1].split("\nfunction ", 1)[0]
    assert 'if ($script:Phase -ne "running") { return }' in confirm
    assert "Stop the installer? You can run it again later; finished steps are kept." in confirm
    assert "MessageBoxDefaultButton]::Button2" in confirm  # default No
    assert "$e.Cancel = $true" in confirm and 'Log "STOPPED: cancelled by the user"' in confirm
    assert confirm.index("Stop-Child") < confirm.index('$script:Phase = "cancelled"')
    stop = install.split("function Stop-Child", 1)[1].split("\nfunction ", 1)[0]
    assert "taskkill.exe /PID $child.Id /T /F" in stop and "Stop-Process -Id $child.Id -Force" in stop
    pump = install.split("function Pump", 1)[1].split("\n}", 1)[0]
    assert 'if ($script:Phase -eq "cancelled") { exit 1 }' in pump
    assert "$script:Child = $p" in install.split("function Run", 1)[1].split("\nfunction ", 1)[0]
    body = fail_body(install)
    assert '$script:Phase = "stopped"' in body and '$script:CloseButton.Text = "Close"' in body
    end = install.split("# --- 7. first start", 1)[1]
    assert '$script:Phase = "done"' in end and '$script:CloseButton.Text = "Close"' in end


def test_long_steps_keep_the_window_answering():
    """2026-09-25: the pane could not be scrolled during the 6.5 GB model copy. Everything long runs through
    Run, which pumps the window every 150 ms."""
    install = text(SCRIPTS / "install.ps1")
    tools = install.split("# --- 1. tools", 1)[1].split("# --- 2. the app", 1)[0]
    assert "Invoke-WebRequest -Uri $(Quote $MinGitUrl)" in tools and "-EncodedCommand" in tools
    assert "try { Invoke-WebRequest" not in tools and "\n    Expand-Archive" not in tools
    assert tools.count('(Run "powershell.exe"') == 3  # Git download, Git unzip, uv


def test_a_rerun_updates_the_app_it_already_downloaded():
    """2026-09-25: after the disk check was fixed and pushed, a rerun still ran the checks from the old
    download (the half-finished install on D:) and would have stopped the same way. The installer now
    fetches and switches like the launcher, and leaves a clone with local changes alone."""
    install = text(SCRIPTS / "install.ps1")
    step = install.split('Step "Getting the app into $Dir"', 1)[1].split("Set-Location $Dir", 1)[0]
    assert '"fetch", "--quiet", "--tags", "origin"' in step
    assert '"checkout", "--quiet", "--detach", $ref' in step
    assert "status --porcelain" in step and "not updating it" in step
    assert '"ref.txt"' in step


# --- developer files stay off department machines ------------------------------------------------

def sparse_patterns(script: str) -> str:
    line = next(l for l in script.splitlines() if l.startswith("$SparsePatterns = @("))
    return line


def test_both_scripts_leave_out_the_same_developer_files():
    """2026-09-25, the researcher: CLAUDE.md, CONTEXT.md, HANDOFF.md were on Seth's machine. One list, the
    same in both scripts and in the order given by hand on that machine, so the launcher finds it already set."""
    install = text(SCRIPTS / "install.ps1")
    launcher = text(SCRIPTS / "launcher.ps1")
    expected = ('$SparsePatterns = @("/*", "!/CLAUDE.md", "!/CONTEXT.md", "!/HANDOFF.md", "!/.scratch/", '
                '"!/.claude/")')
    assert sparse_patterns(install) == expected
    assert sparse_patterns(launcher) == expected
    assert install.count("$SparsePatterns = ") == 1 and launcher.count("$SparsePatterns = ") == 1


def test_the_installer_clones_without_a_checkout_then_goes_sparse():
    install = text(SCRIPTS / "install.ps1")
    step = install.split('Step "Getting the app into $Dir"', 1)[1].split("Set-Location $Dir", 1)[0]
    fresh = step.split("} else {\n    # Cloned without", 1)[1]
    clone = fresh.index('"clone", "--quiet", "--no-checkout", $Repo, $Dir')
    sparse = fresh.index('(@("sparse-checkout", "set", "--no-cone") + $SparsePatterns)')
    checkout = fresh.index('"checkout", "--quiet", "--detach", "origin/main"')
    assert clone < sparse < checkout
    # a repair: the files go before the local-changes check, so a clone made earlier loses them too
    repair = step.split("} else {\n    # Cloned without", 1)[0]
    assert repair.index("+ $SparsePatterns)") < repair.index("status --porcelain")


def test_the_launcher_goes_sparse_before_it_checks_for_local_changes():
    launcher = text(SCRIPTS / "launcher.ps1")
    sparse = launcher.index('(Step "git" (@("sparse-checkout", "set", "--no-cone") + $SparsePatterns))')
    assert launcher.index('Capture "git" @("sparse-checkout", "list")') < sparse
    assert sparse < launcher.index('Capture "git" @("status", "--porcelain")')
    block = launcher.split("# --- developer files stay off", 1)[1].split("$dirty = ", 1)[0]
    assert "try {" in block and "} catch {" in block and "carrying on" in block  # never blocks the start
    assert "if (-not $IsInstalled) {" in block  # a developer's clone is not the installed copy: left whole
    assert '"InstallLocation"' in launcher.split("# --- which copy this is", 1)[1].split("# --- where the data", 1)[0]
    assert "Stop-With" not in block


def test_both_scripts_are_ascii():
    """No byte order mark: PowerShell 5 reads them in the ANSI code page."""
    for name in ("install.ps1", "launcher.ps1", "uninstall.ps1"):
        raw = (SCRIPTS / name).read_bytes()
        assert raw.isascii(), name


def test_run_quotes_each_argument_by_the_windows_rules():
    """2026-09-25, Seth's machine: Start-Process joins its argument list unquoted, so the GPU check reached
    python as `-c import` and said PyTorch saw no GPU on an RTX 6000 Ada. Checked by running Run on python
    and git with spaces, quotes and trailing backslashes (CONTEXT, 2026-09-25)."""
    install = text(SCRIPTS / "install.ps1")
    run = install.split("function Run(", 1)[1].split("\nfunction ", 1)[0]
    assert '$line = (@($arguments) | ForEach-Object { Quote-Arg $_ }) -join " "' in run
    assert "-ArgumentList $line " in run and "-ArgumentList $arguments" not in run
    quote = install.split("function Quote-Arg(", 1)[1].split("\n}", 1)[0]
    assert "$a.StartsWith('\"') -and $a.EndsWith('\"')" in quote  # robocopy's pre-quoted paths pass as they are
    assert r"'\' * (2 * $slashes + 1)" in quote and r"'\' * (2 * $slashes)" in quote
    assert r'-ArgumentList (Quote-Arg (Join-Path $Dir "scripts\launch.vbs"))' in install


def test_config_json_is_written_without_a_byte_order_mark():
    """Set-Content -Encoding utf8 writes a BOM in PowerShell 5; the app's config reader failed on it."""
    install = text(SCRIPTS / "install.ps1")
    assert "Set-Content $cfg" not in install
    assert "[IO.File]::WriteAllText($cfg, ($conf | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))" in install
