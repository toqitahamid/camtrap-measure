<#
  CamTrap Measure launcher.

  The desktop shortcut runs scripts\launch.vbs, which runs this with no console at all. It updates the
  app from the Git remote (what run.bat used to do), shows a splash while it works, and then starts the
  window. A failure ends in a dialog box with a way to the log, never in a black window nobody reads.

  Everything here keeps the promise the old launcher made: offline, or if anything about the update
  fails, the version already on this computer runs; if the new version's dependencies cannot be
  installed, the previous version is restored and run. Model weights are not part of it - the app
  fetches those itself through its weights manifest.

  Rollback: put a known-good tag on one line in ref.txt next to run.bat (e.g. v0.1.0). The app stays on
  that tag at every start until ref.txt is deleted.

  A checkout rewrites this very file while it runs. That is safe here and was not in run.bat: PowerShell
  parses a script whole before executing it, where cmd re-reads a .bat by byte offset.

    -Console   report to the console instead of the splash (what run.bat uses)
    -NoUpdate  skip the update (also skipped by itself in a clone with local changes)
    -NoStart   do everything except start the app - for checking an install
    -AfterPid  the app's "Restart now": wait for that process to end first, then start as usual

  Updates (2026-09-29): the app starts at once from what is on disk, and `git fetch` runs behind its window.
  A newer version found that way is written to logs\update-ready.json, which the app shows as a notice, and
  the NEXT start checks it out and installs it before the app starts. A checkout never runs while the app does.
#>
[CmdletBinding()]
param([switch]$Console, [switch]$NoUpdate, [switch]$NoStart, [int]$AfterPid = 0)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $PSScriptRoot
$Icon = Join-Path $Dir "src\camtrap_measure\assets\camtrap-measure.ico"
$Exe = Join-Path $Dir ".venv\Scripts\camtrap-measure-app.exe"  # the pythonw entry point: it owns no console
$LogDir = Join-Path $Dir "logs"
$Log = Join-Path $LogDir "launcher.log"
$UpdateFile = Join-Path $LogDir "update-ready.json"  # logs\ is ignored by git: it never makes the clone look changed
$Title = "CamTrap Measure"        # the app window's title: what "is it already running?" looks for
$Splash = "Starting CamTrap Measure"  # never the same as $Title, or the splash answers that question
Set-Location $Dir
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 512KB) { Move-Item $Log "$Log.old" -Force }
$T0 = Get-Date  # the click, near enough: the timings in the log count from here
"=== $(Get-Date -Format s) launcher start ($Dir) ===" | Add-Content $Log

function Log($msg) {
    "$(Get-Date -Format 'HH:mm:ss')  $msg" | Add-Content $Log
    if ($Console) { Write-Host $msg }
}

