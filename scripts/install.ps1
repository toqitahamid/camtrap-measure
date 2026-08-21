# CamTrap Measure installer for the department's Windows machine. Run by install.bat, or directly:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Installs Git and uv (winget), clones the app, builds its environment (CUDA torch comes from the lockfile),
# runs the preflight checks (GPU, disk, network, weights token, FlagLabel login — each failure explains its
# fix), puts a shortcut on the desktop and starts the app. Safe to run again: every step is a no-op when done.
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/toqitahamid/camtrap-measure.git"
$Dir = if ($env:CAMTRAP_INSTALL_DIR) { $env:CAMTRAP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "CamTrapMeasure" }

function Step($msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host ""; Write-Host "STOPPED: $msg" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
function RefreshPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Need($exe, $wingetId, $what) {
    if (Get-Command $exe -ErrorAction SilentlyContinue) { Write-Host "$what is installed."; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "$what is not installed and winget is missing. Install $what by hand (see the README), then run this again."
    }
    Step "Installing $what"
    winget install --exact --id $wingetId --accept-source-agreements --accept-package-agreements --silent --disable-interactivity
    if ($LASTEXITCODE -ne 0) { Fail "winget could not install $what (exit code $LASTEXITCODE). Install $what by hand (see the README), then run this again." }
    RefreshPath
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Fail "$what was installed but is not on the PATH yet. Close this window, open a new one, and run the installer again."
    }
}

Step "Checking tools"
Need git Git.Git "Git"
Need uv astral-sh.uv "uv"

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
