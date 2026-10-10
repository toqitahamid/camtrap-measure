"""The torch-free half of the distance port: reference distance map through a homography, 5×5 readout, banner crop,
and the seeded, locked line-up (with fakes; one optional test uses real torch)."""

import contextlib
import sys
import threading
import types

import numpy as np
import pytest
from PIL import Image

from camtrap_measure import distance
from camtrap_measure.calib.model_b import ModelB, pixel_to_distance

from tests.calib.synth import projective_photo


@pytest.fixture
def model():
    ph, _ = projective_photo(noise_px=0.5)
    m = ModelB.fit(ph)
    assert m.ok
    return m


def test_identity_homography_reads_the_reference_calibration(model):
    d = distance.distance_map(np.eye(3), model, 1920, 1080)
    assert d.shape == (270, 480)
    u, v = 960, 1000  # near the bottom centre: close ground
    expect = pixel_to_distance(u, v, model.params, model.cx, model.cy)
    assert np.isclose(d[v // 4, u // 4], expect, atol=1e-6)
    assert np.isnan(d[0, 0])  # sky: no ground hit
    assert np.nanmin(d) >= 2.0 and np.nanmax(d) <= 18.0


def test_shifted_homography_samples_the_reference_elsewhere(model):
    T = np.array([[1, 0, 0], [0, 1, -40.0], [0, 0, 1]])  # target row v looks at reference row v-40: farther ground
    d0, d1 = distance.distance_map(np.eye(3), model, 1920, 1080), distance.distance_map(T, model, 1920, 1080)
    v = 1000
    assert np.nanmean(d1[v // 4]) > np.nanmean(d0[v // 4])
    assert np.isclose(d1[v // 4, 240], d0[(v - 40) // 4, 240], atol=1e-6)


def test_read_at_is_a_5x5_nanmedian_and_none_off_map():
    pred = np.full((100, 200), np.nan)
    pred[48:53, 98:103] = np.arange(25, dtype=float).reshape(5, 5)
    assert distance.read_at(pred, 100, 50) == 12.0
    pred[52, 102] = np.nan  # drop the 24: median of 0..23
    assert distance.read_at(pred, 100, 50) == 11.5
    assert distance.read_at(pred, 10, 10) is None   # all-NaN window
    assert distance.read_at(pred, 0, 0) is None     # clipped corner window, still all NaN
    assert distance.read_at(pred, 1e9, 1e9) is None  # far outside: empty window


def test_crop_banner_scales_with_frame_height():
    assert distance.crop_banner(Image.new("RGB", (1920, 1080))).size == (1920, 995)
    assert distance.crop_banner(Image.new("RGB", (3840, 2160))).size == (3840, 1990)


def test_normalize_is_imagenet_on_518():
    x = distance.normalize(Image.new("RGB", (640, 480), (124, 116, 104)))
    assert x.shape == (3, 518, 518) and np.allclose(x, 0, atol=0.02)


def test_homography_needs_four_points():
    pytest.importorskip("cv2")
    assert distance.homography(np.zeros((3, 2)), np.zeros((3, 2))) == (None, 0)
    src = np.array([[0, 0], [100, 0], [100, 100], [0, 100], [50, 50], [20, 70]], float)
    H, inl = distance.homography(src, src + [5, 7])
    assert inl == 6 and np.allclose(H @ [0, 0, 1], [5, 7, 1])


class FakeRoma:
    """Stands in for romatch: returns fixed keypoints, reference first, target second (RoMa's A/B order)."""

    def __init__(self, k_ref, k_tgt):
        self.k_ref, self.k_tgt = k_ref, k_tgt

    def match(self, im_a, im_b, device=None):
        return "warp", "cert"

    def sample(self, warp, cert):
        return "matches", cert

    def to_pixel_coordinates(self, matches, H_A, W_A, H_B=None, W_B=None):
        import torch
        return torch.tensor(self.k_ref), torch.tensor(self.k_tgt)


def test_align_returns_target_to_reference_homography():
    pytest.importorskip("cv2")
    torch = pytest.importorskip("torch")
    k_tgt = np.array([[0, 0], [100, 0], [100, 100], [0, 100], [50, 50], [20, 70]], float)
    k_ref = k_tgt + [30, -10]  # the reference sees everything shifted
    d = distance.Distance.__new__(distance.Distance)
    d.roma, d.device, d.torch = FakeRoma(k_ref, k_tgt), "cpu", torch
    Hm, inl = d.align(Image.new("RGB", (200, 200)), Image.new("RGB", (200, 200)))
    assert inl == 6 and np.allclose(Hm @ [0, 0, 1], [30, -10, 1])  # target pixel → reference pixel


def test_seed_seeds_torch(monkeypatch):
    """The spread between line-ups comes from RoMa's torch sampling; MAGSAC is already deterministic, so only torch is seeded."""
    seeded = []
    torch = types.ModuleType("torch")
    torch.manual_seed = seeded.append
    monkeypatch.setitem(sys.modules, "torch", torch)
    distance.seed()
    assert seeded == [distance.SEED]


class Keypoints:
    """A tensor's `.cpu().numpy()`, without torch."""

    def __init__(self, k):
        self.k = k

    def cpu(self):
        return self

    def numpy(self):
        return self.k


def fake_torch(calls):
    """Just enough torch for align: fork_rng records where the global random state is saved and restored."""
    @contextlib.contextmanager
    def fork_rng(devices):
        calls.append("fork")
        yield
        calls.append("restore")

    return types.SimpleNamespace(random=types.SimpleNamespace(fork_rng=fork_rng))


class Recording(FakeRoma):
    """FakeRoma that records each step in `calls`, and needs no torch."""

    def __init__(self, calls):
        super().__init__(np.zeros((4, 2)), np.zeros((4, 2)))
        self.calls = calls

    def match(self, im_a, im_b, device=None):
        self.calls.append("match")
        return super().match(im_a, im_b, device)

    def sample(self, warp, cert):
        self.calls.append("sample")
        return super().sample(warp, cert)

    def to_pixel_coordinates(self, matches, H_A, W_A, H_B=None, W_B=None):
        return Keypoints(self.k_ref), Keypoints(self.k_tgt)


def recording_distance(calls, roma=None):
    d = distance.Distance.__new__(distance.Distance)
    d.roma, d.device, d.torch = roma or Recording(calls), "cpu", fake_torch(calls)
    return d


def test_align_seeds_before_roma_draws(monkeypatch):
    """Every line-up (a measurement's read and Compare's align_score alike) goes through align, and align seeds
    before RoMa samples its matches, inside a forked random state, so the same two photos always give the same
    homography and inlier count and nothing else in the process sees its draws."""
    calls = []
    monkeypatch.setattr(distance, "seed", lambda: calls.append("seed"))
    monkeypatch.setattr(distance, "homography", lambda src, dst: calls.append("homography") or (None, 0))
    d = recording_distance(calls)
    assert d.align(Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8))) == (None, 0)
    assert calls == ["fork", "seed", "match", "sample", "restore", "homography"]


def test_align_holds_the_lock_from_seed_to_homography(monkeypatch):
    """torch's generators are process-wide, so a second thread's line-up waits until the first has finished."""
    calls, entered, go = [], threading.Event(), threading.Event()

    class Blocking(Recording):
        def match(self, im_a, im_b, device=None):
            if not entered.is_set():  # the first line-up stops here until told to go on
                entered.set()
                assert go.wait(5)
            return super().match(im_a, im_b, device)

    monkeypatch.setattr(distance, "seed", lambda: calls.append("seed"))
    monkeypatch.setattr(distance, "homography", lambda src, dst: calls.append("homography") or (None, 0))
    d = recording_distance(calls, Blocking(calls))
    im = Image.new("RGB", (8, 8))
    first, second = (threading.Thread(target=d.align, args=(im, im)) for _ in range(2))
    first.start()
    assert entered.wait(5)
    second.start()
    second.join(0.2)
    assert second.is_alive() and calls == ["fork", "seed"]  # the second thread has not even forked
    go.set()
    first.join(5)
    second.join(5)
    one = ["fork", "seed", "match", "sample", "restore", "homography"]
    assert calls == one + one


def test_align_repeats_its_draw_and_restores_torch_state(monkeypatch):
    """With real torch: RoMa's draw (torch.multinomial) is the same on every line-up, whatever was drawn before,
    and the process's global random state is the same after a line-up as before it."""
    torch = pytest.importorskip("torch")

    class Sampling(FakeRoma):
        def sample(self, warp, cert):
            return torch.multinomial(torch.ones(1000), 20), cert

        def to_pixel_coordinates(self, matches, H_A, W_A, H_B=None, W_B=None):
            k = torch.stack([matches, matches], 1).double()
            return k, k + 1

    monkeypatch.setattr(distance, "homography", lambda src, dst: (src, dst))
    d = distance.Distance.__new__(distance.Distance)
    d.roma, d.device, d.torch = Sampling(None, None), "cpu", torch
    im = Image.new("RGB", (8, 8))
    before = torch.get_rng_state()
    a = d.align(im, im)
    assert torch.equal(torch.get_rng_state(), before)
    torch.rand(100)  # move the global state on: an unseeded draw would now differ
    b = d.align(im, im)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
