"""Engine start picks an inference backend: weights manifest, real models, or the fake — reported in /api/status."""

import json
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from huggingface_hub.errors import RepositoryNotFoundError

from camtrap_measure import api, inference, weights

from tests.test_measure import folder, run


class StubReal:
    def __init__(self, weights_dir, device="cuda"):
        self.dir, self.device, self.batch, self.warning = weights_dir, device, 16, None

    def __call__(self, paths, calibration, method):
        yield from inference.fake(paths, calibration, method)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(inference, "state", {"status": "ready", "backend": "fake", "device": None, "batch": None,
                                             "weights": None, "warning": None, "error": None, "download": None})
    monkeypatch.setattr(inference, "backend", inference.fake)
    monkeypatch.delenv("CAMTRAP_WEIGHTS_DIR", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)


@pytest.fixture
def models_installed(monkeypatch):
    """Pretend the [inference] extra is importable and the models load instantly."""
    monkeypatch.setattr(inference, "models_installed", lambda: True)
    monkeypatch.setattr(inference, "Real", StubReal)


@pytest.fixture
def hub(monkeypatch, tmp_path):
    """Fake Hugging Face hub: reachable unless offline; a bad token is rejected; downloads write a manifest."""
    calls = {"offline": False, "bad_token": False, "n": 0, "version": "2026.08.20", "tokens": []}

    def hub_check(token):
        calls["tokens"].append(token)
        if calls["offline"]:
            raise ConnectionError("hub unreachable")
        if calls["bad_token"]:
            resp = httpx.Response(401, request=httpx.Request("GET", "https://huggingface.co/api/models/x"))
            raise RepositoryNotFoundError("401 Client Error: Repository Not Found", response=resp)
        return 7 * 2**30  # the repo's size, for the download progress

    def snapshot_download(repo, local_dir, token=None, **kw):
        calls["n"] += 1
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "manifest.json").write_text(json.dumps({"version": calls["version"], "megadetector": "md.pt", "speciesnet": "sn"}))
        return str(local_dir)

    monkeypatch.setattr(weights, "hub_check", hub_check)
    monkeypatch.setattr(weights, "snapshot_download", snapshot_download)
    return calls


@pytest.fixture
def start():
    """start() → (client, inference state once warmup finished); every client is closed at teardown."""
    opened = []

    def _start(timeout=5):
        c = TestClient(api.app)
        c.__enter__()  # lifespan: warmup thread
        opened.append(c)
        for _ in range(int(timeout / 0.02)):
            s = c.get("/api/status").json()["inference"]
            if s["status"] != "loading":
                return c, s
            time.sleep(0.02)
        raise AssertionError("warmup never finished")

    yield _start
    for c in opened:
        c.__exit__(None, None, None)


def test_without_the_inference_extra_the_fake_runs_with_a_visible_warning(cloud, start):
    c, s = start()
    assert s["status"] == "ready" and s["backend"] == "fake"
    assert "FAKE" in s["warning"] and "uv sync --extra inference" in s["warning"]


def test_first_start_downloads_weights_and_loads_real_models(cloud, hub, models_installed, start, tmp_path):
    c, s = start()
    assert hub["n"] == 1 and (tmp_path / "weights" / "manifest.json").exists()
    assert s == {"status": "ready", "backend": "real", "device": "cuda", "batch": 16, "weights": "2026.08.20",
                 "warning": None, "error": None, "download": None}


def test_token_comes_from_env_or_installer_config(cloud, hub, models_installed, start, monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"hf_token": "hf_cfg"}))
    start()
    monkeypatch.setenv("HF_TOKEN", "hf_env")
    start()
    assert hub["tokens"] == ["hf_cfg", "hf_env"]


def test_offline_start_uses_cached_weights_and_says_so(cloud, hub, models_installed, start):
    start()
    hub["offline"] = True
    c, s = start()
    assert s["status"] == "ready" and s["backend"] == "real" and s["weights"] == "2026.08.20 (offline — cached copy)"
    assert s["warning"] is None  # offline is normal, not a fault


def test_offline_first_start_is_an_error_and_runs_are_refused(cloud, hub, models_installed, start, synced, tmp_path):
    hub["offline"] = True
    c, s = start()
    assert s["status"] == "error" and "internet" in s["error"] and s["backend"] == "fake"
    r = c.post("/api/run", json={"folder": str(folder(tmp_path)), "site": "TON_CAM02", "flag": "IMG_5304.JPG", "method": "md"})
    assert r.status_code == 503 and "internet" in r.json()["detail"]


