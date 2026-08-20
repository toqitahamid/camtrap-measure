# 03 — Read-only sync and login

**What to build:** A technician signs in with their existing FlagLabel account, presses Sync, and the app pulls all flag annotations and the camera registry into the local database. Offline, Sync degrades to a polite "offline — using data from last sync <date>" notice. The app is structurally unable to write to Supabase.

**Blocked by:** 02 — Walking skeleton.

**Status:** done (full sync against real data unverified — needs a dept FlagLabel login)

- [x] Login screen using Supabase email auth; session cached so sign-in is rare
- [x] Sync pulls annotations (schema-v2 JSON) and sites into local SQLite
- [x] Supabase wrapper exposes exactly three read operations; no write method exists
- [x] Guard test: wrapper surface is read-only and it is the only client construction site
- [x] Offline sync shows last-sync date instead of an error
- [x] Re-sync picks up new and re-labeled annotations (upsert by site + image)

## Result

`supabase_ro.py`: plain-REST client (httpx, no SDK) — `sign_in`, `refresh`, `select_annotations`,
`select_sites`, `download_object`. All traffic through one `_send`; the only non-GET is the auth token
grant. Guard tests: surface is exactly those names, source has no write verb, no other module
mentions Supabase/httpx, every data request recorded through a mock transport is a GET.

`store.py`: `~/.camtrap-measure/session.json` (refresh token + email; rotated on every sync) and
`camtrap.db` (sqlite3: `annotations`, `sites`, `meta.last_sync`). Sync replaces the mirror in one
transaction, so re-labels, new rows and cloud deletions all land.

API: `GET /api/status`, `POST /api/login|logout|sync`. Offline sync → `{ok:false, offline:true,
last_sync}`; expired/revoked session → 401 and sign-out. UI: login form ↔ Sync button + last-sync line.

Verified live: engine → wrapper → real Supabase auth round-trips the server's "Invalid login
credentials"; publishable key + RLS confirmed on REST. Full pull needs a real account (314
annotations / 167 sites as of 2026-08-20).

Review follow-ups applied: credential rejections (400/401/403) are the only `AuthError`s, so a 5xx/429
during refresh never signs the user out; cloud 5xx surfaces in the UI as "Sync failed", not as offline;
session file is 0600; guard test also rejects `requests`/`urllib`/SDK imports and any `supabase`
mention in `frontend/src`. Sign out exists (small, natural pair of sign in). Deferred: `schema_version`
check on rows (ticket 04 consumes the JSON and validates there).
