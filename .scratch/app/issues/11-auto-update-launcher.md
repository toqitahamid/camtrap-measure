# 11 — Auto-update launcher

**What to build:** Launching the app first upgrades it to the latest published version from the Git remote (via uv), then starts; offline it skips the upgrade and runs the current version. The running version is visible in the UI, and a bad release can be escaped by pinning the launcher to a known-good tag.

**Blocked by:** 02 — Walking skeleton.

**Status:** ready-for-agent

- [ ] Launcher upgrades from the Git remote when online; failure or offline falls through to current version
- [ ] Version string visible in the UI
- [ ] Weights are not part of code updates (manifest handles them separately)
- [ ] Pinning the launcher to a tag is documented as the rollback path
