# CamTrap Measure

Windows desktop app: distance to each white-tailed deer in camera-trap photos.
Design context in `CONTEXT.md`; spec and tickets in `.scratch/app/`.

## Run (department machine, Windows)

Double-click `run.bat`. Needs [uv](https://docs.astral.sh/uv/) installed.

## Develop

```sh
uv run camtrap-measure --no-window   # engine only, prints the URL (Linux-friendly)
uv run pytest                        # API tests, no GPU needed
cd frontend && npm install && npm run build   # rebuild UI into src/camtrap_measure/ui/
```

The built UI is committed so `uv run` from a fresh clone works without Node.
Rebuild and commit it whenever `frontend/` changes.

Local state (cached login session, SQLite mirror of cloud annotations/sites)
lives in `~/.camtrap-measure/`; override with `CAMTRAP_DATA_DIR`.

Supabase is read-only from this app: `supabase_ro.py` is the only client and
exposes auth plus three reads; `tests/test_supabase_ro.py` enforces it.
