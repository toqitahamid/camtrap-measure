<#
  CamTrap Measure installer for the department's Windows machines.

    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
    scripts\install.bat            (the same thing by double-click)
    install.ps1 -Console           the steps in the console instead of a window
    install.ps1 -InstallTo D:\     install there without asking (D:\ becomes D:\CamTrapMeasure)

  It runs in a window: the steps tick past, the details pane holds what each one printed, and a failure
  says what to do about it in plain words. Nothing here needs an administrator - the dept machines have
  none (2026-08-21): a portable Git in the user profile, uv's user-scope installer, the app in a folder
  the user picks, shortcuts, the Settings > Apps entry and the environment variables all per-user.

  Where it goes (ticket 24): first it asks where. The answer is a parent folder; everything goes in a
  CamTrapMeasure folder inside it (R): R\app is the app, R\data its models and results (CAMTRAP_DATA_DIR),
  R\uv-cache and R\python are uv's download cache and Python (UV_CACHE_DIR, UV_PYTHON_INSTALL_DIR). Those
  three are saved as user environment variables, which is how the launcher and the uninstaller find them.
  Only portable Git and uv.exe stay on C: (small). A machine that already has the app is repaired where it
  is, without the question: an install from before ticket 24 keeps its app in %LOCALAPPDATA%\CamTrapMeasure
  and its data in %USERPROFILE%\.camtrap-measure, untouched.

  Every run writes the same lines to D:\CamTrapMeasure-setup.log (else C:\CamTrapMeasure-log\, the
  Desktop, or TEMP, whichever can be written first), last run only, starting with
  a short description of the machine. A failure names that file and leaves the window open, so there is
  always something to read and something to send.

  Safe to run again: every step is a no-op when it is already done, so this is also the repair path.
#>
[CmdletBinding()]
param(
    [switch]$Console,
    # A folder of model weights to install instead of downloading them. Given this, the installer never
    # asks for a Hugging Face token and the app never contacts the hub: the department is handed the
    # models, not a credential. Defaults to a "weights" folder sitting beside this script, which is what
    # scripts\make_bundle.ps1 builds, so the bundle installs by double-click with no arguments.
    [string]$WeightsFrom,
    # Where to install, so the installer does not ask. A parent folder: D:\ becomes D:\CamTrapMeasure.
    # CAMTRAP_INSTALL_DIR in the environment does the same. Ignored when the app is already installed.
    [string]$InstallTo
)

$ErrorActionPreference = "Stop"
# The app's checks print check and cross marks. Python writes its output as UTF-8 and Run reads it back as UTF-8; before
# this the pane read it as the ANSI code page and showed each mark as three garbled characters (seen 2026-09-25).
$env:PYTHONUTF8 = "1"
# This file has no byte order mark, so PowerShell 5 would misread the marks as literals: build them instead.
$Cross = [string][char]0x2717
$Arrow = [string][char]0x2192
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest's progress bar slows downloads badly on PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "https://github.com/toqitahamid/camtrap-measure.git"
# Portable Git (MinGit: no installer, no registry, no admin). The launcher puts the same folder on the PATH.
$MinGitUrl = "https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/MinGit-2.51.0-64-bit.zip"
$MinGitDir = Join-Path $env:LOCALAPPDATA "Programs\MinGit"
$UvBin = Join-Path $env:USERPROFILE ".local\bin"  # where uv's installer puts uv.exe
$Name = "CamTrap Measure"
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CamTrapMeasure"
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
# The details pane goes with the window; this file is what a person can send afterwards. It goes where
# anyone can be told to look (2026-09-25: the Desktop copy was not found on a dept machine). First the root
# of D:, where the dept image lets any signed-in user write files. The root of C: does not (new folders
# only, no new files, without an administrator), hence a folder there next. The Desktop and TEMP are the
# last fallbacks, for a machine with no writable D:. The pane says which one was used.
$LogCandidates = @(
    "D:\CamTrapMeasure-setup.log",
    "C:\CamTrapMeasure-log\CamTrapMeasure-setup.log",
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrapMeasure-setup.log"),
    (Join-Path $env:TEMP "CamTrapMeasure-setup.log")
)
$LogFile = $LogCandidates[0]

# --- the window -------------------------------------------------------------------------------------
$Form = $null
$StepLabel = $null
$Details = $null
if (-not $Console) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        [System.Windows.Forms.Application]::EnableVisualStyles()
    } catch {
        $Console = $true  # a machine without WinForms still gets installed, just in the console
    }
}

