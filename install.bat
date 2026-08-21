@echo off
rem CamTrap Measure installer. Double-click on a fresh Windows machine (or to repair an install).
rem Everything happens in scripts\install.ps1; this file only gets PowerShell to run it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
if errorlevel 1 pause
