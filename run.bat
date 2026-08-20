@echo off
rem CamTrap Measure launcher. Double-click to start.
cd /d "%~dp0"
uv run camtrap-measure
if errorlevel 1 pause
