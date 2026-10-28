"""The installer's preflight: every failed check explains itself in plain language and names a fix;
the login it collects lands where the app reads it. The weights repo is public, so no token is asked for."""

import json
import subprocess
import sys
from collections import namedtuple

import httpx
import pytest

from camtrap_measure import preflight, store, weights
from camtrap_measure.api import __version__
from camtrap_measure import supabase_ro as sb

Usage = namedtuple("Usage", "total used free")
GB = 2**30


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """A healthy Windows box: one 12 GB GPU on driver 581, 200 GB free, every host reachable, good token, good login."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    m = {"smi": "NVIDIA GeForce RTX 4070, 12282 MiB, 581.15\n", "free_gb": 200, "down": set(), "token_ok": True,
         "cuda": True, "login_ok": True, "tokens": [], "logins": [], "codes_sent": [], "accounts": {"tech@dept.gov"}}

    def run(cmd, **kw):
        if cmd[0] == "nvidia-smi":
            if m["smi"] is None:
                raise FileNotFoundError("nvidia-smi")
            return subprocess.CompletedProcess(cmd, 0, stdout=m["smi"], stderr="")
        raise AssertionError(cmd)

    class Conn:
        def close(self):
            pass

    def connect(addr, timeout=None):
        if addr[0] in m["down"]:
            raise OSError("no route to host")
        return Conn()

    def hub_check(token):
        m["tokens"].append(token)
        if m.get("hub_down"):
            raise ConnectionError("hub unreachable")
        if not m["token_ok"] and not (token is False and m.get("public")):
            resp = httpx.Response(401, request=httpx.Request("GET", "https://huggingface.co/api/models/x"))
            raise weights.RepositoryNotFoundError("401 Client Error", response=resp)
        return 0, "c0ffee", []

    def request_code(email):
        m["codes_sent"].append(email)
        if email not in m["accounts"]:
            raise sb.AuthError("Signups not allowed for otp")

    def verify_code(email, code):
        m["logins"].append((email, code))
        if not m["login_ok"] or code != "123456":
            raise sb.AuthError("Token has expired or is invalid")
        return {"access_token": "at", "refresh_token": "rt0", "user": {"email": email}}

    monkeypatch.setattr(preflight.subprocess, "run", run)
    monkeypatch.setattr(preflight.shutil, "disk_usage", lambda p: Usage(500 * GB, (500 - m["free_gb"]) * GB, m["free_gb"] * GB))
    monkeypatch.setattr(preflight.socket, "create_connection", connect)
    monkeypatch.setattr(weights, "hub_check", hub_check)
    monkeypatch.setattr(sb, "request_code", request_code)
    monkeypatch.setattr(sb, "verify_code", verify_code)
    monkeypatch.setattr(preflight, "_torch_cuda", lambda: m["cuda"])
    monkeypatch.setattr(preflight, "_torch_installed", lambda: m.get("torch", True))
    monkeypatch.setattr(preflight, "_webview2", lambda: m.get("webview2", True))
    return m


def run_preflight(answers: list[str]) -> tuple[int, str]:
    out = []
    it = iter(answers)
    # prompt=True: the console installer's path, where there is a terminal to ask through
    code = preflight.run(ask=lambda prompt: next(it), say=out.append, prompt=True)
    return code, "\n".join(out)


def run_silent() -> tuple[int, str]:
    """The installer's window has no console: preflight must read what is stored and ask nothing."""
    out = []
    code = preflight.run(ask=None, say=out.append, prompt=False)
    return code, "\n".join(out)


def test_healthy_machine_passes_and_stores_the_session_without_asking_for_a_token(machine, tmp_path):
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "All checks passed" in out
    assert "RTX 4070" in out and "12.0 GB" in out and "200 GB free" in out
    assert f"Engine: health check passed, version {__version__}" in out
    assert not (tmp_path / "config.json").exists() and "token" not in out.lower()
    assert store.session() == {"refresh_token": "rt0", "email": "tech@dept.gov"}
    assert machine["tokens"] == [] and machine["codes_sent"] == ["tech@dept.gov"]
    assert machine["logins"] == [("tech@dept.gov", "123456")]