def test_rejected_token_is_named_not_mistaken_for_offline(cloud, hub, models_installed, start):
    hub["bad_token"] = True
    c, s = start()
    assert s["status"] == "error" and "token" in s["error"] and "internet" not in s["error"]
    hub["bad_token"] = False
    start()
    hub["bad_token"] = True  # token expired after a good first download: cached copy + loud warning
    c, s = start()
    assert s["status"] == "ready" and s["weights"] == "2026.08.20" and "token" in s["warning"]


def test_updated_manifest_is_picked_up_on_next_start(cloud, hub, models_installed, start):
    start()
    hub["version"] = "2026.09.01"
    c, s = start()
    assert hub["n"] == 2 and s["weights"] == "2026.09.01"


def test_pinned_weights_dir_skips_the_hub(cloud, hub, models_installed, start, monkeypatch, tmp_path):
    d = tmp_path / "pinned"
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"version": "local", "megadetector": "md.pt", "speciesnet": "sn"}))
    monkeypatch.setenv("CAMTRAP_WEIGHTS_DIR", str(d))
    c, s = start()
    assert hub["n"] == 0 and hub["tokens"] == [] and s["weights"] == "local" and s["backend"] == "real"


def test_no_gpu_warns_loudly_but_still_runs(cloud, hub, models_installed, start, monkeypatch, synced, tmp_path):
    monkeypatch.setattr(inference, "Real", lambda d: StubReal(d, device="cpu"))
    c, s = start()
    assert s["status"] == "ready" and s["device"] == "cpu" and "No GPU" in s["warning"] and "driver" in s["warning"]
    assert c.post("/api/run", json={"folder": str(folder(tmp_path)), "site": "TON_CAM02", "flag": "IMG_5304.JPG", "method": "md"}).status_code == 200


def test_small_gpu_warning_is_shown(cloud, hub, models_installed, start, monkeypatch):
    def small(d):
        r = StubReal(d)
        r.warning = "This GPU has 6.0 GB of memory, below the 8 GB the app is designed for — runs will be slow."
        return r
    monkeypatch.setattr(inference, "Real", small)
    c, s = start()
    assert s["status"] == "ready" and "6.0 GB" in s["warning"]


def test_model_load_failure_is_reported_not_fatal(cloud, hub, models_installed, start, monkeypatch):
    def broken(d):
        raise RuntimeError("CUDA driver version is insufficient")
    monkeypatch.setattr(inference, "Real", broken)
    c, s = start()
    assert s["status"] == "error" and "CUDA driver" in s["error"] and c.get("/api/health").status_code == 200


def test_runs_are_refused_while_models_load(cloud, hub, models_installed, start, monkeypatch, synced, tmp_path):
    gate = threading.Event()

    def slow(d):
        gate.wait(5)
        return StubReal(d)
    monkeypatch.setattr(inference, "Real", slow)
    c = TestClient(api.app)
    with c:
        r = c.post("/api/run", json={"folder": str(folder(tmp_path)), "site": "TON_CAM02", "flag": "IMG_5304.JPG", "method": "md"})
        assert r.status_code == 503 and "loading" in r.json()["detail"]
        gate.set()
        for _ in range(100):
            if c.get("/api/status").json()["inference"]["status"] == "ready":
                break
            time.sleep(0.02)
        assert c.get("/api/status").json()["inference"]["backend"] == "real"


def test_real_backend_is_used_by_runs(cloud, hub, models_installed, start, monkeypatch, synced, tmp_path):
    seen = []

    class Recording(StubReal):
        def __call__(self, paths, calibration, method):
            seen.extend(paths)
            yield from super().__call__(paths, calibration, method)
    monkeypatch.setattr(inference, "Real", Recording)
    c, s = start()
    run(c, folder(tmp_path))
    assert [p.name for p in seen] == ["IMG_0005.JPG"]


# --- species naming (pure rule, no model needed) -------------------------------------------

