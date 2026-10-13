"""The models travel with the installer, and a bundle install still gets new weights from the public repo.

The weights ride along in the installer folder (6.5 GB, researcher 2026-08-24), the installer copies them in,
and config.json says they came that way. Until 2026-10-12 the repo was private, so a bundle install never
asked the hub and could never receive a new weights version. The repo is now public: every install asks it
at start with no token, downloads only what changed, and skips SAM3 (weights.SKIP).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from camtrap_measure import store, weights

ROOT = Path(__file__).resolve().parent.parent
INSTALL = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
BUNDLE = (ROOT / "scripts" / "make_bundle.ps1").read_text(encoding="utf-8")


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """A machine with weights on disk and no token anywhere."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("CAMTRAP_WEIGHTS_DIR", raising=False)
    w = tmp_path / "weights"
    w.mkdir()
    (w / "manifest.json").write_text(json.dumps({"version": "2026.08.20c", "megadetector": "md.pt", "speciesnet": "sn"}))
    asked, downloads = [], []
    monkeypatch.setattr(weights, "hub_check", lambda token: asked.append(token) or (0, "c0ffee", []))
    monkeypatch.setattr(weights, "snapshot_download", lambda *a, **kw: downloads.append(kw) or str(w))
    monkeypatch.setattr(weights, "hf_hub_download", lambda *a, **kw: str(w / "manifest.json"))  # same version
    return asked, downloads


def test_a_bundle_install_checks_the_public_repo_with_no_token(installed, tmp_path):
    """The repo is public: a bundle install with no token asks it and downloads what changed, like any install."""
    asked, downloads = installed
    store.save_config({"weights_from": "bundle"})
    got = weights.ensure()
    assert asked == [None] and len(downloads) == 1 and downloads[0]["token"] is None
    assert got["bundled"] is True and got["version"] == "2026.08.20c"  # "bundled" is a label only
    assert got["problem"] is None and got["offline"] is False  # nothing here is a fault


def test_an_offline_bundle_start_uses_the_weights_on_disk(installed, monkeypatch):
    """No internet is normal on a field laptop: the copy on disk is used, with a notice and no warning."""
    def unreachable(token):
        raise ConnectionError("hub unreachable")

    monkeypatch.setattr(weights, "hub_check", unreachable)
    store.save_config({"weights_from": "bundle"})
    got = weights.ensure()
    assert got["offline"] is True and got["problem"] is None and got["version"] == "2026.08.20c"
    assert got["dir"] == store.DATA_DIR / "weights" and installed[1] == []  # nothing downloaded


def test_a_machine_without_the_marker_still_checks_for_new_weights(installed):
    """A developer machine has no token either, and reaches the hub through a cached huggingface-cli login."""
    weights.ensure()
    assert installed[0] == [None]  # asked, with no token, exactly as before


def test_a_token_that_is_set_is_still_sent(installed):
    """Someone who does supply a token means to use it; the bundle marker does not drop it."""
    store.save_config({"weights_from": "bundle", "hf_token": "hf_abc"})
    got = weights.ensure()
    assert installed[0] == ["hf_abc"] and installed[1][0]["token"] == "hf_abc" and got["bundled"] is True


def test_the_status_line_says_where_the_weights_came_from(installed):
    """"2026.08.20c" and "2026.08.20c (installed with the app)" answer different questions when a
    technician rings up about a number."""
    store.save_config({"weights_from": "bundle"})
    assert weights.ensure()["bundled"]
    src = (ROOT / "src" / "camtrap_measure" / "inference.py").read_text(encoding="utf-8")
    assert "installed with the app" in src and 'w.get("bundled")' in src


# --- the installer ------------------------------------------------------------------------------

def test_the_installer_takes_weights_and_never_asks_for_a_token():
    assert "[string]$WeightsFrom" in INSTALL
    # the bundle installs by double-click: the weights folder sits beside the script and is found
    assert 'Join-Path $PSScriptRoot "weights"' in INSTALL
    # the repo is public (2026-10-12): no token box, and no text saying the numbers are made up without one
    assert "Ask-Token" not in INSTALL and "HF_TOKEN" not in INSTALL and "made-up" not in INSTALL


def test_the_installer_records_where_the_weights_came_from():
    """Said, not guessed — the app has no other way to tell a bundled machine from a developer's."""
    assert '"weights_from"' in INSTALL and '"bundle"' in INSTALL


def test_the_installer_copies_six_gigabytes_with_something_that_can_resume():
    assert "robocopy" in INSTALL and "$copied -ge 8" in INSTALL  # robocopy's success codes are < 8
    # through Run, which keeps the window answering: a direct call held it for minutes (2026-09-25)
    assert '$copied = Run "robocopy.exe"' in INSTALL and "& robocopy" not in INSTALL


