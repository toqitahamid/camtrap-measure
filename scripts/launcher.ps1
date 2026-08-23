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
#>
[CmdletBinding()]
param([switch]$Console, [switch]$NoUpdate, [switch]$NoStart)

$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $PSScriptRoot
$Icon = Join-Path $Dir "src\camtrap_measure\assets\camtrap-measure.ico"
$Exe = Join-Path $Dir ".venv\Scripts\camtrap-measure-app.exe"  # the pythonw entry point: it owns no console
$LogDir = Join-Path $Dir "logs"
$Log = Join-Path $LogDir "launcher.log"
$Title = "CamTrap Measure"        # the app window's title: what "is it already running?" looks for
$Splash = "Starting CamTrap Measure"  # never the same as $Title, or the splash answers that question
Set-Location $Dir
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ((Test-Path $Log) -and (Get-Item $Log).Length -gt 512KB) { Move-Item $Log "$Log.old" -Force }
"=== $(Get-Date -Format s) launcher start ($Dir) ===" | Add-Content $Log

function Log($msg) {
    "$(Get-Date -Format 'HH:mm:ss')  $msg" | Add-Content $Log
    if ($Console) { Write-Host $msg }
}

# --- the splash -------------------------------------------------------------------------------------
# WinForms is on every Windows 10/11; nothing is installed for this. Without a console there is no other
# way to say "something is happening", and a double-click that shows nothing for a minute reads as broken.
$Form = $null
$Status = $null
if (-not $Console) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()
    $Form = New-Object System.Windows.Forms.Form
    $Form.FormBorderStyle = "None"
    $Form.StartPosition = "CenterScreen"
    $Form.Size = New-Object System.Drawing.Size(420, 150)
    $Form.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#14171B")
    $Form.TopMost = $true
    $Form.Text = $Splash
    if (Test-Path $Icon) { $Form.Icon = New-Object System.Drawing.Icon($Icon) }
    $edge = [System.Drawing.ColorTranslator]::FromHtml("#2E343C")
    $Form.add_Paint({
        $pen = New-Object System.Drawing.Pen $edge
        $_.Graphics.DrawRectangle($pen, 0, 0, $Form.Width - 1, $Form.Height - 1)
        $pen.Dispose()
    }.GetNewClosure())

    $mark = New-Object System.Windows.Forms.Label
    $mark.Text = "CAMTRAP MEASURE"
    $mark.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 12)
    $mark.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#E8A13C")
    $mark.SetBounds(28, 34, 360, 26)
    $Form.Controls.Add($mark)

    $Status = New-Object System.Windows.Forms.Label
    $Status.Text = "Starting..."
    $Status.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $Status.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#C7CCD2")
    $Status.SetBounds(30, 66, 360, 20)
    $Form.Controls.Add($Status)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = "Marquee"
    $bar.MarqueeAnimationSpeed = 25
    $bar.SetBounds(30, 96, 360, 6)
    $Form.Controls.Add($bar)
    $Form.Show()
}

function Pump { if ($Form) { [System.Windows.Forms.Application]::DoEvents() } }

