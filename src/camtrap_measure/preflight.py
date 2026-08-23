"""The installer's checks, run as `camtrap-measure --preflight` once uv has built the environment.

Each check says what it found and, when it fails, what to do about it in plain words — never a stack
trace. It also collects the two credentials the app needs (Hugging Face read token for the weights,
FlagLabel login by emailed one-time code) and stores them where the app reads them, so the first real
launch is already set up.
The logic lives here (not in the PowerShell installer) so it is testable without a Windows machine.
"""

import os
import re
import shutil
import socket
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from . import store, weights
from . import supabase_ro as sb
from .inference import VRAM_FLOOR_GB

MIN_DRIVER = 570  # the CUDA 12.8 wheels the lockfile pins need this NVIDIA driver or newer
MIN_FREE_GB = 20  # weights ~7 GB + torch ~3 GB + environment, with room for the results database
HOSTS = {  # host → what the app needs it for; reachability = a TCP connection to port 443 (no HTTP client outside the wrapper)
    "github.com": "app updates",
    "huggingface.co": "model weights",
    sb.SUPABASE_URL.split("//")[1]: "FlagLabel cloud sync",
}
ATTEMPTS = 3


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    fix: str | None = None  # present when not ok, or as a warning on an ok result
    hard: bool = True  # a hard failure stops the install; a soft one is reported and carried on


def _torch_cuda() -> bool | None:
    """Does the installed torch see a GPU? None when torch is not installed (the fake backend will run)."""
    try:
        import torch
    except ImportError:
        return None
    return torch.cuda.is_available()


def check_gpu() -> Result:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        out = None
    # GPU trouble never stops the install: the app runs on the CPU with a loud warning (spec story 33) — but the
    # fix is spelled out here, where a technician is still in setup mode.
    if out is None or out.returncode != 0 or not out.stdout.strip():
        return Result("GPU", False, "No NVIDIA driver found (nvidia-smi is missing or failed).",
                      "Install the NVIDIA driver for this card from https://www.nvidia.com/drivers (needs an administrator — "
                      "ask IT), reboot, and run the installer again. Without it the app runs on the CPU, many times slower.",
                      hard=False)
    name, mem, driver = [s.strip() for s in out.stdout.strip().splitlines()[0].split(",")]  # first card of possibly several
    gb = int(re.sub(r"\D", "", mem) or 0) / 1024
    detail = f"{name}, {gb:.1f} GB memory, driver {driver}"
    major = int(driver.split(".")[0]) if driver.split(".")[0].isdigit() else 0
    if major and major < MIN_DRIVER:
        return Result("GPU", False, detail,
                      f"The driver is {driver}; the app's CUDA 12.8 build needs driver {MIN_DRIVER} or newer — update the "
                      f"NVIDIA driver from https://www.nvidia.com/drivers (needs an administrator — ask IT), reboot, and run "
                      f"the installer again.", hard=False)
    if _torch_cuda() is False:
        return Result("GPU", False, detail,
                      "The driver looks fine but PyTorch does not see the GPU. Reboot (a fresh driver needs one) and run the "
                      "installer again; if it repeats, send this message to the researcher.", hard=False)
    if gb < VRAM_FLOOR_GB:
        return Result("GPU", True, detail, f"Only {gb:.1f} GB of GPU memory, below the {VRAM_FLOOR_GB} GB the app is designed "
                                           f"for — it will run, but slow. Consider the precise method only for small batches.")
    return Result("GPU", True, detail)


def check_disk() -> list[Result]:
    """The data folder (weights, results) and the app folder (environment, torch) may sit on different drives."""
    store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for what, path in {"data folder": store.DATA_DIR, "app folder": Path(__file__).resolve().parent}.items():
        if any(Path(r.detail.split(" holding ")[-1]).anchor == path.anchor for r in out):
            continue  # same drive, already reported
        free = shutil.disk_usage(path).free // 2**30
        detail = f"{free} GB free on the drive holding {path}"
        if free < MIN_FREE_GB:
            out.append(Result(f"Disk space ({what})", False, detail,
                              f"The app needs about {MIN_FREE_GB} GB for its models and environment. Free up space on this "
                              f"drive (for the data folder, CAMTRAP_DATA_DIR can point at a bigger one) and run the installer again."))
        else:
            out.append(Result(f"Disk space ({what})", True, detail))
    return out