# --- windows, found and shown -----------------------------------------------------------------------
# One compile for every call into Windows below (about 0.15 s), before the splash, which needs ShowWindow.
Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
namespace CamTrap {
public static class Win {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string title);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    // Every VISIBLE top-level window titled exactly `title`, with the id of the process that owns it.
    public static List<KeyValuePair<IntPtr, int>> Visible(string title) {
        var found = new List<KeyValuePair<IntPtr, int>>();
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            if (!IsWindowVisible(h)) return true;
            var sb = new StringBuilder(256);
            GetWindowTextW(h, sb, sb.Capacity);
            if (sb.ToString() == title) {
                uint pid;
                GetWindowThreadProcessId(h, out pid);
                found.Add(new KeyValuePair<IntPtr, int>(h, (int)pid));
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
}
"@

function Tree-Ids($rootId) {
    # The process and everything it started, as a set of ids. The entry point re-runs itself as pythonw, and
    # that one again as the real Python, so the window belongs to a grandchild of the process started here.
    $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId)
    $ids = @{ [int]$rootId = $true }
    $grew = $true
    while ($grew) {
        $grew = $false
        foreach ($p in $all) {
            if ($ids.ContainsKey([int]$p.ParentProcessId) -and -not $ids.ContainsKey([int]$p.ProcessId)) {
                $ids[[int]$p.ProcessId] = $true
                $grew = $true
            }
        }
    }
    return $ids
}

function App-Window($rootId) {
    # The app's window is on screen: VISIBLE, titled exactly $Title, and owned by the process tree of $rootId.
    # On 2026-09-29 the launcher took some other window of that title for the app (FindWindowW also finds
    # hidden ones, and any copy's), closed the splash at once, and the app's own window came two minutes
    # later with nothing on screen in between. The process list is read only when such a window exists.
    $candidates = [CamTrap.Win]::Visible($Title)
    if ($candidates.Count -eq 0) { return [IntPtr]::Zero }
    try {
        $tree = Tree-Ids $rootId
    } catch {
        # A machine whose process list cannot be read still gets a start: any visible window of the title.
        if (-not $script:TreeFailed) { Log "could not read the process list ($($_.Exception.Message)) - any visible $Title window counts" }
        $script:TreeFailed = $true
        return $candidates[0].Key
    }
    foreach ($c in $candidates) { if ($tree.ContainsKey($c.Value)) { return $c.Key } }
    return [IntPtr]::Zero
}

function Bring-Forward($hwnd) {
    if ([CamTrap.Win]::IsIconic($hwnd)) { [CamTrap.Win]::ShowWindow($hwnd, 9) | Out-Null }  # SW_RESTORE, minimised only
    [CamTrap.Win]::SetForegroundWindow($hwnd) | Out-Null
}

# --- one launcher, one app --------------------------------------------------------------------------
# Double-clicking the icon again must not start a second engine (two would fight over the GPU), nor a second
# update of the same folder. A launcher that is still working holds this mutex until it ends; a second one
# brings that launcher's splash forward and leaves. A launcher that died holding it leaves it "abandoned",
# which Windows hands to the next one, so a crash never locks the app out.
$MutexName = "Local\CamTrapMeasure-launcher-" + ($Dir.ToLowerInvariant() -replace "[^a-z0-9]", "_")
$Mutex = New-Object System.Threading.Mutex($false, $MutexName)
$owned = $false
# "Restart now" waits a little: the launcher that started the app may still be finishing its background fetch.
$patience = 0
if ($AfterPid) { $patience = 30000 }
try { $owned = $Mutex.WaitOne($patience) } catch { $owned = $true }  # AbandonedMutexException: it is ours now
if (-not $owned) {
    Log "another launcher is starting the app - bringing its splash forward"
    # $null is marshalled as an EMPTY class name, which matches nothing; [NullString]::Value is a real NULL.
    $other = [CamTrap.Win]::FindWindowW([NullString]::Value, $Splash)
    if ($other -ne [IntPtr]::Zero) { Bring-Forward $other }
    exit 0
}

function Running-Apps {
    return @(Get-Process -Name "camtrap-measure-app" -ErrorAction SilentlyContinue |
             Where-Object { $_.Path -and $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) })
}

if ($AfterPid) {
    # The app asked for this start ("Restart now") and is closing itself; the update is applied only once it
    # has gone. Should it still be there after 30 s, the start below finds it running and changes nothing.
    Log "restart asked by the app (pid $AfterPid) - waiting for it to close"
    $until = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $until) {
        if (-not (Get-Process -Id $AfterPid -ErrorAction SilentlyContinue) -and (Running-Apps).Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    }
}

# The process, not the window, is the real answer: an app still starting has no window yet. The window is only
# how the running app is brought forward.
$running = Running-Apps
if ($running.Count -gt 0) {
    $hwnd = App-Window $running[0].Id
    if ($hwnd -ne [IntPtr]::Zero) {
        Log "already running (pid $($running[0].Id)) - bringing its window forward"
        Bring-Forward $hwnd
        exit 0
    }
    # Starting, or closing: a closed window goes at once, and the process can take seconds more to end (it hands
    # the GPU back). 2026-09-29 18:51: this read as "still starting", the process then ended, and the launcher
    # showed its failure box for an app that had run normally and been closed.
    Log "already running (pid $($running[0].Id)) but no window on screen - starting or closing; waiting to see which"
}