function Say($msg) {
    Log $msg
    if ($Status) { $Status.Text = $msg }
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

# --- running a step without a console window --------------------------------------------------------
# -NoNewWindow keeps Windows from giving the child a console of its own (this process has none to share),
# and the output goes to files that are folded into the log, so a failure is still readable afterwards.
function Step($exe, $arguments) {
    $out = Join-Path $LogDir "step.out"
    $err = Join-Path $LogDir "step.err"
    Log "> $exe $($arguments -join ' ')"
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
    Log "  exit $($p.ExitCode)"
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

# --- one app at a time ------------------------------------------------------------------------------
Add-Type -Namespace CamTrap -Name Win -MemberDefinition @"
[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr FindWindowW(string cls, string title);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
"@

$hwnd = [CamTrap.Win]::FindWindowW($null, $Title)
if ($hwnd -ne [IntPtr]::Zero) {
    # Double-clicking the icon again must not start a second engine: two of them would fight over the GPU.
    Log "already running - bringing the window forward"
    [CamTrap.Win]::ShowWindow($hwnd, 9) | Out-Null  # SW_RESTORE
    [CamTrap.Win]::SetForegroundWindow($hwnd) | Out-Null
    Close-Splash
    exit 0
}

# --- the update -------------------------------------------------------------------------------------
# The installer's portable Git and user-scope uv (the dept machines have no administrator); harmless when
# they are already elsewhere on the PATH.
$env:Path = "$env:LOCALAPPDATA\Programs\MinGit\cmd;$env:USERPROFILE\.local\bin;$env:Path"
$env:GIT_TERMINAL_PROMPT = "0"

$dirty = Capture "git" @("status", "--porcelain")
if ($dirty -and $dirty.Trim()) {
    Log "the clone has local changes - not updating it"  # a developer's tree, or a half-finished checkout
    $NoUpdate = $true
}

if (-not $NoUpdate) {
    $ref = "origin/main"
    $refFile = Join-Path $Dir "ref.txt"
    if (Test-Path $refFile) { $ref = (Get-Content $refFile -TotalCount 1).Trim() }
    $prev = Capture "git" @("rev-parse", "HEAD")
    if ($prev) { $prev = $prev.Trim() }

    Say "Checking for a newer version..."
    if ((Step "git" @("fetch", "--quiet", "--tags", "origin")) -ne 0) {
        Say "Offline - starting the version on this computer."
    } else {
        Say "Updating the app..."
        if ((Step "git" @("-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", $ref)) -ne 0) {
            Say "Could not switch to $ref - starting the version on this computer."
        } else {
            $now = Capture "git" @("rev-parse", "HEAD")
            if ($now -and $prev -and $now.Trim() -ne $prev) { Say "Installing what the new version needs..." }
            else { Say "Checking the app's software..." }
            if ((Step "uv" @("sync", "--frozen", "--extra", "inference")) -ne 0) {
                Say "The new version could not be installed - going back to the previous one..."
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

# --- start the app ----------------------------------------------------------------------------------
if ($NoStart) { Say "Ready (not starting the app)."; Close-Splash; exit 0 }
Say "Starting CamTrap Measure..."
if (-not (Test-Path $Exe)) {
    Stop-With "CamTrap Measure is not installed properly on this computer: $Exe is missing. Run the installer again."
}
# The generated entry point re-runs itself as pythonw, so the window belongs to a CHILD process and the
# handle on the one started here stays empty. The window is found by its title instead.
$app = Start-Process -FilePath $Exe -WorkingDirectory $Dir -PassThru `
                     -RedirectStandardOutput (Join-Path $LogDir "app.out") `
                     -RedirectStandardError (Join-Path $LogDir "app.err")
$null = $app.Handle  # so the exit code below is readable if it dies while starting

# The window appearing is what says the app started. The first start also downloads the weights, but that
# happens behind the window with its own progress. Ninety seconds is far past a normal start on a slow disk.
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Pump
    Start-Sleep -Milliseconds 200
    if ($app.HasExited) { break }
    if ([CamTrap.Win]::FindWindowW($null, $Title) -ne [IntPtr]::Zero) { break }
}
if ($app.HasExited -and $app.ExitCode -ne 0) {
    foreach ($f in @((Join-Path $LogDir "app.out"), (Join-Path $LogDir "app.err"))) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 0) { Get-Content $f | Add-Content $Log }
    }
    Stop-With ("CamTrap Measure stopped as it was starting (code $($app.ExitCode)). This usually means its " +
               "software needs installing again: run the installer.")
}
Log "app started (pid $($app.Id))"
Close-Splash
if ($Console) { $app.WaitForExit(); exit $app.ExitCode }