def test_the_bundle_builder_refuses_to_ship_a_token():
    """config.json lives beside the weights folder and holds the token; shipping it by accident is the
    one mistake this whole exercise exists to prevent."""
    assert 'hf_[A-Za-z0-9]{10}' in BUNDLE
    assert "throw \"A Hugging Face token is inside the weights folder" in BUNDLE


def test_the_bundle_is_never_zipped():
    """Windows PowerShell 5.1's Compress-Archive fails above 2 GB and this folder is over 6. Model
    weights are already compressed, so a zip would spend twenty minutes saving nothing and then break
    at the very end of the build."""
    code = [l for l in BUNDLE.splitlines() if not l.lstrip().startswith("#")]  # the comment says why
    assert not [l for l in code if "Compress-Archive" in l or "$Zip" in l]


def test_the_bundle_refuses_to_build_into_a_synced_folder():
    """The dept's Desktop is redirected into OneDrive, so the obvious place to put the bundle is the one
    place it must not go — 6.5 GB of weights would upload to the university's cloud on the spot."""
    assert "Is-Cloud" in BUNDLE and "$env:OneDrive" in BUNDLE
    assert "-AllowCloudFolder" in BUNDLE  # deliberate is allowed; accidental is not
    assert "GetFolderPath(\"Desktop\")" in BUNDLE and "$env:USERPROFILE \"CamTrapMeasure-Installer\"" in BUNDLE


def test_the_bundle_carries_the_installer_and_a_way_to_start_it():
    for want in ("install.ps1", "setup.vbs", "INSTALL.bat", "README.txt"):
        assert want in BUNDLE, want
    assert "wscript.exe" in BUNDLE  # no console window behind the installer's own


def test_a_config_written_by_powershell_is_still_read(installed, tmp_path):
    """PowerShell 5's `Set-Content -Encoding utf8` starts the file with a byte order mark. json.loads
    rejected it, store.config() returned {}, and a bundled dept machine (2026-09-25) lost its label."""
    (tmp_path / "config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"weights_from": "bundle"}).encode())
    assert store.config() == {"weights_from": "bundle"}
    got = weights.ensure()
    assert installed[0] == [None] and got["bundled"] is True


# --- SAM3 is never downloaded -------------------------------------------------------------------

def test_the_download_skips_sam3(installed):
    """SAM3 (3.4 GB) serves only the precise method, which the window no longer offers. It stays in the repo."""
    weights.ensure()
    assert weights.SKIP == ["sam3/*"] and installed[1][0]["ignore_patterns"] == weights.SKIP + ["manifest.json"]


def test_the_size_the_download_reports_leaves_sam3_out(monkeypatch):
    """The progress total counts only what is downloaded, so the bar can reach its end."""
    files = [("manifest.json", 1), ("unified/model.safetensors", 100), ("sam3/model.safetensors", 3400),
             ("sam3/config.json", 5), ("roma/roma_outdoor.pth", 10)]

    class Api:
        def __init__(self, token=None):
            pass

        def model_info(self, repo, files_metadata=False):
            return SimpleNamespace(siblings=[SimpleNamespace(rfilename=n, size=b) for n, b in files], sha="c0ffee")

    monkeypatch.setattr(weights, "HfApi", Api)
    assert weights.hub_check(None) == (111, "c0ffee", ["manifest.json", "unified/model.safetensors",
                                                     "roma/roma_outdoor.pth"])


# --- an update hf_hub could not finish quietly ---------------------------------------------------

@pytest.mark.parametrize("left_old", [True, False])
def test_a_file_hf_hub_kept_from_the_old_version_holds_back_the_manifest(installed, monkeypatch, left_old):
    """huggingface_hub 1.28.0 keeps an old local file and only logs a warning when its per-file check times out or
    gets a 5xx/429, and snapshot_download still returns normally. The new manifest must then not be fetched: the
    old version stays, and the start says the weights could not be checked."""
    from huggingface_hub._local_folder import write_download_metadata

    w = store.DATA_DIR / "weights"
    files = ["manifest.json", "unified/model.safetensors", "roma/roma_outdoor.pth"]
    fetched = []

    def snapshot_download(repo, local_dir, revision=None, **kw):
        for f in files[1:]:
            (w / f).parent.mkdir(parents=True, exist_ok=True)
            (w / f).write_bytes(b"x")
            old = left_old and f.startswith("roma/")  # its HEAD failed: file and record left as they were
            write_download_metadata(w, f, commit_hash="0" * 40 if old else revision, etag="e")
        return str(w)

    def hf_hub_download(repo, filename, local_dir, **kw):
        fetched.append(filename)
        (w / filename).write_text(json.dumps({"version": "2026.10.12", "megadetector": "md.pt", "speciesnet": "sn"}))
        return str(w / filename)

    monkeypatch.setattr(weights, "hub_check", lambda token: (2, "c" * 40, files))
    monkeypatch.setattr(weights, "snapshot_download", snapshot_download)
    monkeypatch.setattr(weights, "hf_hub_download", hf_hub_download)
    got = weights.ensure()
    if left_old:
        assert fetched == [] and got["version"] == "2026.08.20c" and got["offline"] is False
        assert "1 weights file(s) could not be checked" in got["problem"] and "roma/roma_outdoor.pth" in got["problem"]
    else:
        assert fetched == ["manifest.json"] and got["version"] == "2026.10.12" and got["problem"] is None


def test_the_progress_bar_counts_on_disk_only_what_the_hub_total_counts(tmp_path):
    """sam3/ left from an older install and hf_hub's .cache records are not in hub_check's total, so not on the bar."""
    for name, n in (("manifest.json", 1), ("unified/model.safetensors", 100), ("sam3/model.safetensors", 3400),
                    (".cache/huggingface/download/unified/model.safetensors.metadata", 50)):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"x" * n)
    assert weights._dir_bytes(tmp_path) == 101