def check_network() -> list[Result]:
    # ponytail: a raw socket ignores HTTPS_PROXY, which git, uv and the app's own HTTP client honour — hence a warning, never a stop.
    # Honour the proxy env vars here if a proxied dept network makes this cry wolf.
    out = []
    for host, purpose in HOSTS.items():
        try:
            socket.create_connection((host, 443), timeout=10).close()
            out.append(Result(f"Network: {host}", True, f"reachable ({purpose})"))
        except Exception as e:
            # soft: a proxy that git/uv already went through would fail this plain socket too
            out.append(Result(f"Network: {host}", False, f"not reachable ({purpose}): {type(e).__name__}",
                              f"The app needs {host} for {purpose}. Check the internet connection, and ask IT to allow "
                              f"{host} through the firewall or proxy. Measurement itself works offline; this only "
                              f"blocks {purpose}.", hard=False))
    return out


def _webview2() -> bool | None:
    """Is the WebView2 runtime (the app's window) installed? None off Windows. Windows 11 ships it; Windows 10 may not."""
    if sys.platform != "win32":
        return None
    import winreg

    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                      (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")):
        try:
            with winreg.OpenKey(root, key):
                return True
        except OSError:
            pass
    return False


def check_window() -> Result | None:
    has = _webview2()
    if has is None:
        return None
    if not has:
        return Result("App window", False, "the Microsoft WebView2 runtime is not installed",
                      "Install the Evergreen WebView2 runtime from https://developer.microsoft.com/microsoft-edge/webview2/ "
                      "(Windows 11 has it built in; on Windows 10 the installer needs an administrator — ask IT), then run "
                      "the installer again.")
    return Result("App window", True, "WebView2 runtime present")


def check_token(token: str) -> Result:
    try:
        weights.hub_check(token)
    except Exception as e:
        return Result("Model weights access", False, f"token not accepted ({type(e).__name__})",
                      "Get a read token from https://huggingface.co/settings/tokens for an account that has access to the "
                      f"weights repo {weights.REPO} (ask the researcher), and paste it exactly.")
    store.save_config({**store.config(), "hf_token": token})
    return Result("Model weights access", True, "token accepted and saved")


def check_code_sent(email: str) -> Result:
    """Step one of the FlagLabel login: Supabase emails a one-time code to an existing account."""
    try:
        sb.request_code(email)
    except sb.AuthError as e:
        return Result("FlagLabel login", False, f"no code sent to {email}: {e}",
                      "Use the email of an existing FlagLabel account (the one you sign in with on the website). "
                      "'Only request this after N seconds' means wait that long, then try again.")
    except sb.Offline:
        return Result("FlagLabel login", False, "FlagLabel cloud not reachable", "Check the internet connection and try again.")
    except Exception as e:  # a 5xx or a malformed answer: the cloud's problem, not the technician's
        return Result("FlagLabel login", False, f"FlagLabel cloud answered with an error ({type(e).__name__})",
                      "Wait a minute and try again; if it repeats, send this message to the researcher.")
    return Result("FlagLabel login", True, f"code emailed to {email}")


def check_login(email: str, code: str) -> Result:
    """Step two: the code from the email becomes the session the app remembers."""
    try:
        sess = sb.verify_code(email, code)
    except sb.AuthError as e:
        return Result("FlagLabel login", False, str(e), "Type the code from the newest FlagLabel email exactly (check the spam "
                                                        "folder). An expired code: start again with the email.")
    except sb.Offline:
        return Result("FlagLabel login", False, "FlagLabel cloud not reachable", "Check the internet connection and try again.")
    except Exception as e:
        return Result("FlagLabel login", False, f"FlagLabel cloud answered with an error ({type(e).__name__})",
                      "Wait a minute and try again; if it repeats, send this message to the researcher.")
    store.save_session({"refresh_token": sess["refresh_token"], "email": sess["user"]["email"]})
    return Result("FlagLabel login", True, f"signed in as {email}; the app will remember this")


def check_engine() -> Result:
    """Does the engine start and answer? In-process, no port, no network — the first health check."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # library deprecation chatter is not a finding for the technician
            from fastapi.testclient import TestClient

            from .api import app, __version__
            r = TestClient(app).get("/api/health")
        ok = r.status_code == 200 and r.json().get("status") == "ok"
    except Exception as e:
        return Result("Engine", False, f"did not start ({type(e).__name__}: {e})",
                      "The app's environment is broken — run the installer again; if this repeats, send this message to the researcher.")
    return Result("Engine", ok, f"health check {'passed' if ok else 'failed'}, version {__version__}",
                  None if ok else "Run the installer again; if this repeats, send this message to the researcher.")


def run(ask=input, say=print, prompt: bool | None = None) -> int:
    """Preflight. → exit code (0 = ready to launch).

    `prompt=False` asks nothing: the installer's window has no console to ask through, and a bare
    `input()` there raises EOFError before a single check is read (seen 2026-08-23). What is already
    stored is checked instead, and what is missing becomes a warning naming where to put it - never a
    hard failure, because the window itself takes the sign-in and the token can be dropped into
    config.json afterwards. Left at None it asks when there is a terminal to ask through.
    """
    if prompt is None:
        prompt = bool(getattr(sys.stdin, "isatty", lambda: False)())
    results = [r for r in (check_gpu(), *check_disk(), *check_network(), check_window(), check_engine()) if r]
    say("")
    if not prompt:
        results += [_stored_token(), _stored_session()]
        return _report(results, say)
    for _ in range(ATTEMPTS):
        token = ask("Hugging Face read token for the model weights (Enter to skip for now): ").strip()
        if not token:
            results.append(Result("Model weights access", True, "skipped",
                                  "Continuing without a token: the app will start with made-up numbers until hf_token is set "
                                  f"in {store.DATA_DIR / 'config.json'}.", hard=False))
            break
        r = check_token(token)
        if r.ok:
            results.append(r)
            break
        say(f"  ✗ {r.detail}")
    else:
        results.append(r)
    for _ in range(ATTEMPTS):  # three tries at an email that gets a code; then three tries at typing that code
        email = ask("FlagLabel email (a one-time sign-in code will be emailed to it): ").strip()
        r = check_code_sent(email)
        if r.ok:
            for _ in range(ATTEMPTS):
                r = check_login(email, ask("Code from that email: "))
                if r.ok:
                    break
                say(f"  ✗ {r.detail}")
            break  # a code went out: that is the outcome, good or bad — another email would mean another code
        say(f"  ✗ {r.detail}\n    → {r.fix}")
    results.append(r)
    return _report(results, say)


def _stored_token() -> Result:
    """What the weights loader will find, when nobody can be asked for a token."""
    token = os.environ.get("HF_TOKEN") or store.config().get("hf_token")
    if not token:
        return Result("Model weights access", False, "no token stored yet",
                      "The app will start with made-up numbers until hf_token is set in "
                      f"{store.DATA_DIR / 'config.json'} (ask the researcher for the token).", hard=False)
    return check_token(token)


def _stored_session() -> Result:
    """Signing in is the window's job now (ticket 14); this only says where this computer stands."""
    session = store.session()
    if session:
        return Result("FlagLabel login", True, f"signed in as {session['email']}")
    return Result("FlagLabel login", False, "not signed in on this computer yet",
                  "Sign in with your FlagLabel email in the app window when it opens - it emails you a "
                  "one-time code, there is no password.", hard=False)


def _report(results: list[Result], say) -> int:
    say("")
    failed = False
    for r in results:
        say(f"{'✓' if r.ok else '✗'} {r.name}: {r.detail}")
        if r.fix:
            say(f"    → {r.fix}")
        failed |= not r.ok and r.hard
    say("")
    warned = any(not r.ok and not r.hard for r in results)
    say("Some checks failed — fix them as described above, then run the installer again." if failed
        else "All checks passed, with warnings above — the app will run, read them." if warned
        else "All checks passed. The app is ready to launch.")
    return 1 if failed else 0