def test_missing_driver_names_the_fix_but_the_install_goes_on(machine):
    machine["smi"] = None
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "No NVIDIA driver" in out and "nvidia.com/drivers" in out and "Traceback" not in out
    assert "with warnings" in out  # a design requirement: a loud warning, never a crash — the app runs on the CPU


def test_old_driver_is_explained_by_cuda_version(machine):
    machine["smi"] = "NVIDIA GeForce GTX 1080, 8192 MiB, 536.40\n"
    machine["cuda"] = False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "536.40" in out and str(preflight.MIN_DRIVER) in out and "update the NVIDIA driver" in out


def test_new_driver_but_torch_blind_says_reboot(machine):
    machine["cuda"] = False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "PyTorch does not see the GPU" in out and "Reboot" in out


def test_missing_webview2_runtime_is_named_with_its_download(machine):
    machine["webview2"] = False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 1 and "WebView2" in out and "developer.microsoft.com" in out


def test_small_gpu_is_a_warning_not_a_failure(machine):
    machine["smi"] = "NVIDIA GeForce GTX 1650, 4096 MiB, 581.15\n"
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "4.0 GB" in out and "slow" in out


def test_low_disk_is_a_warning_naming_what_is_still_needed(machine):
    """Nothing installed yet: the models (6.5 GB), PyTorch (6 GB) and 1 GB for results, all on one drive."""
    machine["free_gb"], machine["torch"] = 5, False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "with warnings" in out  # disk space never stops the install (the researcher, 2026-09-25)
    assert "only 5 GB free" in out and "Needs about 14 GB. Free up 9 GB there" in out


def test_models_already_copied_in_are_not_counted_again(machine, tmp_path):
    """2026-09-25: 26 GB free, the installer copied 6.5 GB of models in, then the check said 19 GB free and
    needs about 20 GB. What is already there no longer counts toward what is still to come."""
    (tmp_path / "weights").mkdir()
    (tmp_path / "weights" / "manifest.json").write_text("{}")
    machine["free_gb"], machine["torch"] = 19, False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "19 GB free" in out and "Disk space" in out and "Needs about" not in out
    machine["free_gb"] = 6
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert "Needs about 7 GB. Free up 1 GB there" in out  # PyTorch 6 + results 1


def test_part_of_the_models_counts_toward_what_is_left(machine, tmp_path, monkeypatch):
    monkeypatch.setattr(preflight.weights, "_dir_bytes", lambda p: int(4.5 * GB))
    (tmp_path / "weights").mkdir()
    machine["free_gb"] = 2
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert "Needs about 3 GB. Free up 1 GB there" in out  # 6.5 - 4.5 of models, 1 for results; torch is in


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters")
def test_pytorch_counts_on_both_drives_when_the_cache_is_elsewhere(machine, monkeypatch):
    monkeypatch.setenv("UV_CACHE_DIR", r"Z:\uv-cache")
    monkeypatch.setattr(preflight.sys, "prefix", r"Y:\app\.venv")
    machine["free_gb"], machine["torch"] = 1, False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert out.count("Needs about 6 GB") == 2 and "on Y:\\" in out and "on Z:\\" in out


def test_unreachable_host_is_named_with_what_it_is_for(machine):
    machine["down"] = {"huggingface.co"}
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "huggingface.co" in out and "model weights" in out and "firewall" in out  # a warning: proxies fool a raw socket
    assert "github.com" in out and "FlagLabel" in out  # the other hosts still reported OK


def test_a_rejected_stored_token_is_named_with_a_fix(machine):
    """Before the repo is public, a refused token leaves no way in: the fix names both ways out. A warning only."""
    store.save_config({"hf_token": "hf_bad"})
    machine["token_ok"] = False
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "with warnings" in out and machine["tokens"] == ["hf_bad", False]
    assert "not accepted" in out and "not readable without one" in out and "huggingface.co/settings/tokens" in out
    assert "needs no token" not in out


def test_a_rejected_token_with_a_public_repo_only_says_it_can_go(machine):
    store.save_config({"hf_token": "hf_bad"})
    machine["token_ok"], machine["public"] = False, True
    code, out = run_preflight(["tech@dept.gov", "123456"])
    assert code == 0 and "with warnings" in out and machine["tokens"] == ["hf_bad", False]
    assert "not accepted" in out and "reads the public weights repo without it" in out and "needs no token" in out


