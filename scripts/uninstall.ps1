<#
  Removes CamTrap Measure. Settings > Apps > CamTrap Measure > Uninstall runs this through
  scripts\uninstall.vbs, so it has a window and no console. It asks twice: once before removing the app,
  and again about the measurements and downloaded models, which are kept unless they are asked for by
  name. Nothing here needs an administrator - everything it removes is this user's.

    -Yes   remove the app without the first question (the data question is still asked)
#>
[CmdletBinding()]
param([switch]$Yes)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Name = "CamTrap Measure"
$Dir = Split-Path -Parent $PSScriptRoot
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CamTrapMeasure"
$Data = Join-Path $env:USERPROFILE ".camtrap-measure"

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

if (-not (Test-Path $Dir)) {
    Remove-Item $Key -Recurse -Force -ErrorAction SilentlyContinue
    Tell "$Name was already removed from this computer."
    exit 0
}

$size = 0
try { $size = (Get-ChildItem $Dir -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } catch {}
if (-not $Yes) {
    # the format runs on the whole message, so the concatenation is closed before -f is applied
    $ask = ("Remove $Name from this computer?`r`n`r`nThis deletes the app and its software in`r`n$Dir " +
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

try {
    Remove-Item $Dir -Recurse -Force
} catch {
    Tell ("Most of $Name is removed, but some files in`r`n$Dir`r`ncould not be deleted ($($_.Exception.Message)). " +
          "Restart the computer and delete that folder by hand.")
    exit 1
}

if (Test-Path $Data) {
    $dsize = 0
    try { $dsize = (Get-ChildItem $Data -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum } catch {}
    $ask = ("Also delete your measurements and the downloaded models?`r`n`r`n$Data ({0:N1} GB)`r`n`r`n" +
            "This cannot be undone. Answer No to keep them for a future install.") -f ($dsize / 1GB)
    $also = Ask $ask ([System.Windows.Forms.MessageBoxIcon]::Warning)
    if ($also) { Remove-Item $Data -Recurse -Force -ErrorAction SilentlyContinue }
}

Tell "$Name has been removed."
