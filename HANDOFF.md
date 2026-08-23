# Handoff: continuing CamTrap Measure on the Windows workstation

Written 2026-08-21 on the HPC (Linux, aarch64). Everything below is verified against GitHub
unless marked *unverified*. Read `CONTEXT.md` for the *why* of every design decision and
`.scratch/app/` for the spec and tickets; this file is only the *how to pick it up*.

## 1. What is where on GitHub

| repo | URL | branch @ commit | visibility | role |
|---|---|---|---|---|
| camtrap-measure | https://github.com/toqitahamid/camtrap-measure | `main` @ `a9b9476` | public | **this app** (tickets 01–13 done) |
| distance_estimation | https://github.com/toqitahamid/distance_estimation | `master` @ `6a6eed5` | private | research code the app ports from (`calib/`, `transport/`, unified net) |
| camtrap-distance | https://github.com/toqitahamid/camtrap-distance | `main` @ `5b6436b` | private | public-release repo of the paper method; its own git repo, *gitignored* inside `distance_estimation/` |

All three are clean and fully pushed. No symlinks, no LFS, no >100 MB files, no
Windows-hostile names in any of them. `distance_estimation/.git` is 778 MB (clone takes a
minute).

Private repos are invisible to any GitHub account but `toqitahamid` — if a URL 404s in the
browser, you are signed in as someone else.

## 2. Clone layout (keep it — relative paths depend on it)

```powershell
# once: credentials for the private repos (use the toqitahamid account)
winget install GitHub.cli
gh auth login

cd D:\research          # any folder; the two app/research repos must be siblings
git clone https://github.com/toqitahamid/distance_estimation.git
git clone https://github.com/toqitahamid/camtrap-distance.git distance_estimation\camtrap-distance
git clone https://github.com/toqitahamid/camtrap-measure.git
```

`camtrap-measure/CONTEXT.md` and `src/camtrap_measure/distance.py` cite
`../distance_estimation@6a6eed5` as the source of the ported math; `distance_estimation/.gitignore`
expects `camtrap-distance/` inside it.

Things that do **not** travel with the clones (HPC-only, recreate only if you need them):

- `distance_estimation/release/` (2.6 GB checkpoints + dataset staging, ignored) and the
  `camtrap-distance/data` symlink that points into it; `camtrap-distance/outputs/` (101 MB).
- `distance_estimation/depthenv/`, `data/`, `finetune/ckpt_*` weights — research venv and bulk data.
- Nothing from camtrap-measure: the app's weights come from Hugging Face at first start, not git.

## 3. Two ways to run camtrap-measure on Windows

