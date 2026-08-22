# CamTrap Measure installer for the department's Windows machine. Run by install.bat, or directly:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Gets Git and uv without an administrator (a portable Git unpacked into the user profile, uv's own user-scope
# installer), clones the app, builds its environment (CUDA torch comes from the lockfile), runs the preflight
# checks (GPU, disk, network, weights token, FlagLabel login — each failure explains its fix), puts a shortcut on
# the desktop and starts the app. Safe to run again: every step is a no-op when done. Nothing here needs admin
# rights: the dept machines have none (2026-08-21).
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest's progress bar slows downloads badly on PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Repo = "https://github.com/toqitahamid/camtrap-measure.git"
$Dir = if ($env:CAMTRAP_INSTALL_DIR) { $env:CAMTRAP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "CamTrapMeasure" }
# Portable Git (MinGit: no installer, no registry, no admin). run.bat puts the same folder on the PATH at every start.
$MinGitUrl = "https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/MinGit-2.51.0-64-bit.zip"
$MinGitDir = Join-Path $env:LOCALAPPDATA "Programs\MinGit"
$UvBin = Join-Path $env:USERPROFILE ".local\bin"  # where uv's installer puts uv.exe

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "STOPPED: $msg" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
function AddPath($p) { if ((Test-Path $p) -and (($env:Path -split ";") -notcontains $p)) { $env:Path = "$p;" + $env:Path } }

Step "Checking tools (nothing here needs an administrator)"
AddPath (Join-Path $MinGitDir "cmd")
AddPath $UvBin
if (Get-Command git -ErrorAction SilentlyContinue) { Write-Host "Git is installed." } else {
    Step "Getting a portable Git into $MinGitDir (40 MB)"
    $zip = Join-Path $env:TEMP "MinGit.zip"
    try { Invoke-WebRequest -Uri $MinGitUrl -OutFile $zip } catch { Fail "Could not download Git from $MinGitUrl ($($_.Exception.Message)). Check the internet connection (github.com must be reachable), then run this again." }
    Expand-Archive -Path $zip -DestinationPath $MinGitDir -Force
    Remove-Item $zip
    AddPath (Join-Path $MinGitDir "cmd")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "Git was unpacked into $MinGitDir but git.exe is not there. Delete that folder and run this again." }
}
if (Get-Command uv -ErrorAction SilentlyContinue) { Write-Host "uv is installed." } else {
    Step "Installing uv into $UvBin"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    AddPath $UvBin
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Fail "uv did not install. Check the internet connection (astral.sh must be reachable), then run this again." }
}

Step "Getting the app into $Dir"
if (Test-Path (Join-Path $Dir ".git")) {
    Write-Host "Already here; run.bat updates it at every start (and honours ref.txt)."
} else {
    git clone --quiet $Repo $Dir
    if (-not $?) { Fail "Could not download the app from $Repo. Check the internet connection (github.com must be reachable)." }
}
Set-Location $Dir

Step "Building the app's environment"
uv sync --frozen
if (-not $?) { Fail "The environment could not be built. Check the internet connection and disk space, then run this again." }

Step "Checking this machine (before the big download)"
uv run --frozen camtrap-measure --preflight
if (-not $?) { Fail "Fix the points above, then run the installer again." }

Step "Installing the models' software (a few GB - the CUDA build of PyTorch - please wait)"
uv sync --frozen --extra inference
if (-not $?) { Fail "The GPU software could not be installed. Check the internet connection and disk space, then run this again." }
uv run --frozen python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if ($?) { Write-Host "PyTorch sees the GPU." } else {
    Write-Host "WARNING: PyTorch does not see a GPU. The app will run on the CPU, many times slower. Reboot if you just installed a driver; see the GPU line above." -ForegroundColor Yellow
}

Step "Desktop shortcut"
$Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrap Measure.lnk"))
$Shortcut.TargetPath = Join-Path $Dir "run.bat"
$Shortcut.WorkingDirectory = $Dir
$Shortcut.Description = "CamTrap Measure"
$Shortcut.Save()
Write-Host "Created 'CamTrap Measure' on the desktop."

Step "Starting the app (first start downloads the model weights; the window shows the progress)"
Start-Process -FilePath (Join-Path $Dir "run.bat") -WorkingDirectory $Dir
Write-Host "Done. From now on, double-click 'CamTrap Measure' on the desktop."
