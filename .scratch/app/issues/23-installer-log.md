# 23 — A failed install leaves something to send

**What to build:** A department user, 2026-09-03, hit *"This machine is not ready yet. The details pane
lists what to fix; fix it and run the installer again."* at the preflight step. He is not a developer, he
could not find the fix, and all he could email was a screenshot of the message box: the details pane went
with the window the moment he clicked OK, and nothing was left on disk. Every run must write the pane to a
log file, and a failure must leave the window open so the pane can still be read.

**Blocked by:** 18 — Installer and launcher.

**Status:** done (2026-09-03) — 245 passed, 1 skipped; install.ps1 parses; the log header and the machine
block were run on their own on the workstation; the failure path itself is a Windows
window and was read by hand, not run (the installer clones and syncs gigabytes).

## The log

`%LOCALAPPDATA%\CamTrapMeasure-setup.log`, written by every run in both the window and `-Console` mode,
overwritten each time so the file is always the last run and nothing else. It holds exactly what the
details pane holds: a first line with the date, time and the version already on the machine, then every
`Detail` line, every `== step` line and the `STOPPED:` line if there is one.

The Hugging Face token is not in it. `Ask-Token` has never echoed the token to the pane, and the log is
fed from the pane, so keeping it out of the pane keeps it out of the file.

## The machine, written down

The researcher has never seen the department's workstations and nobody had written their hardware down
(HANDOFF open item 2, "collect dept hardware facts at first install"). So the log opens with a short
block, shown in the details pane as well: computer name, Windows edition and build, processor, memory,
graphics adapters, and the free and total space on every fixed drive. Each fact is asked for on its own
inside a try/catch and says "unknown" if the query fails, because none of it is needed to install
anything and none of it may stop an install. Parts and sizes only: no user names beyond the ones already
in the paths the installer prints.

## The window after a failure

`Fail` used to append `STOPPED: …` to the pane, show a message box, and close the form as soon as OK was
clicked. The message box says what went wrong in one sentence; the pane says which check failed and why,
and that is the part a researcher needs. So the message box now ends by naming the log file, and after OK
the form stays on screen with "Stopped." under the mark, running its own message loop
(`[System.Windows.Forms.Application]::Run($Form)`), until the user closes it. Then `exit 1` as before.
