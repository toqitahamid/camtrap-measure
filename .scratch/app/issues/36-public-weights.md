# 36 — Public weights: every install checks the repo, and answers carry their weights version

**The problem:** A bundle install (config.json `"weights_from": "bundle"`, no token) never asked Hugging Face, so it
could never receive a new weights version. A retrained distance model (Run 2) is about to ship. Stored answers did
not record which model read them, so nothing could mark them out of date.

**User decisions (2026-10-12):**

1. The weights repo `toqi/camtrap-measure-weights` becomes public (a separate step, with the user's OK). The repo
   id is unchanged.
2. Every install, bundle installs too, checks the repo at start with no token and downloads what changed.
3. SAM3 is not downloaded; it stays in the repo.
4. The token is optional everywhere. The installer stops asking for it.
5. Each answer stores its weights version; an answer read by another version is "Out of date". The CSV is unchanged.

**What was built:**

- `weights.py`: the bundle skip is gone; `bundled` is a label only (and never with `CAMTRAP_WEIGHTS_DIR`).
  `SKIP = ["sam3/*"]` goes to `snapshot_download` (`ignore_patterns`) and leaves the same files out of `hub_check`'s
  total and of the progress bar's bytes on disk (`.cache` too). Everything but `manifest.json` downloads first, then
  `manifest.json` alone, both at the commit `hub_check` saw, and the manifest only once every other file's hf_hub
  download record is at that commit. An interrupted update keeps the OLD manifest, but files it already downloaded
  may be new: the app may run a mix of old and new files under the old version until the next complete update, which
  then changes the version and redoes the answers. A refused token, or a refused cached login when none is set, is
  dropped: check and download run once more with `token=False` (no token, not even a cached login), and the warning
  says the stored token or login can be removed. Refused both times as RepositoryNotFound: "the weights repo <id> was
  not found". Offline and `CAMTRAP_WEIGHTS_DIR` unchanged.
- `inference.py`: `weights_version()` (the running backend's manifest version; while loading and on the fake, the
  weights folder's manifest; with none, `NO_WEIGHTS_VERSION`, which no real answer carries). `test_mode()`. The status line
  says "(offline — cached copy)" before "(installed with the app)". `Real._sam3` gives a plain error when the
  manifest has no `sam3` entry or the folder is missing.
- `store.py`: `photos.weights_version` text column; old databases gain it on open; `record` writes it.
- `measure.py`: `LEGACY_WEIGHTS_VERSION = "2026.08.20c"`. A run stamps its version on each row and passes it to
  `current_answer`, which also requires the stored version (NULL read as legacy) to equal the running one (None read
  as legacy). The research-log line of each measured photo gains `weights_version`. The run status sent to the window
  does not carry it.
- `report.py`, `batch.py`: the folder listing (`stale`) and the site rows (`measured`) pass the running version.
- `preflight.py`: no token prompt, no "no token stored yet" warning; a set token is still checked, as a warning
  only: refused while the repo is public ("remove it"), refused with no way in ("paste a valid token or ask whether
  the repo is public yet"), or "could not be checked (offline or Hugging Face answered with an error)".
- `measure.py`: a Test mode run (`inference.test_mode()`) never redoes an answer for its weights version alone, so
  made-up numbers never replace an answer the real models read. It stamps its answers `NO_WEIGHTS_VERSION`, even
  with a manifest on disk, so a real run of that version redoes them.
- `scripts/install.ps1`: `Ask-Token` removed; the bundle marker is still written (a label). `scripts/make_bundle.ps1`
  and `scripts/upload_weights.py`: no "private repo" text; the model card lists each component's licence.
- Docs: weights.py docstring, README "Model weights", HANDOFF, CONTEXT "Public weights repo", ADR 0003.

**Tests:**

- `test_bundle.py`: `test_bundled_weights_are_never_checked_against_the_hub` is now
  `test_a_bundle_install_checks_the_public_repo_with_no_token`. New: an offline bundle start uses the weights on disk;
  the download passes the SAM3 pattern; `hub_check`'s total leaves SAM3 out; a manifest without `sam3` loads and the
  precise method says why not. The installer test now asserts no token prompt.
- `test_inference.py`: the rejected-token test sets a token; new test for a refusal with no token.
- `test_preflight.py`: the console path no longer answers a token prompt; the empty-token test is gone; the silent
  path expects no token line.
- `test_measure.py`: weights-version staleness (same version current, new version stale, NULL read as legacy) and the
  migration of an old database. `test_report.py`: end to end, a new version makes the answer stale, a run redoes it,
  and the log line names the version.
- `test_launcher.py`: the two tests that required the token box now assert it is gone.
- `test_lineup.py`: `test_old_answers_measure_again_once_...` seeds answers with no weights version, so its FakeModels
  now run under `LEGACY_WEIGHTS_VERSION` (under the default "test" every seeded answer was rightly out of date).
- Full suite on the Delta login node (nice 19, one thread, no torch): 490 passed, 11 skipped (no cv2 / torch, GPU
  smoke, Windows-only). After the review fixes: 498 passed, 11 skipped.

**Review fixes (2026-10-12):** manifest last and commit-pinned; refused token retried with `token=False`
(huggingface_hub 1.28.0: `get_token_to_send(False)` returns None, `HfApi._build_hf_headers` keeps False); preflight
token check `hard=False`; `weights_version()` falls back to the folder's manifest, then `NO_WEIGHTS_VERSION`, with the
Test mode guard; `bundled` only when not pinned; `_dir_bytes` skips SKIP and `.cache`; message wording; docs true
before and after the flip; `upload_weights.py --sam-license`.

**Review fixes, round 2 (2026-10-12):** the manifest waits until every other file's hf_hub download record is at
the pinned commit (`weights._at_commit`, private `huggingface_hub._local_folder.read_download_metadata`; else
`NotUpdated` → a problem, old manifest kept); Test mode stamps `NO_WEIGHTS_VERSION`; the anonymous retry also runs
with no token set (a stale cached login); "the weights repo <id> was not found" when both asks get
RepositoryNotFound; `weights.refused` public; preflight "could not be checked (offline or Hugging Face answered with
an error)"; `upload_weights.py --upload` refuses a VERSION the repo already holds unless `--force`; docs say an
interrupted update may run a mix of old and new files under the old version.

**Order of release:** 1. a copy of the SAM License into `sam3/` and the per-component model card
(`scripts/upload_weights.py --stage <dir> --sam-license <file> --upload`); 2. make the repo public; 3. merge this
branch; 4. upload new weights. Merged before step 2: a bundle machine with no token warns at every start but keeps
measuring; a fresh non-bundle install with no token gets WeightsMissing and cannot measure.

**Open (low confidence):** confirm upstream that MegaDetector v1000 redwood (`md_v1000.0.0-redwood.pt`,
agentmorris/megadetector) is MIT, as the model card says; not checked against the release page here.

**For the lab PC test:**

1. First start of a bundle install against the public repo: the status line reads "2026.08.20c (installed with the
   app)", no warning, and nothing large is downloaded. The installer's `robocopy /E` copies the hidden
   `weights\.cache\huggingface` download records too, so the files are trusted from those records and are not
   hashed; the SHA-256 check of the large files runs only when the records are missing (step 3 covers that).
2. Offline start of the same install: "(offline — cached copy)", no warning, runs measure.
3. Hand-copied files (no `weights\.cache\huggingface` download records, as after a copy that left the hidden
   folder out): delete that folder, start online, and confirm the large files are kept after their hash check (no
   multi-GB download) and the small files are fetched again. A file that still has a download record for the
   current repo commit is trusted without a hash, so an edited file with a record is not repaired.

**Blocked by:** the repo being public (otherwise no-token bundle machines warn at every start, and a fresh
non-bundle install with no token cannot measure).

**Status:** implemented, not committed (2026-10-12, branch `fix/public-weights` from `main` at f4a3900; the
researcher approves commits). No frontend change, so no bundle rebuild.