@pytest.mark.parametrize("cls, score, label", [
    ("u;mammalia;cetartiodactyla;cervidae;odocoileus;virginianus;white-tailed deer", 0.98, "white-tailed deer"),
    ("u;mammalia;cetartiodactyla;cervidae;;;deer family", 0.4, "white-tailed deer"),   # rolled-up deer is still our deer
    ("u;mammalia;cetartiodactyla;cervidae;cervus;elaphus;elk", 0.9, "white-tailed deer"),  # region has one wild deer
    ("u;mammalia;carnivora;procyonidae;procyon;lotor;raccoon", 0.9, "raccoon"),
    ("u;mammalia;rodentia;sciuridae;;;squirrel family", 0.5, "squirrel family"),
    ("u;mammalia;carnivora;procyonidae;procyon;lotor;raccoon", 0.1, "unsure"),
    ("u;;;;;;blank", 0.95, "blank"),
])
def test_species_label(cls, score, label):
    assert inference.species_label(cls, score) == label


def test_oom_detection_covers_cudnn_and_cublas_failures():
    assert inference.is_oom(RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"))
    assert inference.is_oom(RuntimeError("cuDNN error: CUDNN_STATUS_NOT_INITIALIZED"))
    assert not inference.is_oom(RuntimeError("shape mismatch"))


# --- precise method: ground contact from the SAM3 mask (pure numpy, no model needed) -----------

def test_foot_pixel_is_the_median_column_of_the_lowest_mask_rows():
    m = np.zeros((100, 100), bool)
    m[20:60, 30:70] = True
    assert inference.foot_pixel(m) == (49, 59)  # median of columns 30..69, lowest row
    m[:] = False
    m[60:80, 35:38] = True  # a thin leg, off-centre
    assert inference.foot_pixel(m) == (36, 79)
    assert inference.foot_pixel(np.zeros((4, 4), bool)) is None


def test_contacts_take_the_mask_that_matches_each_box_else_the_box_bottom():
    deer = np.zeros((100, 200), bool)
    deer[20:90, 30:70] = True  # feet at column 49, row 89
    far = np.zeros((100, 200), bool)
    far[10:20, 150:160] = True
    masks = [(far, [150, 10, 160, 20]), (deer, [30, 20, 70, 90])]  # SAM3 returns every instance it sees, any order
    boxes = [[30, 20, 70, 90], [100, 40, 120, 60]]  # the deer, and a box SAM3 gave no mask for
    assert inference.contacts(boxes, masks, 200, 100) == [(49.5 / 200, 89.5 / 100), (110 / 200, 60 / 100)]


def test_methods_endpoint_names_the_default_and_explains_each_choice(client):
    r = client.get("/api/methods").json()
    assert r["default"] == inference.DEFAULT_METHOD == "md"
    assert set(r["methods"]) == {"md", "sam3"}
    assert "slower" in r["methods"]["sam3"]["hint"] and r["methods"]["md"]["label"]


def test_an_offline_day_still_measures(cloud, hub, models_installed, start, tmp_path):
    """Launch, sync and the weights check all fall back with a notice; the run itself never needed the internet."""
    c, _ = start()
    c.post("/api/login", json={"email": "tech@dept.gov", "code": "123456"})
    c.post("/api/sync")
    hub["offline"] = cloud["offline"] = True
    c, s = start()
    assert s["status"] == "ready" and s["weights"].endswith("(offline — cached copy)") and s["warning"] is None
    r = c.post("/api/sync").json()
    assert r == {"ok": False, "offline": True, "last_sync": r["last_sync"]} and r["last_sync"]
    assert run(c, folder(tmp_path))["status"] == "done"
    assert c.get("/api/results").json()


def test_weights_download_progress_is_reported(cloud, monkeypatch, tmp_path):
    """The first start downloads ~6.5 GB; the status line shows how far it is."""
    monkeypatch.setattr(weights, "hub_check", lambda token: 1000)  # total bytes the hub says the repo holds

    def slow_download(repo, local_dir, token=None, **kw):
        d = Path(local_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "big.bin").write_bytes(b"x" * 600)
        time.sleep(0.7)  # a few watcher ticks (0.25 s) even on a loaded CI box
        (d / "manifest.json").write_text(json.dumps({"version": "v", "megadetector": "md.pt", "speciesnet": "sn"}))
        return str(local_dir)

    monkeypatch.setattr(weights, "snapshot_download", slow_download)
    seen = []
    w = weights.ensure(progress=lambda done, total: seen.append((done, total)))
    assert w["version"] == "v" and seen and seen[-1][1] == 1000 and any(600 <= d <= 1000 for d, _ in seen)
