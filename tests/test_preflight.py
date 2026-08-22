"""The installer's preflight: every failed check explains itself in plain language and names a fix;
credentials it collects land where the app reads them."""

import json
import subprocess
from collections import namedtuple

import pytest

from camtrap_measure import preflight, store, weights
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
        if not m["token_ok"]:
            raise weights.RepositoryNotFoundError("401 Client Error")

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
    monkeypatch.setattr(preflight, "_webview2", lambda: m.get("webview2", True))
    return m


def run_preflight(answers: list[str]) -> tuple[int, str]:
    out = []
    it = iter(answers)
    code = preflight.run(ask=lambda prompt: next(it), say=out.append)
    return code, "\n".join(out)


def test_healthy_machine_passes_and_stores_token_and_session(machine, tmp_path):
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "All checks passed" in out
    assert "RTX 4070" in out and "12.0 GB" in out and "200 GB free" in out
    assert "Engine: health check passed, version 0.1.0" in out
    assert json.loads((tmp_path / "config.json").read_text()) == {"hf_token": "hf_abc"}
    assert store.session() == {"refresh_token": "rt0", "email": "tech@dept.gov"}
    assert machine["tokens"] == ["hf_abc"] and machine["codes_sent"] == ["tech@dept.gov"]
    assert machine["logins"] == [("tech@dept.gov", "123456")]


def test_missing_driver_names_the_fix_but_the_install_goes_on(machine):
    machine["smi"] = None
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "No NVIDIA driver" in out and "nvidia.com/drivers" in out and "Traceback" not in out
    assert "with warnings" in out  # story 33: a loud warning, never a crash — the app runs on the CPU


def test_old_driver_is_explained_by_cuda_version(machine):
    machine["smi"] = "NVIDIA GeForce GTX 1080, 8192 MiB, 536.40\n"
    machine["cuda"] = False
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "536.40" in out and str(preflight.MIN_DRIVER) in out and "update the NVIDIA driver" in out


def test_new_driver_but_torch_blind_says_reboot(machine):
    machine["cuda"] = False
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "PyTorch does not see the GPU" in out and "Reboot" in out


def test_missing_webview2_runtime_is_named_with_its_download(machine):
    machine["webview2"] = False
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 1 and "WebView2" in out and "developer.microsoft.com" in out


def test_small_gpu_is_a_warning_not_a_failure(machine):
    machine["smi"] = "NVIDIA GeForce GTX 1650, 4096 MiB, 581.15\n"
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "4.0 GB" in out and "slow" in out


def test_low_disk_names_the_amount_needed(machine):
    machine["free_gb"] = 5
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 1 and "5 GB free" in out and f"{preflight.MIN_FREE_GB} GB" in out


def test_unreachable_host_is_named_with_what_it_is_for(machine):
    machine["down"] = {"huggingface.co"}
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "123456"])
    assert code == 0 and "huggingface.co" in out and "model weights" in out and "firewall" in out  # a warning: proxies fool a raw socket
    assert "github.com" in out and "FlagLabel" in out  # the other hosts still reported OK


def test_rejected_token_asks_again_then_gives_up_with_a_fix(machine):
    machine["token_ok"] = False
    code, out = run_preflight(["hf_bad", "hf_bad2", "hf_bad3", "tech@dept.gov", "123456"])
    assert code == 1 and machine["tokens"] == ["hf_bad", "hf_bad2", "hf_bad3"]
    assert "not accepted" in out and "huggingface.co/settings/tokens" in out


def test_wrong_code_asks_for_the_code_again_without_a_new_email(machine):
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "typo", "123456"])
    assert code == 0 and "Token has expired or is invalid" in out and store.session()["email"] == "tech@dept.gov"
    assert machine["codes_sent"] == ["tech@dept.gov"]  # one email; the typo cost only a second prompt


def test_unknown_email_is_explained_and_asked_again(machine):
    code, out = run_preflight(["hf_abc", "nobody@dept.gov", "tech@dept.gov", "123456"])
    assert code == 0 and "no code sent to nobody@dept.gov" in out and "existing FlagLabel account" in out
    assert machine["codes_sent"] == ["nobody@dept.gov", "tech@dept.gov"]


def test_three_bad_codes_stop_the_install_with_a_fix(machine):
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "1", "2", "3"])
    assert code == 1 and "newest FlagLabel email" in out and "Some checks failed" in out


def test_empty_token_skips_weights_with_a_warning(machine, tmp_path):
    code, out = run_preflight(["", "tech@dept.gov", "123456"])
    assert code == 0 and "without a token" in out and not (tmp_path / "config.json").exists()


def test_cloud_server_error_during_login_is_a_plain_message_not_a_traceback(machine, monkeypatch):
    def boom(email):
        raise RuntimeError("503 Service Unavailable")

    monkeypatch.setattr(sb, "request_code", boom)
    code, out = run_preflight(["hf_abc", "tech@dept.gov", "tech@dept.gov", "tech@dept.gov"])
    assert code == 1 and "answered with an error (RuntimeError)" in out and "Traceback" not in out
