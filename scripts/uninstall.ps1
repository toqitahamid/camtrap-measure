<#
  Removes CamTrap Measure. Settings > Apps > CamTrap Measure > Uninstall runs this through
  scripts\uninstall.vbs, so it has a window and no console. It asks twice: once before removing the app,
  and again about the measurements and downloaded models, which are kept unless they are asked for by
  name. Nothing here needs an administrator - everything it removes is this user's.

  Since ticket 24 an install sits under one folder R: R\app (this script's folder), R\data, R\uv-cache and
  R\python, with the last three named by user environment variables. The app, uv-cache and python go with
  the first question, the data only on the second, and the variables once the app is gone. An install from
  before ticket 24 has the app in %LOCALAPPDATA%\CamTrapMeasure and the data in %USERPROFILE%\.camtrap-measure.

    -Yes   remove the app without the first question (the data question is still asked)
#>
[CmdletBinding()]
param([switch]$Yes)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Name = "CamTrap Measure"
$Dir = Split-Path -Parent $PSScriptRoot
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CamTrapMeasure"

function Ask($text, $icon) {
    return [System.Windows.Forms.MessageBox]::Show($text, "Remove $Name",
        [System.Windows.Forms.MessageBoxButtons]::YesNo, $icon,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2) -eq [System.Windows.Forms.DialogResult]::Yes
}

function Tell($text) {
    [System.Windows.Forms.MessageBox]::Show($text, "Remove $Name",
        [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
}

# This script lives inside the folder it deletes, so it finishes the job from a copy in TEMP.
if ($PSScriptRoot -notlike "$env:TEMP*") {
    $copy = Join-Path $env:TEMP "camtrap-uninstall\scripts"
    New-Item -ItemType Directory -Force -Path $copy | Out-Null
    Copy-Item $PSCommandPath (Join-Path $copy "uninstall.ps1") -Force
    "$Dir" | Set-Content (Join-Path $copy "installed-at.txt")
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $copy "uninstall.ps1"))
    if ($Yes) { $argv += "-Yes" }
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $argv
    exit 0
}
$marker = Join-Path $PSScriptRoot "installed-at.txt"
if (Test-Path $marker) { $Dir = (Get-Content $marker -TotalCount 1).Trim() }

$EnvNames = @("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR")
# R, for an install made by ticket 24 or later: the app folder is R\app. $null for an older install.
$Root = $null
if ([System.IO.Path]::GetFileName($Dir.TrimEnd("\")) -ieq "app") { $Root = Split-Path $Dir.TrimEnd("\") -Parent }
# The data is where the app has been keeping it: the user variable the installer set, else the app's default.
$Data = [Environment]::GetEnvironmentVariable("CAMTRAP_DATA_DIR", "User")
if (-not $Data) { $Data = $env:CAMTRAP_DATA_DIR }
if (-not $Data) { $Data = Join-Path $env:USERPROFILE ".camtrap-measure" }
# What the first question removes: the app, and uv's cache and Python when they are this install's own.
$Software = @($Dir)
if ($Root) {
    foreach ($sub in @("uv-cache", "python")) {
        $p = Join-Path $Root $sub
        if (Test-Path -LiteralPath $p) { $Software += $p }
    }
}

function Size-Of($paths) {
    $sum = 0
    foreach ($p in $paths) {
        try { $sum += (Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } catch {}
    }
    return $sum
}

if (-not (Test-Path $Dir)) {
    Remove-Item $Key -Recurse -Force -ErrorAction SilentlyContinue
    Tell "$Name was already removed from this computer."
    exit 0
}

$size = Size-Of $Software
if (-not $Yes) {
    # the format runs on the whole message, so the concatenation is closed before -f is applied
    $ask = ("Remove $Name from this computer?`r`n`r`nThis deletes the app and its software in`r`n$($Software -join "`r`n") " +
            "({0:N1} GB).`r`n`r`nYour measurements and the downloaded models are in $Data and are kept " +
            "unless you say otherwise on the next question.") -f ($size / 1GB)
    $ok = Ask $ask ([System.Windows.Forms.MessageBoxIcon]::Warning)
    if (-not $ok) { exit 0 }
}

# A running app holds its own files open; deleting around it would leave the folder half there.
$running = Get-Process -Name "camtrap-measure-app", "pythonw" -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    if (-not (Ask "$Name is open. Close it and carry on removing it?" ([System.Windows.Forms.MessageBoxIcon]::Warning))) { exit 0 }
    foreach ($p in $running) {
        $p.CloseMainWindow() | Out-Null
        if (-not $p.WaitForExit(10000)) { $p.Kill() }  # the window is gone but the process is wedged
    }
}

foreach ($lnk in @((Join-Path ([Environment]::GetFolderPath("Desktop")) "$Name.lnk"),
                   (Join-Path ([Environment]::GetFolderPath("Programs")) "$Name.lnk"))) {
    Remove-Item $lnk -Force -ErrorAction SilentlyContinue
}
Remove-Item $Key -Recurse -Force -ErrorAction SilentlyContinue

foreach ($p in $Software) {
    try {
        Remove-Item -LiteralPath $p -Recurse -Force
    } catch {
        Tell ("Most of $Name is removed, but some files in`r`n$p`r`ncould not be deleted ($($_.Exception.Message)). " +
              "Restart the computer and delete that folder by hand.")
        exit 1
    }
}

# The app is gone, so the variables that pointed at its folders go too. Only the ones inside R: a variable
# somebody set by hand, or one for an older install, is not this uninstaller's to remove.
if ($Root) {
    foreach ($n in $EnvNames) {
        $v = [Environment]::GetEnvironmentVariable($n, "User")
        if ($v -and ($v.TrimEnd("\") + "\").StartsWith($Root.TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)) {
            [Environment]::SetEnvironmentVariable($n, $null, "User")
        }
    }
}

if (Test-Path $Data) {
    $dsize = 0
    $dsize = Size-Of @($Data)
    $ask = ("Also delete your measurements and the downloaded models?`r`n`r`n$Data ({0:N1} GB)`r`n`r`n" +
            "This cannot be undone. Answer No to keep them for a future install.") -f ($dsize / 1GB)
    $also = Ask $ask ([System.Windows.Forms.MessageBoxIcon]::Warning)
    if ($also) { Remove-Item -LiteralPath $Data -Recurse -Force -ErrorAction SilentlyContinue }
}

# R itself, once nothing is left in it (the data was kept, or it was the last thing there).
if ($Root -and (Test-Path -LiteralPath $Root) -and -not (Get-ChildItem -LiteralPath $Root -Force)) {
    try { [System.IO.Directory]::Delete($Root, $false) } catch {}
}

Tell "$Name has been removed."