### A. As the department will (acceptance test — never yet run on real Windows)

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/toqitahamid/camtrap-measure/main/scripts/install.ps1 | iex"
```

No administrator needed: portable Git (MinGit) into `%LOCALAPPDATA%\Programs\MinGit`, uv via its
own user-scope installer, clone into `%LOCALAPPDATA%\CamTrapMeasure`, `uv sync --frozen`
(Python 3.12 from `.python-version`), preflight checks, `uv sync --frozen --extra inference`
(torch 2.11 **cu128 from the lockfile** — a few GB), desktop shortcut to `run.bat`, first launch
(~6.5 GB weights download with a progress bar). It asks for the HF read token and the FlagLabel
email + the one-time code FlagLabel emails (no passwords — ticket 14).

Run on the workstation 2026-08-21 (CONTEXT "Windows acceptance"): everything above passed
except the steps that need a FlagLabel mailbox (preflight login, the window's sign-in) — those
are unit-tested and must be tried once by a real user.

### B. As a developer (your clone from §2)

```powershell
winget install astral-sh.uv OpenJS.NodeJS.LTS    # Git already there
cd camtrap-measure
uv sync --frozen --extra inference               # Python 3.12 venv + CUDA torch (lockfile)
uv run pytest                                    # 148 passed, 2 skipped on the HPC; GPU not needed
uv run camtrap-measure                           # pywebview window (WebView2)
uv run camtrap-measure --no-window               # engine only, prints the URL — open in a browser
cd frontend; npm ci; npm run build               # rebuild UI into src/camtrap_measure/ui/ (commit it)
```

- Weights token: `HF_TOKEN` env var or `%USERPROFILE%\.camtrap-measure\config.json`
  `{"hf_token": "hf_..."}` — read access to the private HF repo `toqi/camtrap-measure-weights`.
  Without it the engine runs the `fake` backend and the UI says so.
- Local state (login session, annotations mirror, results SQLite, weights, cached flag photos):
  `%USERPROFILE%\.camtrap-measure\` (override with `CAMTRAP_DATA_DIR`). Delete it for a fresh start.
- `CAMTRAP_WEIGHTS_DIR=<folder>` pins a ready-made weights folder and skips the hub.
- `CAMTRAP_FAKE_DELAY=0.3` slows the fake backend so the progress UI is visible.
- The GPU smoke test (`tests/test_gpu_smoke.py`) needs `CAMTRAP_WEIGHTS_DIR`,
  `CAMTRAP_SMOKE_PHOTO`, `CAMTRAP_SMOKE_FLAG` (a flag photo + its `.json`); README "GPU smoke test".

Both A and B can coexist; they are separate clones and share only `~/.camtrap-measure/`.

## 4. How the project is worked (keep the same loop)

- **`CONTEXT.md`** = the decision record. Every ticket appends a section with its verdicts and
  their reasons. Change a decision only with a reason that beats the recorded one.
- **Tickets**: `.scratch/app/spec.md` + `.scratch/app/issues/NN-slug.md`, one file per ticket,
  `Status:` line near the top (`ready-for-agent` → `done (date) — evidence`). Conventions in
  `../distance_estimation/docs/agents/issue-tracker.md`. Tickets 01–13 are done.
- Claude Code workflow used so far: `/mattpocock-skills:implement .scratch/app/issues/NN-*.md`
  (TDD where a seam exists, `tsc`/`oxlint`/`vite build`, full `pytest`, two-axis
  `/mattpocock-skills:code-review`, commit). Plugins: superpowers, mattpocock-skills, caveman,
  ponytail. Any Claude Code install with those plugins reproduces it; nothing is HPC-specific.
- Hard rules (tested): Supabase is read-only — `supabase_ro.py` is the only client
  (`tests/test_supabase_ro.py` enforces it). Frontend stays dumb: no router, no state lib.
  Built `ui/` is committed; rebuild + commit whenever `frontend/` changes.
- Release = bump `version` in `pyproject.toml`, push `main`, optionally tag. The dept machine
  picks it up at the next launch (`run.bat`). Rollback = `ref.txt` beside `run.bat`.
- `distance_estimation` rule: append a dated entry to `docs/implementation-notes.md` after any
  change there (its `CLAUDE.md`).

## 5. Credentials you will need

- GitHub: `toqitahamid` (private repos).
- Hugging Face: a **read** token for `toqi/camtrap-measure-weights`; `scripts/upload_weights.py`
  needs a write token (only when changing weights; bump `VERSION` there).
- Supabase/FlagLabel: a department user account (email; sign-in is by one-time code emailed by
  Supabase — no passwords); the app uses it through the read-only wrapper. Project
  `uggjzcbozdxvuawxddrn` — no service key anywhere, keep it that way.

## 6. What is next (from `CONTEXT.md` open items)

1. **First real measurement**: Sync in the window, check the camera verdicts, run one folder
   of real photos (sign-in by email code verified 2026-08-23). Then tag `v0.1.0` as the first
   `ref.txt` rollback target.
2. Collect dept hardware facts at first install (GPU model, photo volume) — open item 3. The
   workstation used for acceptance: RTX 2060 SUPER 8 GB, driver 581.95, Windows 11.
3. MD-only vs MD+SAM3 comparison on existing labeled data in `distance_estimation` → sets
   `DEFAULT_METHOD` (`inference.py`); note the RoMa run-to-run spread recorded under ticket 08
   must be pinned first (fixed seed or averaged draws).
4. Distance-ready export (Q12b) after the first season with a statistician.
5. Known deferrals marked `ponytail:` in the code (`grep -rn "ponytail:" src frontend/src`):
   native folder picker, manual theme toggle, etc.

## 7. Gotchas seen on the HPC that may differ on Windows

- `gh` on the HPC needed `env -u GITHUB_TOKEN` (a stale token in the environment). On Windows a
  plain `gh auth login` is enough.
- `uv sync --frozen` must be `--extra inference` on Windows or it *removes* the GPU packages.
- `romatch` is a git dependency pinned to RoMa@77f8d68; it pulls `poselib`, whose win64 cp312
  wheel resolves from the lockfile (verified 2026-08-21). What did *not* resolve was `onnx`
  (see `[tool.uv] override-dependencies` in `pyproject.toml`).
- A developer machine with a cached Hugging Face login (`~/.cache/huggingface/token`) gives the
  app weights access even without `hf_token`; the test suite is pinned offline so it cannot.
- The dept machines have no administrator rights: nothing in the installer may need elevation.
- Capture dates are naive local time; Windows locale affects only the UI's `toLocaleString`.
- pywebview needs the WebView2 runtime (built into Windows 11; preflight names the download).
