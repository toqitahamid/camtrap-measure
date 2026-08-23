@echo off
rem CamTrap Measure installer. Double-click on a fresh Windows machine (or to repair an install).
rem
rem The work is in scripts\install.ps1, which puts up a window of its own. This file hands it to wscript
rem so that window is the only thing on screen - a console behind it would be noise. For the steps in a
rem console instead: powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Console
start "" "%SystemRoot%\System32\wscript.exe" "%~dp0scripts\setup.vbs"
