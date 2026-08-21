# CLAUDE.md

Windows desktop app: distance to each white-tailed deer in camera-trap photos. Companion to
cloud FlagLabel; ports the method from `../distance_estimation` (sibling clone).

## Read first

- `HANDOFF.md` — picking the work up on a new machine (repos, clone layout, run/dev commands, credentials, what is next).
- `CONTEXT.md` — the decision record; every ticket's verdicts and their reasons. Change a decision only with a reason that beats the recorded one, and append a dated section when you do.
- `.scratch/app/spec.md` + `.scratch/app/issues/NN-*.md` — spec and one file per ticket (`Status:` line near the top).

## Commands

```sh
uv sync --frozen --extra inference      # env incl. CUDA torch on Windows (never plain --frozen there: it removes the GPU packages)
uv run pytest                           # full suite, no GPU needed
uv run camtrap-measure --no-window      # engine only, prints URL
cd frontend && npm ci && npm run build  # rebuild src/camtrap_measure/ui/ — committed, rebuild whenever frontend/ changes
```

## Rules that bite

- Supabase is read-only from this app: `supabase_ro.py` is the only client; `tests/test_supabase_ro.py` enforces it. No service key, ever.
- Frontend stays dumb: no router, no state library; renders JSON, posts clicks.
- Weights are not code: private HF repo via `weights.py`; never in git.
- Workflow per ticket: `/mattpocock-skills:implement <issue file>` → tests green → `/mattpocock-skills:code-review` → commit; mark the issue `done (date) — evidence` and add the CONTEXT section.
