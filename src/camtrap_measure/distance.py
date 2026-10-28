"""Aligned-reference distance: RoMa aligns the calibration's flag photo to each target photo, the
unified distance+CQR net reads horizontal ground distance with a 90% band at each animal's ground
contact, and the alignment inlier count is the misfile / moved-camera alarm.

Ported from ../distance_estimation@6a6eed5 — change the math there first:
  transport/matchers.py                      match_roma: dense warp → sampled matches
  transport/build_prompts_roma.py            MAGSAC homography → stride-4 grid → pixel_to_distance → D_R
  transport/gate_roma.py                     published gate: fewer than MIN_INLIERS inliers → suspicious (the app stores
                                             the numbers and lets the export gate exclude them)
  experiments/refnet/10_cv4e_pipeline/model.py                        QuantileHead + load_unified (verbatim)
  experiments/refnet/29_testsplit_revision/eval_intervals_rollfix.py  7-ch input, bf16, 5×5 nanmedian readout
The paper ships the raw [q05, q95] band (E = 0; docs/claims.md, R4 rollfix refresh). A weights manifest may carry a
range factor k (`range_k`, the range-factor change, ADR 0004) that widens the band around q50 (`widen`); without one the band stays raw.

The numpy half (distance_map, read_at, crop_banner) has no torch dependency and is unit-tested;
`Distance` needs the [inference] extra and the weights manifest entries unified / roma / dinov2.
"""

import json
import math
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .calib.model_b import ModelB, pixel_to_distance

SIZE = 518
PROMPT_SCALE = 20.0  # metres → ~[0, 1]
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], np.float32).reshape(3, 1, 1)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], np.float32).reshape(3, 1, 1)
BANNER_Y = 995  # of 1080: the camera's info strip below this row is identical across photos — cropped before matching
STRIDE = 4
D_MIN, D_MAX = 2.0, 18.0  # reference distance map is trusted only here (training range)
UPSAMPLE_RES = 864       # RoMa's own default, and what the research ran (transport/matchers.py)
UPSAMPLE_RES_TIGHT = 672  # the warp the dept's 8 GB card can hold while the desktop is also using it
TIGHT_CARD_GB = 10        # below this much VRAM in total, the 864 warp does not fit and the run crawls

# Two ways to run the same models. RESEARCH reproduces the published pipeline exactly — bfloat16 autocast
# over fp32 weights and RoMa at its own defaults — and is what the app uses unless told otherwise, because
# the numbers this app prints are the paper's numbers. FAST trades a few centimetres for roughly ten times
# the speed on a card too small for the published settings; every difference is a `fidelity == FAST` branch below.
RESEARCH, FAST = "research", "fast"
FIDELITIES = (RESEARCH, FAST)
# What the status line calls the two models this stage puts on the card. RoMa's DINOv2 backbone is not
# named separately: it is part of RoMa, and the bar answers "what is running", not "what is imported".
# The unified net is "the distance model" on screen, not "Depth Anything V2": the technician needs to know
# which of the app's steps is running, and the architecture it was fine-tuned from tells them nothing.
MODELS = ["RoMa", "distance model"]
MIN_INLIERS = 15  # published gate (reports/gate_57cam.md): fewer homography inliers = misfiled or moved camera
SEED = 0  # RoMa samples its matches with torch.multinomial; every line-up seeds torch with this first, so the same two
          # photos line up the same way on the same computer, software, device and fidelity (the fixed-seed change).
          # MAGSAC needs no seed: it is already deterministic on the same matches.
HALF = 2  # 5×5 readout window


def crop_banner(im: Image.Image) -> Image.Image:
    # ponytail: research hard-codes 995 px on 1080-high frames; scaled here so a 4K camera still crops its strip.
    return im.crop((0, 0, im.width, int(round(im.height * BANNER_Y / 1080))))


def distance_map(Hm: np.ndarray, model: ModelB, width: int, height: int) -> np.ndarray:
    """Reference ground distance seen from the target frame: warp a stride-4 target grid through the
    homography Hm (target → reference pixels) and read the reference calibration there.
    NaN off the ground or outside 2–18 m."""
    us, vs = np.meshgrid(np.arange(0, width, STRIDE, dtype=float), np.arange(0, height, STRIDE, dtype=float))
    pts = Hm @ np.stack([us.ravel(), vs.ravel(), np.ones(us.size)])
    ua, va = pts[0] / pts[2], pts[1] / pts[2]
    d = pixel_to_distance(ua, va, model.params, model.cx, model.cy).reshape(us.shape)
    return np.where((d >= D_MIN) & (d <= D_MAX), d, np.nan)


