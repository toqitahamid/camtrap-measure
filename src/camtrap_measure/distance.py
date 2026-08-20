"""Aligned-reference distance: RoMa aligns the calibration's flag photo to each target photo, the
unified distance+CQR net reads horizontal ground distance with a 90% band at each animal's ground
contact, and the alignment inlier count is the misfile / moved-camera alarm.

Ported from ../distance_estimation@6a6eed5 — change the math there first:
  transport/matchers.py                      match_roma: dense warp → sampled matches
  transport/build_prompts_roma.py            MAGSAC homography → stride-4 grid → pixel_to_distance → D_R
  transport/gate_roma.py                     published gate: fewer than MIN_INLIERS inliers → suspicious (the app stores
                                             the numbers and lets the export gate exclude them — CONTEXT "Trust / review UX")
  experiments/refnet/10_cv4e_pipeline/model.py                        QuantileHead + load_unified (verbatim)
  experiments/refnet/29_testsplit_revision/eval_intervals_rollfix.py  7-ch input, bf16, 5×5 nanmedian readout
The paper ships the raw [q05, q95] band (E = 0; docs/claims.md, R4 rollfix refresh).

The numpy half (distance_map, read_at, crop_banner) has no torch dependency and is unit-tested;
`Distance` needs the [inference] extra and the weights manifest entries unified / roma / dinov2.
"""

import json
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
MIN_INLIERS = 15  # published gate (reports/gate_57cam.md): fewer homography inliers = misfiled or moved camera
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


def homography(src: np.ndarray, dst: np.ndarray):
    """MAGSAC homography src → dst (pixels). → (H | None, inlier count)."""
    import cv2

    if len(src) < 4:
        return None, 0
    Hm, inl = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, 3.0)
    return Hm, int(inl.sum()) if inl is not None else 0


def normalize(im: Image.Image) -> np.ndarray:
    """RGB photo → (3, SIZE, SIZE) float32, ImageNet-normalized."""
    arr = np.asarray(im.resize((SIZE, SIZE), Image.BILINEAR), np.float32).transpose(2, 0, 1) / 255.0
    return (arr - IMAGENET_MEAN) / IMAGENET_STD


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


class Distance:
    """RoMa + unified net, loaded once. `read()` gives [q05, q50, q95] per ground-contact point."""

    def __init__(self, weights_dir: Path, device: str):
        import torch
        from romatch import roma_outdoor

        self.torch, self.device = torch, device
        # ponytail: research ran bf16 only; fp16 on pre-Ampere cards is unverified for DA-V2-L — check on the dept GPU.
        self.dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else torch.float16
        manifest = json.loads((weights_dir / "manifest.json").read_text())
        # custom local_corr CUDA kernel is not built anywhere we run; pure-torch fallback as in the research runs
        self.roma = roma_outdoor(device=device, use_custom_corr=False,
                                 weights=torch.load(weights_dir / manifest["roma"], map_location=device),
                                 dinov2_weights=torch.load(weights_dir / manifest["dinov2"], map_location=device))
        self.net = load_unified(weights_dir / manifest["unified"], device)
        self.refs: dict[tuple, tuple] = {}  # per calibration: (banner-cropped flag photo, its normalized tensor, ModelB)

    def reference(self, calibration: dict) -> tuple:
        """Reference features for one calibration window, computed once and kept. Keyed on the annotation
        version and the flag photo's mtime, so a relabel or re-upload after a sync is never served stale."""
        key = (calibration["site"], calibration["image_name"], calibration.get("updated_at"),
               Path(calibration["ref_path"]).stat().st_mtime_ns)
        if key not in self.refs:
            with Image.open(calibration["ref_path"]) as im:
                im = im.convert("RGB")
            self.refs[key] = (crop_banner(im), self.torch.from_numpy(normalize(im)), ModelB.from_dict(json.loads(calibration["model"])))
        return self.refs[key]

    def align(self, ref_crop: Image.Image, tgt_crop: Image.Image):
        """Homography target → reference pixels from RoMa's dense warp. → (H | None, inliers)."""
        warp, cert = self.roma.match(ref_crop, tgt_crop, device=self.device)
        matches, cert = self.roma.sample(warp, cert)
        k_ref, k_tgt = self.roma.to_pixel_coordinates(matches, ref_crop.height, ref_crop.width, tgt_crop.height, tgt_crop.width)
        return homography(k_tgt.cpu().numpy(), k_ref.cpu().numpy())

    def read(self, im: Image.Image, calibration: dict, contacts: list[tuple[float, float]]) -> tuple[list[tuple | None], int]:
        """contacts = (x, y) fractions of the image. → ([(q05, q50, q95) | None per contact], inliers).
        A photo that does not align to its flag photo gets no numbers at all."""
        torch = self.torch
        import torch.nn.functional as F

        ref_crop, ref_t, model = self.reference(calibration)
        Hm, inliers = self.align(ref_crop, crop_banner(im))
        if Hm is None:
            return [None] * len(contacts), inliers
        width, height = im.size
        d = np.nan_to_num(distance_map(Hm, model, width, height).astype(np.float32), nan=0.0)
        d_r = F.interpolate(torch.from_numpy(d)[None, None], (SIZE, SIZE), mode="nearest")[0, 0]
        x = torch.cat([torch.from_numpy(normalize(im)), ref_t, (d_r / PROMPT_SCALE)[None]], 0)[None].to(self.device)
        with torch.no_grad(), torch.autocast("cuda", dtype=self.dtype, enabled=self.device == "cuda"):
            pred = self.net(pixel_values=x).predicted_depth  # (1, 3, SIZE, SIZE) = [q05, q50, q95]
        pred = F.interpolate(pred.float(), (height, width), mode="bilinear", align_corners=True)[0].cpu().numpy()
        out = []
        for fx, fy in contacts:
            qs = [read_at(pred[i], fx * width, fy * height) for i in range(3)]
            out.append(None if None in qs else (qs[0], qs[1], qs[2]))
        return out, inliers
