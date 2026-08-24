"""The models travel with the installer, so no team machine ever needs a Hugging Face token.

Handing a read token to twelve people is handing out a credential that cannot be taken back from any
one of them, so the department is given the models instead (researcher, 2026-08-24). The weights ride
along in the installer folder, the installer copies them in, and the app is told they came that way.

The failure this guards against is quiet rather than loud: a machine with no token asks the private
repo anyway, gets a 401, and shows "the weights repo rejected the access token" for ever after on a
machine that is working perfectly.
"""

import json
from pathlib import Path

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
    asked = []
    monkeypatch.setattr(weights, "hub_check", lambda token: asked.append(token) or 0)
    monkeypatch.setattr(weights, "snapshot_download", lambda *a, **kw: str(w))
    return asked


def test_bundled_weights_are_never_checked_against_the_hub(installed, tmp_path):
    """The repo is private and the machine has no token: asking could only ever fail."""
    store.save_config({"weights_from": "bundle"})
    got = weights.ensure()
    assert installed == []  # the hub was not asked at all
    assert got["bundled"] is True and got["version"] == "2026.08.20c"
    assert got["problem"] is None and got["offline"] is False  # nothing here is a fault


def test_a_machine_without_the_marker_still_checks_for_new_weights(installed):
    """A developer machine has no token either, and reaches the hub through a cached huggingface-cli
    login. Inferring "bundled" from the absence of a token would stop its updates."""
    weights.ensure()
    assert installed == [None]  # asked, with no token, exactly as before


def test_a_token_still_wins_over_the_marker(installed):
    """Someone who does supply a token means to use it — the marker is for machines that have none."""
    store.save_config({"weights_from": "bundle", "hf_token": "hf_abc"})
    got = weights.ensure()
    assert installed == ["hf_abc"] and got["bundled"] is False


def test_the_status_line_says_where_the_weights_came_from(installed):
    """"2026.08.20c" and "2026.08.20c (installed with the app)" answer different questions when a
    technician rings up about a number."""
    store.save_config({"weights_from": "bundle"})
    assert weights.ensure()["bundled"]
    src = (ROOT / "src" / "camtrap_measure" / "inference.py").read_text(encoding="utf-8")
    assert "installed with the app" in src and 'w.get("bundled")' in src


# --- the installer ------------------------------------------------------------------------------

def test_the_installer_takes_weights_instead_of_asking_for_a_token():
    assert "[string]$WeightsFrom" in INSTALL
    # the bundle installs by double-click: the weights folder sits beside the script and is found
    assert 'Join-Path $PSScriptRoot "weights"' in INSTALL
    # the token box is inside the "no weights came with the installer" branch, and nowhere else
    assert INSTALL.count("$token = Ask-Token") == 1
    branch = INSTALL.split("if ($WeightsFrom) {")[1].split("Step \"Checking this machine")[0]
    ask_at = branch.index("$token = Ask-Token")
    assert branch.index("} else {") < ask_at  # reached only when there were no bundled weights


def test_the_installer_records_where_the_weights_came_from():
    """Said, not guessed — the app has no other way to tell a bundled machine from a developer's."""
    assert '"weights_from"' in INSTALL and '"bundle"' in INSTALL


def test_the_installer_copies_six_gigabytes_with_something_that_can_resume():
    assert "robocopy" in INSTALL and "$LASTEXITCODE -ge 8" in INSTALL  # robocopy's success codes are < 8


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


def test_the_bundle_carries_the_installer_and_a_way_to_start_it():
    for want in ("install.ps1", "setup.vbs", "INSTALL.bat", "README.txt"):
        assert want in BUNDLE, want
    assert "wscript.exe" in BUNDLE  # no console window behind the installer's own
