# 11 — Auto-update launcher

**What to build:** Launching the app first upgrades it to the latest published version from the Git remote (via uv), then starts; offline it skips the upgrade and runs the current version. The running version is visible in the UI, and a bad release can be escaped by pinning the launcher to a known-good tag.

**Blocked by:** 02 — Walking skeleton.

**Status:** done (2026-08-20) — launcher = git fetch/checkout REF + uv run; the .bat cannot run on Linux; ACCEPTANCE = the installer's first launch on the dept machine (ticket 12) must show the update, an offline launch, and a ref.txt rollback

- [x] Launcher upgrades from the Git remote when online; failure or offline falls through to current version
- [x] Version string visible in the UI
- [x] Weights are not part of code updates (manifest handles them separately)
- [x] Pinning the launcher to a tag is documented as the rollback path
