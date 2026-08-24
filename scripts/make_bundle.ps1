<#
  Builds the folder you hand to the wildlife team: the installer, plus the model weights.

      powershell -ExecutionPolicy Bypass -File scripts\make_bundle.ps1
      powershell -ExecutionPolicy Bypass -File scripts\make_bundle.ps1 -Out E:\CamTrapMeasure

  Why this exists: the weights live in a private Hugging Face repo, and the only way for a team machine
  to download them is a read token. Handing that token to twelve people is handing out a credential that
  cannot be taken back from any one of them. So the models travel with the installer instead, on a USB
  stick or a share, and no team machine ever needs an account.

  The result is about 6.5 GB and installs by double-click. The app itself still comes from GitHub during
  the install, which is public, so the machine needs the internet - it just needs no credentials.

  Weights are not code (CLAUDE.md): this writes a distributable, never anything that goes into git.
#>
[CmdletBinding()]
param(
    [string]$Out = (Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrapMeasure-Installer"),
    [string]$WeightsDir = (Join-Path $env:USERPROFILE ".camtrap-measure\weights")
)

# Deliberately no -Zip. Windows PowerShell 5.1's Compress-Archive fails above 2 GB, and this folder is
# over 6 GB; model weights are already compressed, so a zip would spend twenty minutes to save nothing
# and then break at the end. Copy the folder to the stick or the share as it is.

$ErrorActionPreference = "Stop"
$here = Split-Path $PSCommandPath -Parent

function Say($msg) { Write-Host $msg }

if (-not (Test-Path (Join-Path $WeightsDir "manifest.json"))) {
    throw "No weights in $WeightsDir. Start the app once on this machine so it downloads them, or pass -WeightsDir."
}
$version = (Get-Content (Join-Path $WeightsDir "manifest.json") -Raw | ConvertFrom-Json).version
$size = (Get-ChildItem $WeightsDir -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Say "Weights $version, $([math]::Round($size, 2)) GB, from $WeightsDir"

# Refuse to ship a token by accident: config.json lives next to the weights folder and holds one.
$stray = Get-ChildItem $WeightsDir -Recurse -File -Include "config.json", "*.token", "token" -ErrorAction SilentlyContinue |
         Where-Object { (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue) -match "hf_[A-Za-z0-9]{10}" }
if ($stray) { throw "A Hugging Face token is inside the weights folder ($($stray[0].FullName)). Remove it before bundling." }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
Say "Building $Out"

# The installer scripts, and nothing else from the repo: the app itself is cloned from GitHub at install
# time, so the bundle does not go stale every time a line of the app changes.
$scripts = Join-Path $Out "scripts"
New-Item -ItemType Directory -Force -Path $scripts | Out-Null
foreach ($f in "install.ps1", "setup.vbs") { Copy-Item (Join-Path $here $f) $scripts -Force }

Say "Copying the weights (this is the slow part)"
$null = & robocopy $WeightsDir (Join-Path $scripts "weights") /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) copying the weights." }

# One thing to double-click. wscript, so no console window appears behind the installer's own window.
@"
@echo off
rem CamTrap Measure - double-click this to install the app and its models on this computer.
rem Nothing here needs an administrator, and nothing here asks for a password or a token.
start "" "%SystemRoot%\System32\wscript.exe" "%~dp0scripts\setup.vbs"
"@ | Set-Content (Join-Path $Out "INSTALL.bat") -Encoding ascii

@"
CamTrap Measure - installer for the wildlife team
=================================================

Models included: version $version. No Hugging Face account or token is needed on this computer.

To install:
  1. Copy this whole folder onto the computer (or plug in the stick and run it from there).
  2. Double-click INSTALL.bat.
  3. Follow the window. It needs no administrator and asks for no password.
  4. When it finishes, the app starts and asks for the email address of your FlagLabel account.
     A one-time code is emailed to you - type it in. There is no password.

What this computer needs:
  - Windows 11, and an internet connection for the install (the app itself downloads from GitHub).
  - An NVIDIA graphics card, driver version 570 or newer. Without one the app still runs, on the
    processor instead, many times slower.
  - 20 GB of free disk space.

If something goes wrong the installer says what to do in plain words, and it is safe to run again -
running it a second time repairs a half-finished install rather than starting over.

Two things worth knowing when you use it:
  - The first measurement of each session waits 20-30 seconds while the models load. That is normal;
    the app deliberately holds no graphics memory when it is idle.
  - Close Chrome and Teams while measuring. On a shared graphics card it is worth two to three times
    the speed, and it is the one thing you control.
"@ | Set-Content (Join-Path $Out "README.txt") -Encoding utf8

$total = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Say "Done: $Out  ($([math]::Round($total, 2)) GB)"

Say ""
Say "Hand the folder over as it is. The team double-clicks INSTALL.bat; nobody needs a token."
