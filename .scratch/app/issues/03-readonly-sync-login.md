# 03 — Read-only sync and login

**What to build:** A technician signs in with their existing FlagLabel account, presses Sync, and the app pulls all flag annotations and the camera registry into the local database. Offline, Sync degrades to a polite "offline — using data from last sync <date>" notice. The app is structurally unable to write to Supabase.

**Blocked by:** 02 — Walking skeleton.

**Status:** ready-for-agent

- [ ] Login screen using Supabase email auth; session cached so sign-in is rare
- [ ] Sync pulls annotations (schema-v2 JSON) and sites into local SQLite
- [ ] Supabase wrapper exposes exactly three read operations; no write method exists
- [ ] Guard test: wrapper surface is read-only and it is the only client construction site
- [ ] Offline sync shows last-sync date instead of an error
- [ ] Re-sync picks up new and re-labeled annotations (upsert by site + image)