def read_at(pred: np.ndarray, u: float, v: float) -> float | None:
    """5×5 nanmedian of a full-resolution map at pixel (u, v); None when the window holds nothing finite."""
    iu, iv = int(round(u)), int(round(v))
    patch = pred[max(0, iv - HALF):iv + HALF + 1, max(0, iu - HALF):iu + HALF + 1]
    return float(np.nanmedian(patch)) if patch.size and np.isfinite(patch).any() else None


RANGE_K = "range_k"  # the weights manifest key that carries the range factor k (the range-factor change, ADR 0004)
RANGE_K_MAX = 5.0  # the largest usable k; scripts/upload_weights.py keeps a copy (RANGE_K_MAX there), keep them equal


def usable_range_k(k) -> bool:
    """Is k a usable range factor: a real number (not a bool), finite, above 0 and at most RANGE_K_MAX? A JSON integer
    too large for a float (10**400) is not: math.isfinite raises OverflowError on it, which counts as no."""
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        return False
    try:
        return math.isfinite(k) and 0 < k <= RANGE_K_MAX
    except OverflowError:
        return False


def range_factor(manifest: dict) -> tuple[float, str | None]:
    """The range factor k of a weights manifest, and the problem when the manifest's value is unusable.

    No `range_k` key gives (1.0, None): the raw range, as every manifest before the range-factor change (ADR 0004). A value that is not a finite
    number above 0 and at most RANGE_K_MAX (a string, true, 0, -1, NaN, infinity, 6, 10**400) gives (1.0, why): the
    run goes on with the raw range. The problem goes to the research log and the backend's stderr, never to the
    window: staff never see k (decided 2026-10-13)."""
    if RANGE_K not in manifest:
        return 1.0, None
    k = manifest[RANGE_K]
    if not usable_range_k(k):
        try:
            shown = repr(k)
        except ValueError:  # an integer past Python's digit limit for str()
            shown = "a very large integer"
        if len(shown) > 40:
            shown = shown[:37] + "..."
        return 1.0, (f"The models' range_k setting ({shown}) is not a number above 0 and at most {RANGE_K_MAX:g}, "
                     "so the 90% ranges are not widened.")
    return float(k), None


def widen(q05, q50, q95, k: float) -> tuple:
    """The 90% range of one read-out, widened by the range factor k around its median: each log arm is multiplied by k.

        lo = q50 · (q05 / q50)^k,   hi = q50 · (q95 / q50)^k,   q50 unchanged.

    k = 1.0 returns the three values exactly as given (no arithmetic, so current answers do not move by a rounding).
    k must pass usable_range_k (0 < k ≤ RANGE_K_MAX, not a bool), else ValueError. An arm too large for a float comes
    back as infinity, never as an OverflowError.
    The research fitted k on these very values: per-point (q05, q50, q95) after read_at's 5×5 nanmedian (research
    folder 73, widen_loco.py). Edge cases: a None or non-finite value is passed through; with q50 None, non-finite or
    ≤ 0 nothing is changed (there is no log arm); an arm at or below 0 is not scaled. The order lo ≤ q50 ≤ hi is kept:
    an inverted arm (q05 > q50 or q95 < q50) comes back as q50."""
    if isinstance(k, bool):  # before the k = 1.0 shortcut: True == 1.0
        raise ValueError(f"range factor k must be a number, not {k!r}")
    if k == 1.0:
        return q05, q50, q95
    if not usable_range_k(k):
        raise ValueError(f"range factor k must be a finite number above 0 and at most {RANGE_K_MAX:g}")
    if q50 is None or not math.isfinite(q50) or q50 <= 0:
        return q05, q50, q95

    def arm(q):
        if q <= 0:
            return q
        try:
            return q50 * (q / q50) ** k
        except OverflowError:  # (q / q50)^k past the largest float: only an arm above q50 can get there
            return math.inf

    lo = q05 if q05 is None or not math.isfinite(q05) else min(arm(q05), q50)
    hi = q95 if q95 is None or not math.isfinite(q95) else max(arm(q95), q50)
    return lo, q50, hi