def test_a_pinned_weights_folder_is_never_labelled_installed_with_the_app(installed, monkeypatch, tmp_path):
    """CAMTRAP_WEIGHTS_DIR is a folder someone chose, not the bundle's copy, even on a machine with the marker."""
    store.save_config({"weights_from": "bundle"})
    monkeypatch.setenv("CAMTRAP_WEIGHTS_DIR", str(tmp_path / "weights"))
    got = weights.ensure()
    assert got["bundled"] is False and installed[0] == [] and got["version"] == "2026.08.20c"


def test_a_manifest_without_sam3_loads_and_the_precise_method_says_why_not(installed, tmp_path):
    from camtrap_measure import inference

    assert weights.ensure()["version"] == "2026.08.20c"  # the fixture's manifest has no "sam3"
    real = object.__new__(inference.Real)  # no torch: _sam3 refuses before it imports anything
    real.sam3, real.weights_dir = None, tmp_path / "weights"
    for manifest in ({"version": "v"}, {"version": "v", "sam3": "sam3"}):  # no entry; an entry but no folder
        real.manifest = manifest
        with pytest.raises(RuntimeError, match="SAM3 outline is not on this computer"):
            real._sam3()


def test_staging_puts_a_copy_of_the_sam_license_in_sam3(tmp_path, capsys):
    """SAM3 may be redistributed only with its licence: staging copies a given file in, keeps one the snapshot
    brought, and otherwise warns. Nothing is fetched for it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("upload_weights", ROOT / "scripts" / "upload_weights.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    sam3 = tmp_path / "sam3"
    sam3.mkdir()
    up._sam_license(sam3, None)
    assert "WARNING: no SAM License" in capsys.readouterr().err
    (tmp_path / "SAM_LICENSE.txt").write_text("SAM License")
    up._sam_license(sam3, tmp_path / "SAM_LICENSE.txt")
    assert (sam3 / "LICENSE").read_text() == "SAM License"
    up._sam_license(sam3, None)
    assert "kept LICENSE" in capsys.readouterr().out
    assert "must be in `sam3/` before the repo is public" in up.README


def test_an_upload_under_a_version_the_repo_already_holds_is_refused(tmp_path, monkeypatch):
    """A changed file under an unchanged VERSION would leave every old answer looking current: --upload refuses
    and says to bump VERSION; --force uploads anyway. Nothing here reaches the hub."""
    import importlib.util

    import huggingface_hub

    spec = importlib.util.spec_from_file_location("upload_weights", ROOT / "scripts" / "upload_weights.py")
    up = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(up)
    assert up.same_version("2026.10.12", None) is None and up.same_version("2026.10.12", "2026.08.20c") is None
    assert "Bump VERSION" in up.same_version("2026.10.12", "2026.10.12")
    (tmp_path / "manifest.json").write_text(json.dumps({"version": up.VERSION}))
    pushed = []

    class Api:
        def create_repo(self, *a, **kw):
            pass

        def upload_folder(self, **kw):
            pushed.append(kw)

        def list_repo_files(self, repo):
            return []

    monkeypatch.setattr(huggingface_hub, "HfApi", Api)
    monkeypatch.setattr(up, "remote_version", lambda: up.VERSION)
    with pytest.raises(SystemExit, match="Bump VERSION"):
        up.upload(tmp_path)
    assert pushed == []
    up.upload(tmp_path, force=True)
    assert len(pushed) == 1
