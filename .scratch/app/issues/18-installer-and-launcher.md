# 18 — It installs and starts like an app, not a script

**What to build:** The researcher, 2026-08-23: *"i would like to make a installer for the app. and why does
everytime i click the desktop shortcut button it opens a command prompt? why not make the app professional"*.
Two faults, one cause: the desktop shortcut points at `run.bat`, so Windows opens a console for cmd.exe and
leaves it there for the whole session, and the install is a command a technician pastes into PowerShell.

**Blocked by:** 11 — Auto-update launcher; 12 — Guided installer; 17 — The window becomes an app.

**Status:** done (2026-08-23) - 189 tests green; the launcher checked hidden and in a console on the workstation, the GUI entry point checked to be PE subsystem 2; the researcher's own double-click is the remaining acceptance

## Why the console appears (the fault being fixed)

1. A `.lnk` whose target is a `.bat` is run by `cmd.exe`, a console program: Windows must give it a console.
2. `run.bat` then runs the app **in the foreground** of that console, so the black window stays for the
   whole session, and closing it kills the app mid-run.
3. `camtrap-measure.exe` is a `[project.scripts]` entry point — a console executable of its own.

## What replaces it

- **A windowless launcher.** The shortcut runs `scripts\launch.vbs` through `wscript.exe` (window style 0:
  no console, and no black flash — `powershell -WindowStyle Hidden` still flashes), which runs
  `scripts\launcher.ps1`. That script owns the update that `run.bat` used to do, shows a splash while it
  works, and reports a failure in a dialog box instead of a `pause`.
- **A GUI entry point.** `[project.gui-scripts] camtrap-measure-app` builds a `pythonw` executable, so the
  app itself can never own a console. The launcher starts that.
- **An icon.** `src/camtrap_measure/assets/camtrap-measure.ico`, drawn from the mark the window already
  uses, on the shortcut, the Start-menu entry, the window and the taskbar.
- **An installer with a window**: a wizard with steps, a progress bar and a details pane, a Start-menu
  entry, an entry in Settings ▸ Apps (per-user, no administrator) and an uninstaller.
- `run.bat` stays as the troubleshooting way in: the same launcher, with its output in a console.

## Acceptance

- [x] Double-clicking the desktop shortcut shows no console window at any point, only the splash and then
      the app window
- [x] The update still happens at every start, still falls back to the installed version offline, and
      still honours `ref.txt`
- [x] A failed update explains itself in a dialog with a way to the log, not a `pause` in a console
- [x] Starting the app twice focuses the window that is already open instead of starting a second engine
- [x] Desktop, Start menu and taskbar show the app icon; the window's title bar and taskbar button do too
- [x] The installer runs in a window with visible steps, and finishes with the app installed, listed in
      Settings ▸ Apps, and removable from there
- [x] Nothing needs an administrator