KDE_CHUNK = 4096  # rows of the density matrix computed at once; the whole matrix is 3.2 GB


def kde_chunked(x, std=0.1, half=True, down=None, chunk=KDE_CHUNK):
    """RoMa's match-density estimate, one band of rows at a time.

    Verbatim arithmetic from romatch.utils.kde, which builds the whole N x N distance matrix at once:
    with RoMa's own defaults N is 40000 (4x the 10000 samples, "balanced" mode), so that matrix is
    3.2 GB in half precision and the expression materialises it several times over. On an 8 GB card
    with a browser open the run died there before the first photo (seen 2026-08-23).

    Chunked, the peak is chunk x N instead, the sum is the same one, and the sampling that follows is
    unchanged - so the published inlier gate (MIN_INLIERS) still means what the research measured.
    """
    import torch

    if half:
        x = x.half()
    ref = x[::down] if down is not None else x
    scale = -1 / (2 * std**2)
    out = torch.empty(len(x), device=x.device, dtype=x.dtype)
    for i in range(0, len(x), chunk):
        d = torch.cdist(x[i:i + chunk], ref)
        out[i:i + chunk] = d.mul_(d).mul_(scale).exp_().sum(dim=-1)
    return out


def use_chunked_kde() -> None:
    """Install `kde_chunked` where RoMa's sampler looks it up (it imported the name at module load)."""
    from romatch.models import matcher

    matcher.kde = kde_chunked


def homography(src: np.ndarray, dst: np.ndarray):
    """MAGSAC homography src → dst (pixels). → (H | None, inlier count)."""
    import cv2

    if len(src) < 4:
        return None, 0
    Hm, inl = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 3.0)
    return Hm, int(inl.sum()) if inl is not None else 0


def seed() -> None:
    """Seed torch (every device) before RoMa samples its matches, so a re-run of the same photo lines up the same way."""
    import torch

    torch.manual_seed(SEED)


# torch's generators are process-wide: Compare and a measurement aligning in two threads would interleave their draws.
_aligning = threading.Lock()


def normalize(im: Image.Image) -> np.ndarray:
    """RGB photo → (3, SIZE, SIZE) float32, ImageNet-normalized."""
    arr = np.asarray(im.resize((SIZE, SIZE), Image.BILINEAR), np.float32).transpose(2, 0, 1) / 255.0
    return (arr - IMAGENET_MEAN) / IMAGENET_STD


def native_bf16(torch) -> bool:
    """Does this card do bfloat16 in hardware?

    `torch.cuda.is_bf16_supported()` answers True on cards that only emulate it, and the emulation is
    slower than either alternative: on the dept's RTX 2060 SUPER (Turing, compute 7.5) the same
    convolutions took 122 ms in bf16, 44 ms in fp32 and 25 ms in fp16 (measured 2026-08-23). The app
    was picking bf16 on that card, so the unified net ran five times slower than it needed to.
    """
    try:
        return bool(torch.cuda.is_bf16_supported(including_emulation=False))
    except TypeError:  # older torch: no such argument, and compute capability is the same question
        return torch.cuda.get_device_properties(0).major >= 8


def autocast_dtype(torch, device: str, fidelity: str):
    """The precision a run will use, answerable before a single weight is loaded — the status line has
    to name it while the models are still on disk.

    The research ran bfloat16 (29_testsplit_revision/eval_intervals_rollfix.py), so research fidelity
    asks for bfloat16 and takes the emulation on a card with no hardware for it. Only fast fidelity is
    allowed to swap in the fp16 the card actually implements.
    """
    return (torch.bfloat16 if device == "cuda" and (fidelity == RESEARCH or native_bf16(torch))
            else torch.float16)


