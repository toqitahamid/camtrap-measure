# 0003. The weights repo becomes public, and every install checks it at start

Date: 2026-10-12. Status: accepted; implemented 2026-10-12 on branch `fix/public-weights`, not committed (ticket 36).
The repo itself is made public as a separate step with the user's OK, and must be public before this ships.

## Context

The weights live in the Hugging Face repo `toqi/camtrap-measure-weights`, which was private. Reading a private repo
needs a token, and handing a token to every team machine hands out a credential that cannot be taken back. So
since ticket 21 (2026-08-24) the team gets the weights inside the installer folder (a "bundle"), and the app never
asks the hub on a bundle install (`"weights_from": "bundle"` in config.json, no token).

That made the bundle's weights version permanent. A retrained distance model (Run 2, research folders 69 and 70) is
about to ship, and no bundle install can receive it. The answers already stored also carry no record of which model
read them, so nothing could mark them out of date.

## Decision

User decision, 2026-10-12:

- The repo becomes public. Every install, a bundle install too, asks the hub at start with no token and downloads
  only the files that changed. A token is optional and still sent when set; a token the hub refuses, or a refused
  `hf auth login` that huggingface_hub sends when no token is set, is dropped for that start and the repo is read
  with no token at all.
- `manifest.json` is downloaded last, only after every other file is confirmed at the commit the size check saw, and
  both downloads ask for that commit. An interrupted update keeps the OLD manifest, but files it already downloaded
  may be new: the app may run a mix of old and new files under the old version until the next complete update, which
  then changes the version and redoes the answers.
- The app never downloads SAM3 (`weights.SKIP = ["sam3/*"]`). SAM3 stays in the repo; a `sam3/` folder already on a
  machine is left alone.
- Each answer stores the weights manifest version that read it (`photos.weights_version`). An answer read by another
  version is out of date and Measure all redoes it. Answers stored before this change count as read by
  `LEGACY_WEIGHTS_VERSION` = "2026.08.20c". While the models load, the weights folder's manifest names the running
  version; with no manifest anywhere (Test mode on a machine without weights) no real answer is current, and a Test
  mode run never redoes an answer for its weights version alone. Test mode stamps its answers `NO_WEIGHTS_VERSION`
  even when a manifest is on disk, so a real run redoes them.
- The CSV export is unchanged: stale rows stay in it.

## Consequences

- New weights reach every machine that starts while online. Uploading a new manifest version turns every older
  answer "Out of date" at the next start.
- No credential exists on any team machine, and the installer asks for none.
- Once the repo is public, the weights are public. Each component keeps its own licence, listed on the model card;
  the distance net is CC-BY-NC-4.0 (non-commercial), as its Depth-Anything-V2 base is. SAM3 may be redistributed
  only with a copy of the SAM License, so the copy must be in `sam3/` before the repo is public.
- A bundle install's first start now contacts the hub. It hashes the large files it already has (SHA-256) to
  confirm they match, and downloads small files whose local download record is missing.
- Order of release: 1. put a copy of the SAM License into `sam3/` and the per-component model card in the repo;
  2. make the repo public; 3. merge this branch; 4. upload new weights. Merged before step 2, the harm is: a bundle
  machine with no token shows a warning ("was not found") at every start but keeps measuring on
  its copy; a fresh non-bundle install with no token gets WeightsMissing and cannot measure at all.
- A bundle's `"weights_from": "bundle"` marker is now only a label for the status line.

## Alternatives considered

- *Keep the repo private and ship new bundles by hand*: rejected. Every new model would need a USB stick or a share
  visit to every machine, and stale installs would go unnoticed.
- *Give each machine a read token*: rejected in ticket 21, for the reason above.
- *Mark old answers by the time they were measured*: rejected. Clocks differ between machines; versions are compared,
  never clocks (as for calibrations).
