<#
  CamTrap Measure installer for the department's Windows machines.

    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
    scripts\install.bat            (the same thing by double-click)
    install.ps1 -Console           the steps in the console instead of a window

  It runs in a window: the steps tick past, the details pane holds what each one printed, and a failure
  says what to do about it in plain words. Nothing here needs an administrator - the dept machines have
  none (2026-08-21): a portable Git in the user profile, uv's user-scope installer, the app under
  %LOCALAPPDATA%, shortcuts and the Settings > Apps entry all per-user.

  Safe to run again: every step is a no-op when it is already done, so this is also the repair path.
#>
[CmdletBinding()]
param([switch]$Console)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest's progress bar slows downloads badly on PowerShell 5
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "https://github.com/toqitahamid/camtrap-measure.git"
$Dir = if ($env:CAMTRAP_INSTALL_DIR) { $env:CAMTRAP_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "CamTrapMeasure" }
# Portable Git (MinGit: no installer, no registry, no admin). The launcher puts the same folder on the PATH.
$MinGitUrl = "https://github.com/git-for-windows/git/releases/download/v2.51.0.windows.1/MinGit-2.51.0-64-bit.zip"
$MinGitDir = Join-Path $env:LOCALAPPDATA "Programs\MinGit"
$UvBin = Join-Path $env:USERPROFILE ".local\bin"  # where uv's installer puts uv.exe
$Name = "CamTrap Measure"
$Key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CamTrapMeasure"
$Ico = Join-Path $Dir "src\camtrap_measure\assets\camtrap-measure.ico"
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"

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
    $sub.Text = "Installing into $Dir. Nothing here needs an administrator."
    $sub.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $sub.ForeColor = [System.Drawing.ColorTranslator]::FromHtml("#8A929C")
    $sub.SetBounds(26, 52, 600, 20)
    $Form.Controls.Add($sub)

    $StepLabel = New-Object System.Windows.Forms.Label
    $StepLabel.Text = "Starting…"
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

function Detail($text) {
    if ($null -eq $text) { return }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line.Trim() -eq "") { continue }
        if ($Details) {
            $Details.AppendText("$line`r`n")
        } else {
            Write-Host "   $line"
        }
    }
    Pump
}

function Step($msg) {
    $script:Done += 1
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
    if ($Form) {
        $StepLabel.Text = "Stopped."
        $Details.AppendText("STOPPED: $msg`r`n")
        [System.Windows.Forms.MessageBox]::Show($msg, "$Name Setup",
            [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
        $Form.Close()
    } else {
        Write-Host ""
        Write-Host "STOPPED: $msg" -ForegroundColor Red
        Read-Host "Press Enter to close" | Out-Null
    }
    exit 1
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
            $lines = @(Get-Content $out -ErrorAction SilentlyContinue)
            if ($lines.Count -gt $shown) {
                Detail ($lines[$shown..($lines.Count - 1)] -join "`r`n")
                $shown = $lines.Count
            }
        }
    }
    if (Test-Path $out) {
        $lines = @(Get-Content $out)
        if ($lines.Count -gt $shown) { Detail ($lines[$shown..($lines.Count - 1)] -join "`r`n") }
    }
    if (Test-Path $err) { Detail (Get-Content $err -Raw) }
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
    Detail "Getting a portable Git into $MinGitDir (40 MB)…"
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
    Detail "Installing uv into $UvBin…"
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
$cfg = Join-Path $env:USERPROFILE ".camtrap-measure\config.json"
$hasToken = (Test-Path $cfg) -and ((Get-Content $cfg -Raw) -match '"hf_token"\s*:\s*"\S')
if (-not $hasToken) {
    $token = Ask-Token
    if ($token) { $env:HF_TOKEN = $token }
}

Step "Checking this machine (before the big download)"
if ((Run "uv" @("run", "--frozen", "camtrap-measure", "--preflight", "--no-prompt") $Dir) -ne 0) {
    Fail "This machine is not ready yet. The details pane lists what to fix; fix it and run the installer again."
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
New-ItemProperty -Path $Key -Name "Publisher" -Value "Southern Illinois University" -Force | Out-Null
New-ItemProperty -Path $Key -Name "InstallLocation" -Value $Dir -Force | Out-Null
New-ItemProperty -Path $Key -Name "UninstallString" `
                 -Value ("$Wscript """ + (Join-Path $Dir "scripts\uninstall.vbs") + """") -Force | Out-Null
New-ItemProperty -Path $Key -Name "NoModify" -Value 1 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $Key -Name "NoRepair" -Value 1 -PropertyType DWord -Force | Out-Null
Detail "Listed in Settings > Apps as $Name $version."

# --- 7. first start ---------------------------------------------------------------------------------
Step "Starting $Name (the first start downloads the models; the window shows the progress)"
Start-Process -FilePath $Wscript -ArgumentList (Join-Path $Dir "scripts\launch.vbs") -WorkingDirectory $Dir
if ($Form) {
    $StepLabel.Text = "$Name is installed. From now on, double-click its icon on the desktop."
    $Details.AppendText("Done.`r`n")
    Pump
    Start-Sleep -Seconds 3
    $Form.Close()
} else {
    Write-Host ""
    Write-Host "Done. From now on, double-click '$Name' on the desktop." -ForegroundColor Green
}