def test_a_stored_token_checked_offline_blames_the_connection_not_the_token(machine):
    store.save_config({"hf_token": "hf_abc"})
    machine["hub_down"] = True
    code, out = run_silent()
    assert code == 0 and "with warnings" in out
    assert "could not be checked (offline or Hugging Face answered with an error" in out
    assert "not accepted" not in out and "needs no token" not in out


def test_wrong_code_asks_for_the_code_again_without_a_new_email(machine):
    code, out = run_preflight(["tech@dept.gov", "typo", "123456"])
    assert code == 0 and "Token has expired or is invalid" in out and store.session()["email"] == "tech@dept.gov"
    assert machine["codes_sent"] == ["tech@dept.gov"]  # one email; the typo cost only a second prompt


def test_unknown_email_is_explained_and_asked_again(machine):
    code, out = run_preflight(["nobody@dept.gov", "tech@dept.gov", "123456"])
    assert code == 0 and "no code sent to nobody@dept.gov" in out and "existing FlagLabel account" in out
    assert machine["codes_sent"] == ["nobody@dept.gov", "tech@dept.gov"]


def test_three_bad_codes_stop_the_install_with_a_fix(machine):
    code, out = run_preflight(["tech@dept.gov", "1", "2", "3"])
    assert code == 1 and "newest FlagLabel email" in out and "Some checks failed" in out


def test_cloud_server_error_during_login_is_a_plain_message_not_a_traceback(machine, monkeypatch):
    def boom(email):
        raise RuntimeError("503 Service Unavailable")

    monkeypatch.setattr(sb, "request_code", boom)
    code, out = run_preflight(["tech@dept.gov", "tech@dept.gov", "tech@dept.gov"])
    assert code == 1 and "answered with an error (RuntimeError)" in out and "Traceback" not in out


def test_without_a_console_nothing_is_asked_and_nothing_is_a_hard_failure(machine, tmp_path):
    """The window installer runs preflight with no stdin; asking there raised EOFError before a single
    check was read (seen 2026-08-23), and the technician got a traceback in a dialog."""
    code, out = run_silent()
    assert code == 0 and "All checks passed. The app is ready to launch." in out
    assert "token" not in out.lower() and "made-up" not in out  # no token is normal: the weights repo is public
    assert "Traceback" not in out and not (tmp_path / "config.json").exists()
    # 2026-09-25, the researcher: signing in comes after the install, in the app; the line read as a problem
    assert "FlagLabel login" not in out and "signed in" not in out


def test_without_a_console_what_is_already_stored_is_checked(machine, tmp_path):
    store.save_config({"hf_token": "hf_abc"})
    code, out = run_silent()
    assert code == 0 and "token accepted" in out
    assert machine["tokens"] == ["hf_abc"]


def test_bundled_models_need_no_token_line_and_no_sign_in_line(machine, tmp_path):
    """2026-09-25, the researcher: "i dont need this unwanted message at all". Neither the token nor the
    FlagLabel sign-in is something to act on during the install, so neither is printed."""
    store.save_config({"weights_from": "bundle"})
    code, out = run_silent()
    assert code == 0 and "All checks passed. The app is ready to launch." in out
    assert "Model weights access" not in out and "token" not in out.lower()
    assert "FlagLabel login" not in out and "signed in" not in out
    assert machine["tokens"] == []


def test_a_rejected_stored_token_is_a_warning_not_a_stop(machine):
    """The app reads the public repo without a refused token (weights.ensure), so the install goes on."""
    store.save_config({"hf_token": "hf_bad"})
    machine["token_ok"] = False
    code, out = run_silent()
    assert code == 0 and "not accepted" in out and "with warnings" in out


def test_a_token_in_the_environment_is_used_when_nobody_can_be_asked(machine, tmp_path, monkeypatch):
    """How the installer's window hands over a token the technician typed into it."""
    monkeypatch.setenv("HF_TOKEN", "hf_abc")
    code, out = run_silent()
    assert code == 0 and "token accepted" in out
    assert json.loads((tmp_path / "config.json").read_text()) == {"hf_token": "hf_abc"}