def load_unified(ckdir: Path, device: str):
    """Rebuild the wrapped architecture from the saved config (num_channels=7 ⇒ 7-ch patch embed)
    and load the state dict strictly. QuantileHead is verbatim from 10_cv4e_pipeline/model.py."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from safetensors.torch import load_file
    from transformers import AutoConfig, AutoModelForDepthEstimation

    class QuantileHead(nn.Module):
        """Wraps the original DepthAnythingDepthEstimationHead: conv1→interp→conv2→relu exposes the
        penultimate features, conv3 keeps the metric median q50, two softplus-delta heads give a
        monotone log-space interval. Returns stack([q05, q50, q95], dim=1)."""

        def __init__(self, base):
            super().__init__()
            self.base = base
            hc = base.conv3.in_channels
            self.head_lo = nn.Conv2d(hc, 1, kernel_size=1)
            self.head_hi = nn.Conv2d(hc, 1, kernel_size=1)

        def _penultimate(self, hidden_states, patch_height, patch_width):
            b = self.base
            x = b.conv1(hidden_states[b.head_in_index])
            x = F.interpolate(x, (int(patch_height * b.patch_size), int(patch_width * b.patch_size)),
                              mode="bilinear", align_corners=True)
            x = b.conv2(x)
            return b.activation1(x)

        def forward(self, hidden_states, patch_height, patch_width):
            b = self.base
            feat = self._penultimate(hidden_states, patch_height, patch_width)
            q50 = (b.activation2(b.conv3(feat)) * b.max_depth).squeeze(1)
            m = torch.log(q50.clamp(min=1e-3)).detach()
            fd = feat.detach()
            q05 = torch.exp(m - F.softplus(self.head_lo(fd)).squeeze(1))
            q95 = torch.exp(m + F.softplus(self.head_hi(fd)).squeeze(1))
            return torch.stack([q05, q50, q95], dim=1)

    cfg = AutoConfig.from_pretrained(ckdir)
    model = AutoModelForDepthEstimation.from_config(cfg)
    model.head = QuantileHead(model.head)
    model.load_state_dict(load_file(ckdir / "model.safetensors"), strict=True)
    return model.to(device).eval()


def upsample_res(torch, device: str, fidelity: str) -> int:
    """RoMa's refinement resolution. The research default at research fidelity, always; under fast
    fidelity, chosen by the size of the card and never by what is free at this moment, so that a given
    computer still produces the same numbers every run. Answerable before RoMa is loaded: a stored line-up
    is keyed on it (inference.Real.link_setting).

    Measured on the dept's 8 GB RTX 2060 SUPER (2026-08-23, scripts/profile_run.py): at 864 one photo
    needs 6.3 GB, more than Windows leaves free with a browser open, so the driver quietly serves the
    overflow from system memory over PCIe and a photo takes 3.6 to 26 seconds - the same run, the same
    settings, a lottery. At 672 it needs 4.4 GB, fits, and takes about 2. The metres move by ~8 cm,
    which is inside the 3-17 cm that repeat runs of identical settings moved before the fixed-seed change seeded
    RoMa's match sampling (the draw-to-draw spread). A card big enough for 864 keeps the research default.
    """
    if device != "cuda" or fidelity == RESEARCH:
        return UPSAMPLE_RES
    total_gb = torch.cuda.get_device_properties(0).total_memory / 2**30
    return UPSAMPLE_RES_TIGHT if total_gb < TIGHT_CARD_GB else UPSAMPLE_RES


class Distance:
    """RoMa + unified net, loaded once. `read()` gives [q05, q50, q95] per ground-contact point."""

    def __init__(self, weights_dir: Path, device: str, fidelity: str = RESEARCH):
        import torch
        from romatch import roma_outdoor

        self.torch, self.device, self.fidelity = torch, device, fidelity
        use_chunked_kde()
        self.dtype = autocast_dtype(torch, device, fidelity)
        manifest = json.loads((weights_dir / "manifest.json").read_text())
        self.upsample_res = self._upsample_res()
        # custom local_corr CUDA kernel is not built anywhere we run; pure-torch fallback as in the research runs
        self.roma = roma_outdoor(device=device, use_custom_corr=False, upsample_res=self.upsample_res,
                                 weights=torch.load(weights_dir / manifest["roma"], map_location=device),
                                 dinov2_weights=torch.load(weights_dir / manifest["dinov2"], map_location=device))
        self.net = load_unified(weights_dir / manifest["unified"], device)
        self.refs: dict[tuple, tuple] = {}  # per calibration: (banner-cropped flag photo, its normalized tensor, ModelB)
        if device == "cuda" and fidelity == FAST:
            # Half weights, not just half arithmetic: under autocast the fp32 net is cast on every forward
            # and the cast copies are kept for the region, ~0.6 GB that buys nothing. It is not free
            # numerically, though — the ops autocast keeps in fp32 (the head's log, exp and softplus) then
            # get half inputs — so the research pipeline keeps its fp32 weights.
            self.net = self.net.to(self.dtype)

    def _upsample_res(self) -> int:
        return upsample_res(self.torch, self.device, self.fidelity)

    def reference(self, calibration: dict) -> tuple:
        """Reference features for one calibration window, computed once and kept. Keyed on the annotation
        version, the fit rules and the flag photo's mtime, so a relabel, a refit or a re-upload after a sync is never
        served stale."""
        key = (calibration["site"], calibration["image_name"], calibration.get("updated_at"), calibration.get("fit_version"),
               Path(calibration["ref_path"]).stat().st_mtime_ns)
        if key not in self.refs:
            with Image.open(calibration["ref_path"]) as im:
                im = im.convert("RGB")
            self.refs[key] = (crop_banner(im), self.torch.from_numpy(normalize(im)), ModelB.from_dict(json.loads(calibration["model"])))
        return self.refs[key]

    def align(self, ref_crop: Image.Image, tgt_crop: Image.Image):
        """Homography target → reference pixels from RoMa's dense warp, seeded. → (H | None, inliers).
        The seed is forked: torch's global random state is the same after a line-up as before it."""
        torch = self.torch
        with _aligning:
            with torch.random.fork_rng(devices=[torch.cuda.current_device()] if self.device == "cuda" else []):
                seed()
                warp, cert = self.roma.match(ref_crop, tgt_crop, device=self.device)
                matches, cert = self.roma.sample(warp, cert)
            k_ref, k_tgt = self.roma.to_pixel_coordinates(matches, ref_crop.height, ref_crop.width, tgt_crop.height, tgt_crop.width)
            return homography(k_tgt.cpu().numpy(), k_ref.cpu().numpy())

    def read(self, im: Image.Image, calibration: dict, contacts: list[tuple[float, float]]) -> tuple[list[tuple | None], int]:
        """contacts = (x, y) fractions of the image. → ([(q05, q50, q95) | None per contact], inliers).
        A photo that does not align to its flag photo gets no numbers at all. The raw range: the app reads through
        inference.Real, which widens it by the manifest's range factor (`widen`); nothing in the app calls this."""
        ref_crop, _, _ = self.reference(calibration)
        Hm, inliers = self.align(ref_crop, crop_banner(im))
        if Hm is None:
            return [None] * len(contacts), inliers
        width, height = im.size
        return self.quantiles(self.predict(im, calibration, Hm), [(fx * width, fy * height) for fx, fy in contacts]), inliers

    def predict(self, im: Image.Image, calibration: dict, Hm: np.ndarray) -> np.ndarray:
        """The [q05, q50, q95] maps of a photo, (3, H, W), read through a line-up Hm (photo -> flag photo pixels)
        that was measured already: the photo's own, or the day photo's that a night photo or a weak day photo
        borrows (lineup.py)."""
        torch = self.torch
        import torch.nn.functional as F

        _, ref_t, model = self.reference(calibration)
        width, height = im.size
        d = np.nan_to_num(distance_map(Hm, model, width, height).astype(np.float32), nan=0.0)
        d_r = F.interpolate(torch.from_numpy(d)[None, None], (SIZE, SIZE), mode="nearest")[0, 0]
        x = torch.cat([torch.from_numpy(normalize(im)), ref_t, (d_r / PROMPT_SCALE)[None]], 0)[None].to(self.device)
        with torch.no_grad(), torch.autocast("cuda", dtype=self.dtype, enabled=self.device == "cuda"):
            pred = self.net(pixel_values=x).predicted_depth  # (1, 3, SIZE, SIZE) = [q05, q50, q95]
        return F.interpolate(pred.float(), (height, width), mode="bilinear", align_corners=True)[0].cpu().numpy()

    @staticmethod
    def quantiles(pred: np.ndarray, points: list[tuple[float, float]]) -> list[tuple | None]:
        """(q05, q50, q95) at each pixel (u, v), 5×5 nanmedian; None where the window holds nothing. Raw: the range
        factor is applied by the caller (inference.Real.__call__, `widen`)."""
        out = []
        for u, v in points:
            qs = [read_at(pred[i], u, v) for i in range(3)]
            out.append(None if None in qs else (qs[0], qs[1], qs[2]))
        return out
