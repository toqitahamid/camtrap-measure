# 21 — The models travel with the installer, so nobody gets a token

**What to build:** The researcher, 2026-08-24: *"i want to put eveything as an installer including the
weight files, dont want to share hf token"*, and *"the system we will install dont have admin acess so
make sure it will work for all users"*.

**Blocked by:** 12 — Guided installer; 18 — Installer and launcher.

**Status:** done (2026-08-24) — 226 tests green; the bundle builder verified end to end against a
stand-in weights folder, including its refusal to ship a token. **The bundled install path itself has
not been run on a second machine yet** — see "Not done".

## The decision

The weights are in a private Hugging Face repo, and the only way for a team machine to download them is
a read token. Handing that token to a dozen people hands out a credential that cannot be taken back
from any one of them, and lives on in a dozen `config.json` files. So the department is given the
**models**, not the means to fetch them: `scripts/make_bundle.ps1` builds a ~6.5 GB folder holding the
installer and the weights, the installer copies them into place, and no team machine ever has a token.

The **app** still comes from GitHub during the install, which is public, so the machine needs the
internet — it just needs no credentials. Choosing this over a fully offline bundle (which would also
have to carry the 5.4 GB CUDA environment and a seeded uv cache) was the researcher's call: half the
size, and far less new machinery to fail on a machine nobody can reach.

## The quiet failure this avoids

A machine with no token that asks the private repo anyway gets a **401**, which the code reports as
*"the weights repo rejected the access token — check hf_token in config.json"*. On a bundled machine
that warning would be permanent, wrong, and on screen for ever.

So the installer writes `"weights_from": "bundle"` into `config.json`, and `weights.ensure` skips the
hub entirely when it sees it. **Said, never guessed:** a developer machine has no token either and
still reaches the hub through a cached `huggingface-cli` login, and must go on picking up new weights
versions (HANDOFF gotchas). Inferring "bundled" from the absence of a token silently broke that — the
existing tests caught it, which is why they are worth having.

A token, if someone does supply one, still wins over the marker.

## No administrator, one person per machine

Unchanged from ticket 18 and still true: portable Git in the user profile, uv's user-scope installer,
the app under `%LOCALAPPDATA%`, shortcuts and the Settings entry all per-user. Nothing in the bundle
needs elevation and nothing asks for a password.

Without an administrator there is no such thing as a machine-wide install, so this is **one install per
Windows user**, which the researcher confirmed matches the deployment (one person per PC). If a machine
is ever shared, the shape to reach for is a copy under `C:\Users\Public` (writable without admin) with
each user running the installer to get their own shortcuts — `CAMTRAP_INSTALL_DIR` already allows it.

## Deliberately not zipped

Windows PowerShell 5.1's `Compress-Archive` fails above 2 GB, and this folder is over 6. Model weights
are already compressed, so a zip would spend twenty minutes saving nothing and then break at the very
end of the build. The folder is copied to the stick or the share as it is.

## Not done

**Nobody has run the bundled install on a machine that did not already have everything.** The builder
is verified, the app-side logic is unit-tested, the installer's branch is contract-tested — but the
6.5 GB copy, the skipped token box and the first start with `weights_from` set have never happened on a
cold machine. **ponytail:** run it on a second machine before it goes to the team, and budget an hour.
