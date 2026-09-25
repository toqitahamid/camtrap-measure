<#
  Removes CamTrap Measure. Settings > Apps > CamTrap Measure > Uninstall runs this through
  scripts\uninstall.vbs, so it has a window and no console. It asks twice: once before removing the app,
  and again about the measurements and downloaded models, which are kept unless they are asked for by
  name. Nothing here needs an administrator - everything it removes is this user's.

  Since ticket 24 an install sits under one folder R: R\app (this script's folder), R\data, R\uv-cache and
  R\python, with the last three named in R\camtrap-install.json (an install made before that file has them
  in user environment variables instead). The app, uv-cache, python and that file go with the first
  question, the data only on the second, and any such variables once the app is gone. An install from
  before ticket 24 has the app in %LOCALAPPDATA%\CamTrapMeasure and the data in %USERPROFILE%\.camtrap-measure.

    -Yes   remove the app without the first question (the data question is still asked)
    -FromTemp   internal: this is the copy in TEMP that does the removing (passed by the first stage)
#>
[CmdletBinding()]
param([switch]$Yes, [switch]$FromTemp)

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

# One argument for a command line, by the Windows rules: wrapped in double quotes when it holds a space or a
# quote, an inner quote as \", and the backslashes before a quote (or before the closing one) doubled. The
# same function as in install.ps1 (the scripts share no code). An argument already in quotes passes as it is.
function Quote-Arg([string]$a) {
    if ($a.Length -ge 2 -and $a.StartsWith('"') -and $a.EndsWith('"')) { return $a }
    if ($a -ne "" -and $a -notmatch '[\s"]') { return $a }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($c in $a.ToCharArray()) {
        if ($c -eq [char]'\') { $slashes++; continue }
        if ($c -eq [char]'"') { [void]$sb.Append('\' * (2 * $slashes + 1)) } else { [void]$sb.Append('\' * $slashes) }
        [void]$sb.Append($c)
        $slashes = 0
    }
    [void]$sb.Append('\' * (2 * $slashes))
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Is-Inside($path, $root) {
    if (-not $path -or -not $root) { return $false }
    return ($path.TrimEnd("\") + "\").StartsWith($root.TrimEnd("\") + "\", [StringComparison]::OrdinalIgnoreCase)
}

# This script lives inside the folder it deletes, so it finishes the job from a copy in TEMP. The copy is told
# so by -FromTemp. It used to work it out by comparing $PSScriptRoot with $env:TEMP, but when the account name
# is longer than 8 characters TEMP is the short 8.3 form (SIU856~4) and $PSScriptRoot the long one,
# so the copy thought it was the original, tried to copy itself onto itself, and died with no window: Uninstall
# in Settings did nothing at all (2026-09-25).
if (-not $FromTemp) {
    $copy = Join-Path $env:TEMP "camtrap-uninstall\scripts"
    New-Item -ItemType Directory -Force -Path $copy | Out-Null
    Copy-Item $PSCommandPath (Join-Path $copy "uninstall.ps1") -Force
    "$Dir" | Set-Content (Join-Path $copy "installed-at.txt")
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $copy "uninstall.ps1"))
    $argv += "-FromTemp"
    if ($Yes) { $argv += "-Yes" }
    # Quoted (Quote-Arg): Start-Process joins the list with spaces and quotes nothing, so a TEMP path with a
    # space reached powershell.exe as two arguments and the copy never started.
    $line = ($argv | ForEach-Object { Quote-Arg $_ }) -join " "
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $line
    exit 0
}
$marker = Join-Path $PSScriptRoot "installed-at.txt"
if (-not (Test-Path $marker)) {
    Tell "Could not tell where $Name is installed ($marker is missing). Nothing was removed. Use Uninstall in Settings > Apps again."
    exit 1
}
$Dir = (Get-Content $marker -TotalCount 1).Trim()

$EnvNames = @("CAMTRAP_DATA_DIR", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR")
# R, for an install made by ticket 24 or later: the app folder is R\app. $null for an older install.
$Root = $null
if ([System.IO.Path]::GetFileName($Dir.TrimEnd("\")) -ieq "app") { $Root = Split-Path $Dir.TrimEnd("\") -Parent }
# The data is where the app has been keeping it: the layout file the installer wrote in R, else the user
# variable an install made before that file set (only one inside R), else the app's default.
$Data = $null
$LayoutFile = $null
if ($Root) {
    $LayoutFile = Join-Path $Root "camtrap-install.json"
    if (Test-Path -LiteralPath $LayoutFile) {
        try { $Data = ([IO.File]::ReadAllText($LayoutFile) | ConvertFrom-Json).data } catch { $Data = $null }
    }
    if (-not $Data) {
        $v = [Environment]::GetEnvironmentVariable("CAMTRAP_DATA_DIR", "User")
        if (Is-Inside $v $Root) { $Data = $v }
    }
}
if (-not $Data) { $Data = Join-Path $env:USERPROFILE ".camtrap-measure" }
# What the first question removes: the app, uv's cache and Python when they are this install's own, and the
# layout file (it describes the app, which is going).
$Software = @($Dir)
if ($Root) {
    foreach ($sub in @("uv-cache", "python", "camtrap-install.json")) {
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
        if (Is-Inside $v $Root) {
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
