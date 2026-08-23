@echo off
rem CamTrap Measure, with its steps in a console - the way in when something needs looking at.
rem
rem The desktop shortcut does NOT use this file: it runs scripts\launch.vbs, which starts the same
rem launcher with no console at all. This one exists for troubleshooting, and takes the launcher's
rem switches: -NoUpdate, -NoStart.
rem
rem The update, the offline fallback, the rollback to the previous version and ref.txt all live in
rem scripts\launcher.ps1 now. PowerShell reads a script whole before running it, so a checkout that
rem rewrites the launcher mid-run is harmless - which is why the update moved out of this file.
rem
rem cmd, on the other hand, re-reads a .bat by byte offset while it runs, and the checkout below can
rem rewrite this very file. So the call is the last line, and it ends by exiting. Keep it that way.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1" -Console %* & exit /b
