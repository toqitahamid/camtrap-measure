# 24 — Install where the user chooses

**What to build:** A department machine failed the 20 GB free-space check on 2026-09-25: everything went on
C: (the app and its environment in `%LOCALAPPDATA%\CamTrapMeasure`, about 7 GB of models and the results in
`%USERPROFILE%\.camtrap-measure`, uv's cache in `%LOCALAPPDATA%\uv\cache`). The researcher: "how about
installing it on my chosen location that I select on the installing time". The installer asks where, and
everything big goes under that one folder.

**Blocked by:** 18 — Installer and launcher; 23 — the setup log.

**Status:** done (2026-09-25) — 260 passed, 1 skipped; install.ps1, launcher.ps1 and uninstall.ps1 parse;
the folder resolution, the write test (D:\ct-test accepted, C:\Windows\System32 refused and left
untouched), the repair detection on the workstation (its pre-24 install found, nothing asked) and the
dialog's construction were run in a harness; the whole installer was not run.

## The question

Window mode, before anything is written: a small dialog in the installer's colours, "Where should CamTrap
Measure be installed?", a text box, Browse... (FolderBrowserDialog), a line that follows the typing with
the final folder and the free space on its drive (amber, not a stop, under 20 GB), Install and Cancel.
The answer is a parent: `D:\` becomes `D:\CamTrapMeasure`; a folder already named CamTrapMeasure is used
as it is. Suggested: `D:\` when D: is a local disk with more room than C:, else `%LOCALAPPDATA%` (or the
place a previous, unfinished run chose). Cancel exits 0 with nothing made. `-Console` asks with Read-Host,
Enter takes the suggestion. `-InstallTo <path>` or `CAMTRAP_INSTALL_DIR` skip the question.

The choice is proved by making the folder and writing a file in it; on failure the reason is shown in
plain words and the question comes back.

## The layout

Under the chosen folder R: `R\app` (the clone), `R\data` (`CAMTRAP_DATA_DIR`: weights, config.json,
results), `R\uv-cache` (`UV_CACHE_DIR`), `R\python` (`UV_PYTHON_INSTALL_DIR`). Portable Git and uv.exe stay
where they were. The three variables are saved in the user scope (no administrator) and set in the
installer's own process; the launcher reads them back from the user scope at every start.

## Repair

When Settings > Apps knows an install folder that exists (or an old clone sits in
`%LOCALAPPDATA%\CamTrapMeasure`), the installer repairs it there with no question. An install from before
this ticket keeps its app and data exactly where they are.

## Uninstall

Finds the data through `CAMTRAP_DATA_DIR` (else the default), removes `R\app`, `R\uv-cache` and
`R\python` with the app, then the variables that point inside R, then asks about the data, and removes R
when it is empty.

## Also: the publisher

Settings > Apps now lists the publisher as "BASE Lab, SIU Carbondale" (was "Southern Illinois University"),
at the researcher's request. An existing install picks it up the next time the installer runs.