# --- where it goes ----------------------------------------------------------------------------------
# 2026-09-25: a dept machine failed the 20 GB free-space check, because everything went on C: (the app and
# its environment in %LOCALAPPDATA%, 7 GB of models in the user profile, uv's cache). The researcher: "how
# about installing it on my chosen location that I select on the installing time". So the installer asks,
# and everything big goes under the one folder that was picked (see the header for the layout).
$MinFreeGB = 20  # preflight.MIN_FREE_GB: what the app's own disk check asks for
$LegacyDir = Join-Path $env:LOCALAPPDATA "CamTrapMeasure"  # where every install before ticket 24 put the app
$EnvNames = @("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR")
$Amber = if ($Console) { $null } else { [System.Drawing.ColorTranslator]::FromHtml("#E8A13C") }

function Resolve-InstallRoot($picked) {
    # The picked folder is a parent: D:\ becomes D:\CamTrapMeasure, and a folder already called
    # CamTrapMeasure is used as it is. $null when the answer is not a full path.
    if (-not $picked) { return $null }
    $p = [Environment]::ExpandEnvironmentVariables(([string]$picked).Trim().Trim('"').Trim())
    if ($p -match '^[A-Za-z]:$') { $p += "\" }
    if ($p -notmatch '^([A-Za-z]:\\|\\\\[^\\]+\\[^\\]+)') { return $null }
    try { $p = [System.IO.Path]::GetFullPath($p) } catch { return $null }
    if ($p.Length -gt 3) { $p = $p.TrimEnd("\") }
    if ([System.IO.Path]::GetFileName($p) -ieq "CamTrapMeasure") { return $p }
    return (Join-Path $p "CamTrapMeasure")
}

function Free-GB($path) {
    # Free space on the drive holding $path, in whole GB; $null when Windows will not say (a network path).
    try {
        $drive = New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot($path))
        return [int][Math]::Floor($drive.AvailableFreeSpace / 1GB)
    } catch { return $null }
}

function Test-InstallRoot($root) {
    # Makes the folder and writes a file in it: the only sure answer to "can this account install here?"
    # (the root of C: takes new folders but not new files). $null when it can, else why not, in words.
    $made = -not (Test-Path -LiteralPath $root)
    $probe = Join-Path $root "camtrap-write-test.tmp"
    try {
        New-Item -ItemType Directory -Force -Path $root -ErrorAction Stop | Out-Null
        Set-Content -LiteralPath $probe -Value "test" -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
        return $null
    } catch {
        $why = $_.Exception.Message
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
        if ($made) { try { [System.IO.Directory]::Delete($root, $false) } catch {} }  # only if empty: never a prompt
        return "Windows does not let this account save files in $root ($why)"
    }
}

function Where-Text($picked) {
    # The line under the folder box: where it will really go, and whether the drive has room. A warning,
    # never a stop: the checks later on say the same thing with more detail.
    $root = Resolve-InstallRoot $picked
    if (-not $root) { return @("Type a full folder path, like D:\", $true) }
    $free = Free-GB $root
    $drive = [System.IO.Path]::GetPathRoot($root)
    if ($null -eq $free) { return @("Installs into $root. Free space on that drive is unknown.", $false) }
    if ($free -lt $MinFreeGB) {
        return @("Installs into $root. Only $free GB free on $drive and it needs about $MinFreeGB GB.", $true)
    }
    return @("Installs into $root. $free GB free on $drive", $false)
}

function Default-Parent {
    # A run that stopped part way left its choice behind: offer the same place again.
    $before = [Environment]::GetEnvironmentVariable("CAMTRAP_DATA_DIR", "User")
    if ($before -and ([System.IO.Path]::GetFileName($before.TrimEnd("\")) -ieq "data")) {
        return (Split-Path $before.TrimEnd("\") -Parent)
    }
    # Otherwise D: when it is a local disk with more room than C: (the dept machines' case), else the old place.
    try {
        $d = New-Object System.IO.DriveInfo("D")
        $c = New-Object System.IO.DriveInfo("C")
        if ($d.IsReady -and $d.DriveType -eq [System.IO.DriveType]::Fixed -and
            $d.AvailableFreeSpace -gt $c.AvailableFreeSpace) { return "D:\" }
    } catch {}
    return $env:LOCALAPPDATA
}

function New-FolderDialog($suggest) {
    # Built apart from Ask-Folder so it can be made and looked at without waiting for a click.
    $box = New-Object System.Windows.Forms.Form
    $box.Text = "$Name Setup"
    $box.Size = New-Object System.Drawing.Size(580, 250)
    $box.StartPosition = "CenterScreen"
    $box.FormBorderStyle = "FixedDialog"
    $box.MaximizeBox = $false
    $box.MinimizeBox = $false
    $box.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#14171B")

    $mark = New-Object System.Windows.Forms.Label
    $mark.Text = "CAMTRAP MEASURE"
    $mark.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 13)
    $mark.ForeColor = $Amber
    $mark.SetBounds(22, 18, 400, 28)
    $box.Controls.Add($mark)

    $question = New-Object System.Windows.Forms.Label
    $question.Text = "Where should $Name be installed?"
    $question.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $question.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#E8EAED")
    $question.SetBounds(24, 54, 520, 22)
    $box.Controls.Add($question)

    $field = New-Object System.Windows.Forms.TextBox
    $field.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $field.Text = $suggest
    $field.SetBounds(24, 84, 412, 26)
    $box.Controls.Add($field)

    $browse = New-Object System.Windows.Forms.Button
    $browse.Text = "Browse..."
    $browse.SetBounds(444, 83, 100, 28)
    $box.Controls.Add($browse)

    $where = New-Object System.Windows.Forms.Label
    $where.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $where.SetBounds(24, 118, 520, 36)
    $box.Controls.Add($where)

    $go = New-Object System.Windows.Forms.Button
    $go.Text = "Install"
    $go.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $go.SetBounds(336, 166, 100, 28)
    $box.Controls.Add($go)
    $box.AcceptButton = $go

    $stop = New-Object System.Windows.Forms.Button
    $stop.Text = "Cancel"
    $stop.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $stop.SetBounds(444, 166, 100, 28)
    $box.Controls.Add($stop)
    $box.CancelButton = $stop

    # Script scope, not closures: the handlers run while ShowDialog is on the stack, and a closure
    # (GetNewClosure) would not see this script's functions.
    $script:FolderField = $field
    $script:FolderWhere = $where
    $field.add_TextChanged({ Show-Where })
    $browse.add_Click({
        $pick = New-Object System.Windows.Forms.FolderBrowserDialog
        $pick.Description = "Pick a folder. $Name goes in a CamTrapMeasure folder inside it."
        if (Test-Path -LiteralPath $script:FolderField.Text) { $pick.SelectedPath = $script:FolderField.Text }
        if ($pick.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $script:FolderField.Text = $pick.SelectedPath }
        $pick.Dispose()
    })
    Show-Where
    return $box
}

function Show-Where {
    $said = Where-Text $script:FolderField.Text
    $script:FolderWhere.Text = $said[0]
    $script:FolderWhere.ForeColor = if ($said[1]) { $Amber } else { [System.Drawing.ColorTranslator]::FromHtml("#8A929C") }
}

function Ask-Folder($suggest) {
    # Asks until the answer is a folder this account can write to. Returns it, or $null for Cancel.
    if ($Console) {
        while ($true) {
            $typed = Read-Host "Where should $Name be installed? Press Enter for $suggest"
            if (-not $typed) { $typed = $suggest }
            $root = Resolve-InstallRoot $typed
            $problem = if ($root) { Test-InstallRoot $root } else { "That is not a full folder path, like D:\" }
            if (-not $problem) { return $root }
            Write-Host "$problem. Pick another folder." -ForegroundColor Yellow
        }
    }
    $box = New-FolderDialog $suggest
    try {
        while ($box.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            $root = Resolve-InstallRoot $script:FolderField.Text
            $problem = if ($root) { Test-InstallRoot $root } else { "That is not a full folder path, like D:\" }
            if (-not $problem) { return $root }
            [System.Windows.Forms.MessageBox]::Show("$problem.`r`n`r`nPick another folder.", "$Name Setup",
                [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        }
        return $null
    } finally {
        $box.Dispose()
    }
}

# Already installed: repair it where it is, with no question, and leave its data where it is. The
# Settings > Apps entry says where; an install from before that entry existed is found at the old place.
$Root = $null      # R, for an install made by ticket 24 or later; $null for an older one
$Repair = $false
$Notes = @()       # for the details pane, which does not exist yet
$known = $null
try { $known = (Get-ItemProperty -Path $Key -ErrorAction Stop).InstallLocation } catch { $known = $null }
if ($known -and (Test-Path -LiteralPath $known)) {
    $Dir = $known
    $Repair = $true
} elseif (Test-Path -LiteralPath (Join-Path $LegacyDir ".git")) {
    $Dir = $LegacyDir
    $Repair = $true
}
$asked = if ($InstallTo) { $InstallTo } elseif ($env:CAMTRAP_INSTALL_DIR) { $env:CAMTRAP_INSTALL_DIR } else { $null }
if ($Repair) {
    if ([System.IO.Path]::GetFileName($Dir.TrimEnd("\")) -ieq "app") { $Root = Split-Path $Dir.TrimEnd("\") -Parent }
    $Notes += "Already installed in $Dir; repairing it there."
    if ($asked) { $Notes += "The folder given ($asked) is not used: remove the app first to install it somewhere else." }
    # An older install has no R: its data stays wherever it has been (the variable if set, else the default).
    foreach ($n in $EnvNames) {
        $v = [Environment]::GetEnvironmentVariable($n, "User")
        if ($v) { Set-Item -Path "env:$n" -Value $v }
    }
} else {
    if ($asked) {
        $Root = Resolve-InstallRoot $asked
        $problem = if ($Root) { Test-InstallRoot $Root } else { "$asked is not a full folder path, like D:\" }
        if ($problem) {
            if ($Console) { Write-Host "$problem." -ForegroundColor Yellow }
            else {
                [System.Windows.Forms.MessageBox]::Show("$problem.`r`n`r`nPick another folder.", "$Name Setup",
                    [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
            }
            $Root = Ask-Folder $asked
        }
    } else {
        $Root = Ask-Folder (Default-Parent)
    }
    if (-not $Root) { exit 0 }  # Cancel: nothing was made, nothing was changed
    $Dir = Join-Path $Root "app"
}
if ($Root) {
    $Layout = @{
        "CAMTRAP_DATA_DIR"      = (Join-Path $Root "data")
        "UV_CACHE_DIR"          = (Join-Path $Root "uv-cache")
        "UV_PYTHON_INSTALL_DIR" = (Join-Path $Root "python")
    }
    # This process first: step 7 starts the app from here, and Explorer may not have the new values yet.
    foreach ($n in $EnvNames) { Set-Item -Path "env:$n" -Value $Layout[$n] }
}
$DataDir = if ($env:CAMTRAP_DATA_DIR) { $env:CAMTRAP_DATA_DIR } else { Join-Path $env:USERPROFILE ".camtrap-measure" }
$Ico = Join-Path $Dir "src\camtrap_measure\assets\camtrap-measure.ico"

if (-not $Console) {
    $Form = New-Object System.Windows.Forms.Form
    $Form.Text = "$Name Setup"
    $Form.Size = New-Object System.Drawing.Size(660, 470)
    $Form.StartPosition = "CenterScreen"
    $Form.FormBorderStyle = "FixedDialog"
    $Form.MaximizeBox = $false
    $Form.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#14171B")

    $mark = New-Object System.Windows.Forms.Label
    $mark.Text = "CAMTRAP MEASURE"
    $mark.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 13)
    $mark.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#E8A13C")
    $mark.SetBounds(24, 22, 400, 28)
    $Form.Controls.Add($mark)

    $sub = New-Object System.Windows.Forms.Label
    $sub.Text = "Installing into $(if ($Root) { $Root } else { $Dir }). Nothing here needs an administrator."
    $sub.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $sub.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#8A929C")
    $sub.SetBounds(26, 52, 600, 20)
    $Form.Controls.Add($sub)

    $StepLabel = New-Object System.Windows.Forms.Label
    $StepLabel.Text = "Starting..."
    $StepLabel.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $StepLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#E8EAED")
    $StepLabel.SetBounds(26, 86, 600, 22)
    $Form.Controls.Add($StepLabel)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = "Continuous"
    $bar.Minimum = 0
    $bar.Maximum = 7  # the steps below; the bar is a promise about how much is left, so keep it in step
    $bar.SetBounds(26, 112, 600, 8)
    $Form.Controls.Add($bar)
    $script:Bar = $bar

    $Details = New-Object System.Windows.Forms.TextBox
    $Details.Multiline = $true
    $Details.ReadOnly = $true
    $Details.ScrollBars = "Vertical"
    $Details.Font = New-Object System.Drawing.Font("Consolas", 8.5)
    $Details.BackColor = [System.Drawing.ColorTranslator]::FromHtml("#0E1013")
    $Details.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#C7CCD2")
    $Details.BorderStyle = "FixedSingle"
    $Details.SetBounds(26, 134, 600, 250)
    $Form.Controls.Add($Details)

    $Form.Show()
}

$Done = 0
function Pump { if ($Form) { [System.Windows.Forms.Application]::DoEvents() } }

# Each failed check (a line starting with the cross) and the fix under it (the arrow line), kept so a failure
# can show them in the message box itself: on 2026-09-03 a dept user saw only "the details pane lists what
# to fix" and never found the fix in the pane.
$script:Problems = New-Object System.Collections.Generic.List[string]
$script:InProblem = $false
function Detail($text) {
    if ($null -eq $text) { return }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line.Trim() -eq "") { continue }
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith($Cross)) { $script:Problems.Add($trimmed); $script:InProblem = $true }
        elseif ($script:InProblem -and $trimmed.StartsWith($Arrow)) { $script:Problems.Add("    $trimmed") }
        else { $script:InProblem = $false }
        if ($Details) {
            $Details.AppendText("$line`r`n")
        } else {
            Write-Host "   $line"
        }
        Log $line
    }
    Pump
}

function Step($msg) {
    $script:Done += 1
    Log "== $msg"
    if ($StepLabel) {
        $StepLabel.Text = $msg
        $script:Bar.Value = [Math]::Min($script:Done, $script:Bar.Maximum)
        $Details.AppendText("== $msg`r`n")
    } else {
        Write-Host ""
        Write-Host "==> $msg" -ForegroundColor Cyan
    }
    Pump
}

function Fail($msg) {
    $send = "The full record is in $LogFile - send that file to the researcher if the fix is not clear."
    $found = ""
    if ($script:Problems.Count -gt 0) {
        $shown = @($script:Problems | Select-Object -First 20)
        $found = "What went wrong:`r`n" + ($shown -join "`r`n") + "`r`n`r`n"
    }
    Log "STOPPED: $msg"
    Log $send
    if ($Form) {
        $StepLabel.Text = "Stopped."
        $Details.AppendText("STOPPED: $msg`r`n")
        $Details.AppendText("$send`r`n")
        [System.Windows.Forms.MessageBox]::Show("$msg`r`n`r`n$found$send", "$Name Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        # The window stays after OK, with a message loop of its own, until the user closes it. Closing it
        # here took the pane off the screen at the one moment somebody needed to read it: a dept user hit
        # the preflight failure on 2026-09-03 and could send nothing but a photograph of this message box.
        try { [System.Windows.Forms.Application]::Run($Form) } catch { Write-Host $_.Exception.Message }
    } else {
        Write-Host ""
        Write-Host "STOPPED: $msg" -ForegroundColor Red
        if ($found) { Write-Host $found -ForegroundColor Red }
        Write-Host $send -ForegroundColor Yellow
        Read-Host "Press Enter to close" | Out-Null
    }
    exit 1
}

# --- the log ----------------------------------------------------------------------------------------
# The details pane disappears with the window, and the person running the installer is usually not the
# person who can fix what it says. So every run - window or -Console - writes the same lines to $LogFile,
# overwriting it, so the file is always the last run and nothing else. The Hugging Face token never
# reaches the pane (see Ask-Token), which is why it never reaches this file either.
$script:LogOff = $false
function Log($line) {
    if ($script:LogOff) { return }
    try {
        Add-Content -Path $LogFile -Value $line -Encoding utf8 -ErrorAction Stop
    } catch {
        $script:LogOff = $true  # set first: Detail calls Log, and this must not turn into a loop
        Detail "Could not write the setup log to $LogFile ($($_.Exception.Message)). The install carries on."
    }
}

$here = "the app is not on this machine yet"
$pyproject0 = Join-Path $Dir "pyproject.toml"
if (Test-Path $pyproject0) {
    $v0 = Select-String -Path $pyproject0 -Pattern '^version = "(.+)"' | Select-Object -First 1
    if ($v0) { $here = "app version " + $v0.Matches[0].Groups[1].Value + " already installed" }
}
$script:LogOff = $true  # until one of the candidates takes the header
$logMisses = @()
foreach ($candidate in $LogCandidates) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $candidate -Parent) -ErrorAction Stop | Out-Null
        Set-Content -Path $candidate -Encoding utf8 -ErrorAction Stop `
                    -Value "$Name setup - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $here"
        $LogFile = $candidate
        $script:LogOff = $false
        break
    } catch {
        $logMisses += "Could not write the setup log to $candidate ($($_.Exception.Message))."
    }
}
foreach ($miss in $logMisses) { Detail $miss }
if ($script:LogOff) { Detail "No setup log this time; the install carries on." }

# What this machine is. Whoever reads the log has never seen the computer it came from, and nobody has
# written the department's hardware down at all. Each fact is asked for on its own: a query that fails
# says "unknown" and the install carries on, because none of this is needed to install anything. Parts
# and disk sizes only - no user names beyond the ones already in the paths above.
function Fact($name, $get) {
    $value = $null
    try { $value = & $get } catch { $value = $null }
    if (-not $value) { $value = "unknown" }
    Detail "$name`: $value"
}
Detail "--- this machine ---"
Fact "Computer" { $env:COMPUTERNAME }
Fact "Windows" { $o = Get-CimInstance Win32_OperatingSystem; "$($o.Caption) build $($o.Version)" }
Fact "Processor" { (Get-CimInstance Win32_Processor | ForEach-Object { $_.Name.Trim() }) -join ", " }
Fact "Memory" { "{0:N1} GB" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) }
Fact "Graphics" { (Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join ", " }
Fact "Disks" {
    (Get-PSDrive -PSProvider FileSystem | Where-Object { $null -ne $_.Free } | ForEach-Object {
        "{0}: {1:N0} GB free of {2:N0} GB" -f $_.Name, ($_.Free / 1GB), (($_.Used + $_.Free) / 1GB)
    }) -join "; "
}
function Folder-Fact($path) {
    $free = Free-GB $path
    if ($null -eq $free) { return "$path (free space unknown)" }
    return "$path ($free GB free on $([System.IO.Path]::GetPathRoot($path)))"
}
Fact "Install folder" { Folder-Fact $(if ($Root) { $Root } else { $Dir }) }
Fact "App folder" { $Dir }
Fact "Data folder" { Folder-Fact $DataDir }
Detail "Log: $LogFile (this run only; every run overwrites it)"
Detail "--------------------"
foreach ($note in $Notes) { Detail $note }

# Saved as user variables (no administrator needed) so the app, the launcher and the uninstaller find the
# data and uv's folders on every later start. The launcher reads them back itself at start, so it does not
# matter whether Explorer has picked them up yet.
if ($Root) {
    foreach ($n in $EnvNames) {
        [Environment]::SetEnvironmentVariable($n, $Layout[$n], "User")
        Detail "$n = $($Layout[$n])"
    }
}

function AddPath($p) { if ((Test-Path $p) -and (($env:Path -split ";") -notcontains $p)) { $env:Path = "$p;" + $env:Path } }

# Runs a command with its output in the details pane and no console window of its own.
function Run($exe, $arguments, $where) {
    if (-not $where) { $where = $env:TEMP }
    $out = Join-Path $env:TEMP "camtrap-setup.out"
    $err = Join-Path $env:TEMP "camtrap-setup.err"
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $where -NoNewWindow -PassThru `
                       -RedirectStandardOutput $out -RedirectStandardError $err
    # Touching .Handle keeps the process object's handle open; without it PowerShell can hand back
    # a null ExitCode when the child has already gone, and every step would read as a failure.
    $null = $p.Handle
    $shown = 0
    while (-not $p.HasExited) {
        Pump
        Start-Sleep -Milliseconds 150
        if (Test-Path $out) {  # stream it: `uv sync` pulls gigabytes and silence reads as a hang
            $lines = @(Get-Content $out -Encoding UTF8 -ErrorAction SilentlyContinue)
            if ($lines.Count -gt $shown) {
                Detail ($lines[$shown..($lines.Count - 1)] -join "`r`n")
                $shown = $lines.Count
            }
        }
    }
    if (Test-Path $out) {
        $lines = @(Get-Content $out -Encoding UTF8)
        if ($lines.Count -gt $shown) { Detail ($lines[$shown..($lines.Count - 1)] -join "`r`n") }
    }
    if (Test-Path $err) { Detail (Get-Content $err -Raw -Encoding UTF8) }
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    return $p.ExitCode
}

function Ask-Token {
    # Asks for the Hugging Face read token. Never echoed and never written to the details pane: the
    # installer only hands it to the app, which stores it in config.json.
    $ask = "Hugging Face read token for the model weights (ask the researcher). Leave it empty to carry " +
           "on without one: the app then shows made-up numbers until the token is set."
    if ($Console) {
        $secure = Read-Host "$ask`nToken" -AsSecureString
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    $box = New-Object System.Windows.Forms.Form
    $box.Text = "$Name Setup"
    $box.Size = New-Object System.Drawing.Size(560, 220)
    $box.StartPosition = "CenterParent"
    $box.FormBorderStyle = "FixedDialog"
    $box.MaximizeBox = $false
    $box.MinimizeBox = $false
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $ask
    $label.SetBounds(18, 18, 510, 62)
    $box.Controls.Add($label)
    $field = New-Object System.Windows.Forms.TextBox
    $field.UseSystemPasswordChar = $true  # a token is a credential: it does not belong on a screen
    $field.SetBounds(18, 88, 510, 24)
    $box.Controls.Add($field)
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Continue"
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $ok.SetBounds(428, 128, 100, 28)
    $box.Controls.Add($ok)
    $box.AcceptButton = $ok
    $box.ShowDialog($Form) | Out-Null
    $typed = $field.Text
    $box.Dispose()
    return $typed
}

function Shortcut($path, $target, $arguments, $description) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $Dir
    $s.Description = $description
    if (Test-Path $Ico) { $s.IconLocation = "$Ico,0" }
    $s.Save()
}

# --- 1. tools ---------------------------------------------------------------------------------------
Step "Checking the tools (nothing here needs an administrator)"
AddPath (Join-Path $MinGitDir "cmd")
AddPath $UvBin
if (Get-Command git -ErrorAction SilentlyContinue) { Detail "Git is installed." } else {
    Detail "Getting a portable Git into $MinGitDir (40 MB)..."
    $zip = Join-Path $env:TEMP "MinGit.zip"
    try { Invoke-WebRequest -Uri $MinGitUrl -OutFile $zip } catch {
        Fail "Could not download Git from $MinGitUrl ($($_.Exception.Message)). Check the internet connection (github.com must be reachable), then run this again."
    }
    Expand-Archive -Path $zip -DestinationPath $MinGitDir -Force
    Remove-Item $zip
    AddPath (Join-Path $MinGitDir "cmd")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail "Git was unpacked into $MinGitDir but git.exe is not there. Delete that folder and run this again."
    }
}
if (Get-Command uv -ErrorAction SilentlyContinue) { Detail "uv is installed." } else {
    Detail "Installing uv into $UvBin..."
    if ((Run "powershell.exe" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://astral.sh/uv/install.ps1 | iex")) -ne 0) {
        Fail "uv did not install. Check the internet connection (astral.sh must be reachable), then run this again."
    }
    AddPath $UvBin
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Fail "uv did not install. Check the internet connection (astral.sh must be reachable), then run this again."
    }
}

# --- 2. the app -------------------------------------------------------------------------------------
Step "Getting the app into $Dir"
if (Test-Path (Join-Path $Dir ".git")) {
    Detail "Already here; the launcher updates it at every start (and honours ref.txt)."
} else {
    if ((Run "git" @("clone", "--quiet", $Repo, $Dir) $env:TEMP) -ne 0) {
        Fail "Could not download the app from $Repo. Check the internet connection (github.com must be reachable)."
    }
}
Set-Location $Dir
Detail "The app on this machine is now:"
$null = Run "git" @("--no-pager", "log", "-1", "--format=%h %cs %s") $Dir  # which commit, in the log, for a bug report

# --- 3. environment ---------------------------------------------------------------------------------
Step "Building the app's environment"
if ((Run "uv" @("sync", "--frozen") $Dir) -ne 0) {
    Fail "The environment could not be built. Check the internet connection and the free disk space, then run this again."
}

# --- 4. the weights token, then the checks ----------------------------------------------------------
# The checks ask nothing now: they run with no console to ask through, and a bare input() there raised
# EOFError before a single check was read (2026-08-23). The token is the one thing only a person can
# supply, so the installer asks for it in its own window and hands it over in the environment; signing in
# to FlagLabel happens in the app window, which has had its own sign-in since ticket 14.
$cfg = Join-Path $DataDir "config.json"  # where the app will look: CAMTRAP_DATA_DIR, set above for this process

# Weights that came with the installer: copy them in and the token question never arises.
if (-not $WeightsFrom) {
    $beside = Join-Path $PSScriptRoot "weights"
    if (Test-Path (Join-Path $beside "manifest.json")) { $WeightsFrom = $beside }
}
$bundled = $false
if ($WeightsFrom) {
    if (-not (Test-Path (Join-Path $WeightsFrom "manifest.json"))) {
        Fail "No model weights in $WeightsFrom - it should hold manifest.json and the model files."
    }
    $target = Join-Path $DataDir "weights"
    $have = Join-Path $target "manifest.json"
    $same = (Test-Path $have) -and ((Get-Content $have -Raw) -eq (Get-Content (Join-Path $WeightsFrom "manifest.json") -Raw))
    if ($same) {
        Detail "The model weights on this machine are already the ones in this installer."
    } else {
        Step "Copying the models onto this machine (about 6.5 GB - please wait)"
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        # robocopy: the only thing on a stock Windows that copies 6.5 GB reliably and restarts a part-
        # copied file. Its exit codes below 8 are all success (0 = nothing to do, 1 = files copied).
        $null = & robocopy $WeightsFrom $target /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2
        if ($LASTEXITCODE -ge 8) { Fail "The models could not be copied to $target (robocopy $LASTEXITCODE). Check the free disk space." }
        Detail "Models installed in $target."
    }
    $bundled = $true
} else {
    $hasToken = $env:HF_TOKEN -or ((Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match '"hf_token"\s*:\s*"\S'))  # already answered: do not ask again
    if (-not $hasToken) {
        $token = Ask-Token
        if ($token) { $env:HF_TOKEN = $token }
    }
}

if ($bundled) {
    # Said in config.json rather than guessed from the absence of a token: a developer machine has no
    # token either and still reaches the hub through a cached huggingface-cli login, and must go on
    # picking up new weights versions.
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $conf = if (Test-Path $cfg) { Get-Content $cfg -Raw | ConvertFrom-Json } else { New-Object PSObject }
    $conf | Add-Member -NotePropertyName "weights_from" -NotePropertyValue "bundle" -Force
    $conf | ConvertTo-Json | Set-Content $cfg -Encoding utf8
    Detail "This machine uses the models that came with the installer; no Hugging Face token is needed."
}

Step "Checking this machine (before the big download)"
if ((Run "uv" @("run", "--frozen", "camtrap-measure", "--preflight", "--no-prompt") $Dir) -ne 0) {
    Fail "This machine is not ready yet. Fix what is listed below and run the installer again."
}

# --- 5. the models' software ------------------------------------------------------------------------
Step "Installing the models' software (a few GB - the CUDA build of PyTorch - please wait)"
if ((Run "uv" @("sync", "--frozen", "--extra", "inference") $Dir) -ne 0) {
    Fail "The GPU software could not be installed. Check the internet connection and the free disk space, then run this again."
}
if ((Run "uv" @("run", "--frozen", "python", "-c", "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)") $Dir) -eq 0) {
    Detail "PyTorch sees the GPU."
} else {
    Detail "WARNING: PyTorch does not see a GPU. The app will run on the processor instead, many times slower. Reboot if the driver was just installed."
}

# --- 6. shortcuts and the Settings entry ------------------------------------------------------------
Step "Putting $Name on the desktop and in the Start menu"
$launch = """" + (Join-Path $Dir "scripts\launch.vbs") + """"
# wscript, not the .bat: a shortcut to a .bat is run by cmd.exe, which must have a console window, and
# that console then stays open behind the app for the whole session (reported 2026-08-23).
Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$Name.lnk") $Wscript $launch "Measure the distance to deer in camera-trap photos"
Shortcut (Join-Path ([Environment]::GetFolderPath("Programs")) "$Name.lnk") $Wscript $launch "Measure the distance to deer in camera-trap photos"

$version = "0.1.0"
$pyproject = Join-Path $Dir "pyproject.toml"
if (Test-Path $pyproject) {
    $line = Select-String -Path $pyproject -Pattern '^version = "(.+)"' | Select-Object -First 1
    if ($line) { $version = $line.Matches[0].Groups[1].Value }
}
# Per-user (HKCU), so it appears in Settings > Apps and can be removed from there without an administrator.
New-Item -Path $Key -Force | Out-Null
New-ItemProperty -Path $Key -Name "DisplayName" -Value $Name -Force | Out-Null
New-ItemProperty -Path $Key -Name "DisplayVersion" -Value $version -Force | Out-Null
New-ItemProperty -Path $Key -Name "DisplayIcon" -Value $Ico -Force | Out-Null
New-ItemProperty -Path $Key -Name "Publisher" -Value "BASE Lab, SIU Carbondale" -Force | Out-Null
New-ItemProperty -Path $Key -Name "InstallLocation" -Value $Dir -Force | Out-Null
New-ItemProperty -Path $Key -Name "UninstallString" `
                 -Value ("$Wscript """ + (Join-Path $Dir "scripts\uninstall.vbs") + """") -Force | Out-Null
New-ItemProperty -Path $Key -Name "NoModify" -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $Key -Name "NoRepair" -Value 1 -PropertyType DWord -Force | Out-Null
Detail "Listed in Settings > Apps as $Name $version."

# --- 7. first start ---------------------------------------------------------------------------------
Step $(if ($bundled) { "Starting $Name" } else { "Starting $Name (the first start downloads the models; the window shows the progress)" })
Start-Process -FilePath $Wscript -ArgumentList (Join-Path $Dir "scripts\launch.vbs") -WorkingDirectory $Dir
Detail "Done. $Name is installed."
if ($Form) {
    $StepLabel.Text = "$Name is installed. From now on, double-click its icon on the desktop."
    Pump
    Start-Sleep -Seconds 3
    $Form.Close()
} else {
    Write-Host ""
    Write-Host "Done. From now on, double-click '$Name' on the desktop." -ForegroundColor Green
}

# A form was shown without a message loop of its own; ending the script explicitly is what makes
# the process go, rather than lingering with a closed window nobody can see.
exit 0