# --- the splash -------------------------------------------------------------------------------------
# WinForms is on every Windows 10/11; nothing is installed for this. Without a console there is no other way to
# say "something is happening", and a click that shows nothing for a minute reads as broken (2026-09-29: the
# researcher clicked twice and wrote "it dont show anything"). It comes up before anything else is done.
# System colours, like the installer. launch.vbs starts this process hidden, and Windows applies that to the
# first window it shows: the splash was built here since ticket 18 and never seen. Show-Now is the installer's
# answer (see install.ps1): an explicit ShowWindow as the window loads, then a moment of TopMost to bring it in
# front of whatever was on screen.
$E = [char]0x2026  # the ellipsis, as one character: this file is ASCII, with no byte order mark
$Form = $null
$Status = $null
if (-not $Console) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $Form = New-Object System.Windows.Forms.Form
    $Form.Text = $Splash
    $Form.FormBorderStyle = "FixedDialog"
    $Form.ControlBox = $false  # closing it would not stop the start, only hide it again
    $Form.StartPosition = "CenterScreen"
    $Form.ClientSize = New-Object System.Drawing.Size(400, 112)
    if (Test-Path $Icon) { $Form.Icon = New-Object System.Drawing.Icon($Icon) }
    $Form.add_Load({ [CamTrap.Win]::ShowWindow($this.Handle, 5) | Out-Null })  # SW_SHOW
    $Form.add_Shown({ $this.TopMost = $true; $this.Activate(); $this.TopMost = $false })

    $head = New-Object System.Windows.Forms.Label
    $head.Text = "Starting CamTrap Measure$E"
    $head.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 12)
    $head.ForeColor = [System.Drawing.SystemColors]::ControlText
    $head.SetBounds(24, 18, 352, 26)
    $Form.Controls.Add($head)

    $Status = New-Object System.Windows.Forms.Label
    $Status.Text = "Starting$E"
    $Status.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $Status.ForeColor = [System.Drawing.SystemColors]::ControlText
    $Status.SetBounds(26, 50, 352, 20)
    $Form.Controls.Add($Status)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = "Marquee"
    $bar.MarqueeAnimationSpeed = 25
    $bar.SetBounds(26, 80, 348, 10)
    $Form.Controls.Add($bar)
    $Form.Show()
    [System.Windows.Forms.Application]::DoEvents()  # Load and Shown run now
    Log "splash shown ($([Math]::Round(((Get-Date) - $T0).TotalSeconds, 1)) s after the launcher started)"
}

function Pump { if ($Form) { [System.Windows.Forms.Application]::DoEvents() } }

function Wait-Pumping($ms) {
    # a pause that keeps the splash answering (and its bar moving)
    $until = (Get-Date).AddMilliseconds($ms)
    do { Pump; Start-Sleep -Milliseconds 40 } while ((Get-Date) -lt $until)
}

function Say($msg, $status) {
    # $msg is for the log; $status, when given, is the splash's short line
    Log $msg
    if ($script:Status -and $status) { $script:Status.Text = $status }
    Pump
}

function Close-Splash {
    if ($script:Form) { $script:Form.Close(); $script:Form.Dispose(); $script:Form = $null }
}

function Stop-With($msg) {
    Log "STOPPED: $msg"
    Close-Splash
    if ($Console) {
        Write-Host "STOPPED: $msg" -ForegroundColor Red
        Read-Host "Press Enter to close" | Out-Null
    } else {
        $answer = [System.Windows.Forms.MessageBox]::Show(
            "$msg`r`n`r`nWould you like to see the technical details?", $Title,
            [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Error)
        if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) { Start-Process notepad.exe $Log }
    }
    exit 1
}

function Wait-ForApp($proc) {
    # Until the app's window is on screen: its handle. [IntPtr]::Zero when the app ended first, or after five
    # minutes without a window (the models load behind the window, so this is only ever the start itself).
    $from = Get-Date
    $slow = $false
    while ((Get-Date) -lt $from.AddMinutes(5)) {
        Wait-Pumping 250
        if ($proc.HasExited) { return [IntPtr]::Zero }
        $h = App-Window $proc.Id
        if ($h -ne [IntPtr]::Zero) { return $h }
        if (-not $slow -and (Get-Date) -gt $from.AddSeconds(20)) {
            Say "no window yet after 20 s" "Still starting. This can take a few minutes after an update."
            $slow = $true
        }
    }
    return [IntPtr]::Zero
}

function Seconds-Since($t) { return "$([Math]::Round(((Get-Date) - $t).TotalSeconds, 1)) s" }

if ($running.Count -gt 0) {
    # Not started by this launcher, so its end is never reported as a failure here: an app that was closed ends
    # like this too. No update while it runs. If it shows a window, that is the app; if it ends, this click
    # opens a new one, below, as a click on a closed app does.
    Say "waiting for the running app" "Starting$E"
    $hwnd = Wait-ForApp $running[0]
    if ($hwnd -ne [IntPtr]::Zero) {
        Log "app window showing ($(Seconds-Since $T0) after the click)"
        Bring-Forward $hwnd
        Close-Splash
        exit 0
    }
    if (-not $running[0].HasExited) {
        Log "no app window after 5 minutes - leaving it to finish starting"
        Close-Splash
        exit 0
    }
    Log "the running app ended (it was closing) - starting it again"
    $until = (Get-Date).AddSeconds(30)  # its other processes go with it; the update below must not run under them
    while ((Running-Apps).Count -gt 0 -and (Get-Date) -lt $until) { Wait-Pumping 200 }
    if ((Running-Apps).Count -gt 0) {
        Log "another copy is still running - not starting a second one"
        Close-Splash
        exit 0
    }
}

# --- which copy this is -----------------------------------------------------------------------------
# Settings > Apps registers one folder as the installed app. Only that copy has its layout read and its
# files trimmed below; for a developer who runs run.bat in their own clone, nothing here reads, writes or
# deletes anything.
$InstalledAt = $null
$IsInstalled = $false
try {
    $InstalledAt = (Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CamTrapMeasure" `
                                     -Name "InstallLocation" -ErrorAction SilentlyContinue).InstallLocation
    $IsInstalled = [bool]($InstalledAt -and
        [IO.Path]::GetFullPath($InstalledAt).TrimEnd("\") -eq [IO.Path]::GetFullPath($Dir).TrimEnd("\"))
} catch {
    Log "could not tell whether this is the installed copy ($($_.Exception.Message)) - treating it as not"
}

# --- where the data and uv's folders are ------------------------------------------------------------
# An install made by ticket 24 or later sits under one folder R: R\app (this clone), R\data, R\uv-cache and
# R\python. R\camtrap-install.json names the last three, and they are set here for this process only, before
# any uv or git step, so uv and the app inherit them. The file is in R, not in the clone: an untracked file
# there would make the clone look changed and stop its updates.
# They used to be saved as user environment variables, which every program of the Windows account then saw:
# on a developer's PC, uv in their own repo used the installed app's cache and Python, and their copy of the
# app its data (2026-09-25). An install from that time has the variables and no file; its first start with
# this launcher writes the file and removes exactly those variables (only ones pointing inside R). An install
# from before ticket 24 has neither and keeps the app's defaults (%USERPROFILE%\.camtrap-measure).
# Any failure is a log line and the start carries on.
$EnvNames = @("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR")
$LayoutKeys = @{ "CAMTRAP_DATA_DIR" = "data"; "UV_CACHE_DIR" = "uv_cache"; "UV_PYTHON_INSTALL_DIR" = "uv_python" }
$InstallRoot = Split-Path $Dir -Parent
$LayoutFile = Join-Path $InstallRoot "camtrap-install.json"

function Is-Inside($path, $root) {
    if (-not $path -or -not $root) { return $false }
    return ($path.TrimEnd("\") + "\").StartsWith($root.TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)
}

try {
    if (-not $IsInstalled) {
        Log "layout: not the installed copy ($InstalledAt) - the environment is left as it is"
    } elseif (Test-Path -LiteralPath $LayoutFile) {
        $saved = [IO.File]::ReadAllText($LayoutFile) | ConvertFrom-Json
        foreach ($n in $EnvNames) {
            $v = $saved.($LayoutKeys[$n])
            if ($v) { Set-Item -Path "env:$n" -Value $v }
        }
        Log "layout: from $LayoutFile"
    } elseif ([IO.Path]::GetFileName($Dir.TrimEnd("\")) -ine "app") {
        Log "layout: none (an install from before ticket 24 - the app's defaults)"
    } else {
        # An install made after ticket 24 but before the layout file: its folders are in user variables.
        $legacy = [ordered]@{}
        foreach ($n in $EnvNames) {
            $v = [Environment]::GetEnvironmentVariable($n, "User")
            if (Is-Inside $v $InstallRoot) { $legacy[$n] = $v }
        }
        if ($legacy.Count -eq 0) {
            Log "layout: none (no $LayoutFile and no user variables inside $InstallRoot - the app's defaults)"
        } else {
            $out = [ordered]@{}
            foreach ($n in $legacy.Keys) { $out[$LayoutKeys[$n]] = $legacy[$n] }
            # UTF-8 without a byte order mark, like config.json
            [IO.File]::WriteAllText($LayoutFile, ($out | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
            foreach ($n in $legacy.Keys) { Set-Item -Path "env:$n" -Value $legacy[$n] }
            Log "layout: from the user variables ($($legacy.Keys -join ', ')), now saved in $LayoutFile"
            # Only once the file is written: removed first, a failed write would lose the layout.
            foreach ($n in $legacy.Keys) {
                try {
                    [Environment]::SetEnvironmentVariable($n, $null, "User")
                    Log "layout: removed the user variable $n"
                } catch {
                    Log "layout: could not remove the user variable $n ($($_.Exception.Message)) - carrying on"
                }
            }
        }
    }
} catch {
    Log "layout: could not be read ($($_.Exception.Message)) - carrying on with the environment as it is"
}
Log "layout: CAMTRAP_DATA_DIR=$env:CAMTRAP_DATA_DIR; UV_CACHE_DIR=$env:UV_CACHE_DIR; UV_PYTHON_INSTALL_DIR=$env:UV_PYTHON_INSTALL_DIR"

# --- running a step without a console window --------------------------------------------------------
# -NoNewWindow keeps Windows from giving the child a console of its own (this process has none to share),
# and the output goes to files that are folded into the log, so a failure is still readable afterwards.
function Step($exe, $arguments) {
    $out = Join-Path $LogDir "step.out"
    $err = Join-Path $LogDir "step.err"
    Log "> $exe $($arguments -join ' ')"
    $t = Get-Date
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $Dir -NoNewWindow -PassThru `
                       -RedirectStandardOutput $out -RedirectStandardError $err
    # Touching .Handle keeps the process object's handle open; without it PowerShell can hand back
    # a null ExitCode when the child has already gone, and every step would read as a failure.
    $null = $p.Handle
    while (-not $p.HasExited) { Pump; Start-Sleep -Milliseconds 120 }
    foreach ($f in @($out, $err)) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) { Get-Content $f | Add-Content $Log }
        Remove-Item $f -ErrorAction SilentlyContinue
    }
    Log "  exit $($p.ExitCode) ($(Seconds-Since $t))"
    return $p.ExitCode
}

function Capture($exe, $arguments) {
    # for the one-line answers - a commit hash, a dirty working tree - where the value is the point
    $out = Join-Path $LogDir "capture.out"
    $err = Join-Path $LogDir "capture.err"
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $Dir -NoNewWindow -PassThru `
                       -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $p.Handle  # see Step: without this the exit code can come back null
    $p.WaitForExit()
    $text = ""
    if (Test-Path $out) { $text = Get-Content $out -Raw }
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { return $null }
    return $text
}

# --- the update -------------------------------------------------------------------------------------
# The installer's portable Git and user-scope uv (the dept machines have no administrator); harmless when
# they are already elsewhere on the PATH.
$env:Path = "$env:LOCALAPPDATA\Programs\MinGit\cmd;$env:USERPROFILE\.local\bin;$env:Path"
$env:GIT_TERMINAL_PROMPT = "0"

# --- developer files stay off this computer ---------------------------------------------------------
# The repo is public and the installer cloned it whole, so the developers' notes landed on department
# machines too (2026-09-25, the researcher: "i dont want him to see this files"). A sparse checkout leaves
# these paths out of the app folder; excluded files are not reported by `git status --porcelain`, even
# ones deleted by hand, so this runs BEFORE the local-changes check below and never makes a clean clone
# look changed. The same list, in the same order, is in install.ps1 (and was run by hand on one machine):
# a clone that already has exactly it is left alone. Any failure is logged and the start carries on.
# An install that gets this launcher through an update applies it at the start AFTER that update:
# PowerShell had already parsed the old launcher when the checkout rewrote this file.
# Only the installed copy ($IsInstalled, from the "InstallLocation" check above) is touched, so a
# developer's clone keeps its files.
$SparsePatterns = @("/*", "!/CLAUDE.md", "!/CONTEXT.md", "!/HANDOFF.md", "!/.scratch/", "!/.claude/")
try {
    if (-not $IsInstalled) {
        Log "not the installed copy ($InstalledAt) - leaving its files as they are"
    } else {
        $have = Capture "git" @("sparse-checkout", "list")  # $null when the clone is not sparse yet
        $haveList = @()
        if ($have) { $haveList = @($have -split "`r?`n" | Where-Object { $_ }) }
        if (($haveList -join "`n") -cne ($SparsePatterns -join "`n")) {
            if ((Step "git" (@("sparse-checkout", "set", "--no-cone") + $SparsePatterns)) -ne 0) {
                Log "could not leave the developer files out - carrying on"
            }
        }
    }
} catch {
    Log "could not leave the developer files out ($($_.Exception.Message)) - carrying on"
}

$dirty = Capture "git" @("status", "--porcelain")
if ($dirty -and $dirty.Trim()) {
    Log "the clone has local changes - not updating it"  # a developer's tree, or a half-finished checkout
    $NoUpdate = $true
}

$ref = "origin/main"
$refFile = Join-Path $Dir "ref.txt"
if (Test-Path $refFile) { $ref = (Get-Content $refFile -TotalCount 1).Trim() }

function Resolve-Ref {
    # the commit $ref names in what was fetched last time: no network, so it never slows a start
    $c = Capture "git" @("rev-parse", "--verify", "--quiet", "$ref^{commit}")
    if ($c) { return $c.Trim() }
    return $null
}

# The update found by the last start's background fetch is applied here, before the app starts: the app is not
# running (checked above), so nothing has the files open. What decides is $ref in the fetched refs against HEAD,
# not the file, so ref.txt keeps its rule: the app stays on that tag at every start until ref.txt is deleted.
if (-not $NoUpdate) {
    $prev = Capture "git" @("rev-parse", "HEAD")
    if ($prev) { $prev = $prev.Trim() }
    $target = Resolve-Ref
    if (-not $target) {
        Log "could not find $ref in what was fetched - starting the version on this computer"
    } elseif ($target -eq $prev) {
        Log "up to date with $ref ($($target.Substring(0, 10)))"
    } else {
        Say "Updating the app to $ref ($($target.Substring(0, 10)))..." "Updating$E"
        if ((Step "git" @("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", $target)) -ne 0) {
            Say "Could not switch to $ref - starting the version on this computer."
        } else {
            Say "Installing what the new version needs..."
            if ((Step "uv" @("sync", "--frozen", "--extra", "inference")) -ne 0) {
                Say "The new version could not be installed - going back to the previous one..." "Updating$E"
                if ($prev) {
                    Step "git" @("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", $prev) | Out-Null
                    if ((Step "uv" @("sync", "--frozen", "--offline", "--extra", "inference")) -ne 0) {
                        Stop-With ("CamTrap Measure could not be prepared to start. The update was undone, but the " +
                                   "previous version's software could not be restored either. Check the internet " +
                                   "connection and try again; if it keeps failing, run the installer again.")
                    }
                }
            }
        }
    }
}
# Whatever it said is settled now: applied, undone, or not for this copy. The fetch below writes it again.
Remove-Item -LiteralPath $UpdateFile -ErrorAction SilentlyContinue

function Start-Fetch {
    # `git fetch` only moves refs and adds objects; it never touches the files the running app uses
    Log "> git fetch --quiet --tags origin (in the background)"
    $p = Start-Process -FilePath "git" -ArgumentList @("fetch", "--quiet", "--tags", "origin") -WorkingDirectory $Dir `
                       -NoNewWindow -PassThru -RedirectStandardOutput (Join-Path $LogDir "fetch.out") `
                       -RedirectStandardError (Join-Path $LogDir "fetch.err")
    $null = $p.Handle  # see Step: without this the exit code can come back null
    return $p
}

function Finish-Fetch($p, $started) {
    # Offline, or anything else that goes wrong here, is a log line only: the app is already running.
    try {
        if (-not $p.WaitForExit(120000)) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Log "  background fetch still going after 120 s - stopped; no update check this time"
            return
        }
        $err = Join-Path $LogDir "fetch.err"
        if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) { Get-Content $err | Add-Content $Log }
        Remove-Item (Join-Path $LogDir "fetch.out"), $err -ErrorAction SilentlyContinue
        if ($p.ExitCode -ne 0) { Log "  background fetch: exit $($p.ExitCode) (offline?) - no update check this time"; return }
        Log "  background fetch: exit 0 ($(Seconds-Since $started))"
        $target = Resolve-Ref
        $head = Capture "git" @("rev-parse", "HEAD")
        if ($head) { $head = $head.Trim() }
        if (-not $target -or $target -eq $head) { Log "no newer version"; return }
        $describe = Capture "git" @("describe", "--tags", "--always", $target)
        if ($describe) { $describe = $describe.Trim() } else { $describe = $target.Substring(0, 10) }
        $found = [ordered]@{ commit = $target; describe = $describe; ref = $ref; found = (Get-Date -Format s) }
        # UTF-8 without a byte order mark, whole in one write: the app reads it while it runs
        [IO.File]::WriteAllText($UpdateFile, ($found | ConvertTo-Json), (New-Object System.Text.UTF8Encoding $false))
        Log "newer version found: $describe - it is installed at the next start"
    } catch {
        Log "  background update check failed ($($_.Exception.Message)) - carrying on"
    }
}

# --- start the app ----------------------------------------------------------------------------------
if ($NoStart) { Say "Ready (not starting the app)."; Close-Splash; exit 0 }
Say "Starting CamTrap Measure... ($(Seconds-Since $T0) after the click)" "Starting$E"
if (-not (Test-Path $Exe)) {
    Stop-With "CamTrap Measure is not installed properly on this computer: $Exe is missing. Run the installer again."
}
# The generated entry point re-runs itself as pythonw, so the window belongs to a CHILD process and the
# handle on the one started here stays empty. The window is found through the process tree instead (App-Window).
# The app's stderr goes to app.err, which is only copied here if it dies while starting; a problem it hits
# later (its icon, say) it writes straight into this log, which it finds through this variable. So do the
# app's own start-up timings: window shown, engine imported, engine up.
$env:CAMTRAP_LAUNCHER_LOG = $Log
# The app's "new version" notice reads this file; its "Restart now" runs the shortcut's launch.vbs again.
if (-not $NoUpdate) { $env:CAMTRAP_UPDATE_FILE = $UpdateFile }
$env:CAMTRAP_LAUNCH_VBS = Join-Path $PSScriptRoot "launch.vbs"
$started = Get-Date
$app = Start-Process -FilePath $Exe -WorkingDirectory $Dir -PassThru `
                     -RedirectStandardOutput (Join-Path $LogDir "app.out") `
                     -RedirectStandardError (Join-Path $LogDir "app.err")
$null = $app.Handle  # so the exit code below is readable if it dies while starting
Log "app started (pid $($app.Id))"
$fetch = $null
$fetchStarted = Get-Date
if (-not $NoUpdate) {
    try { $fetch = Start-Fetch } catch { Log "could not start the background fetch ($($_.Exception.Message)) - carrying on" }
}

# The app opens its window first, with a Starting page, and loads the engine behind it; the window being on
# screen is what says the app started. The splash stays until then, and says so if it takes a while.
$hwnd = Wait-ForApp $app
if ($hwnd -ne [IntPtr]::Zero) {
    Log "app window showing after $(Seconds-Since $started) ($(Seconds-Since $T0) after the click)"
    Bring-Forward $hwnd
} elseif ($app.HasExited) {
    foreach ($f in @((Join-Path $LogDir "app.out"), (Join-Path $LogDir "app.err"))) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) { Get-Content $f | Add-Content $Log }
    }
    Stop-With ("CamTrap Measure stopped as it was starting (code $($app.ExitCode)). This usually means its " +
               "software needs installing again: run the installer.")
} else {
    Log "no app window after 5 minutes - leaving it to finish starting"
}
Close-Splash
if ($fetch) { Finish-Fetch $fetch $fetchStarted }  # hidden, after the splash: the app is on screen by now
if ($Console) { $app.WaitForExit(); exit $app.ExitCode }
# A form was shown without a message loop of its own; ending the script explicitly is what makes
# the process go, rather than lingering with a closed window nobody can see.
exit 0
