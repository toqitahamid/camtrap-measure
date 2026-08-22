"""The inference boundary: photos in, detections out. Everything GPU/torch lives behind `backend`.

`backend(paths, calibration, method)` takes the photos of one calibration window (so a real
implementation can batch them), the window's calibration row ({site, image_name, model: ModelB
json, ref_path: the flag photo on disk}), and the method name; it yields one `PhotoResult` per
path, in order: the animals found plus the photo's alignment score against the flag photo.

Two implementations: `fake` (deterministic per file name; ships so the app runs and demos without
a GPU) and `Real` (MegaDetector boxes → SpeciesNet species → RoMa-aligned unified net distance).
`warmup()` picks one at engine start and records what it chose in `state` for the status line.

Methods differ only in *where* the distance map is read: `md` at the detector box's bottom centre,
`sam3` at the feet of a SAM3 mask prompted with that box (loaded on first use — most runs never pay
for it). Every detection row records its method (store.detections key), so histories mixing both
stay interpretable and a rerun with the other method adds rows instead of replacing them.
"""

import json
import logging
import os
import random
import time
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import distance, weights

METHODS = {
    "md": {"label": "Fast — MegaDetector box",
           "hint": "Distance is read at the bottom of each animal's detection box. Fast; fine for most photos."},
    "sam3": {"label": "Precise — SAM3 outline (slower)",
             "hint": "SAM3 outlines each animal and the distance is read where its feet touch the ground. "
                     "Several times slower; better when animals are partly hidden or the box is loose."},
}
# ponytail: which method is the default is decided by the research-repo comparison (CONTEXT open item 2,
# bbox-bottom vs mask ground contact on the labeled data); until then the fast one. One-line change.
DEFAULT_METHOD = "md"
SPECIES = ["white-tailed deer", "white-tailed deer", "white-tailed deer", "raccoon", "unsure"]
FAKE_DELAY_S = float(os.environ.get("CAMTRAP_FAKE_DELAY", "0"))  # per photo, to demo the progress display
MD_CONF = 0.15  # deliberately low: weak boxes are kept and land in the suspicious gallery (ticket 09), never silently binned
MIN_SPECIES_SCORE = 0.2  # below this SpeciesNet is guessing → "unsure" (research knob, detect/speciesnet_wrap.py)
VRAM_FLOOR_GB = 8  # CONTEXT "Performance envelope": the design floor; smaller cards run, with a warning
FEET_BAND = 0.05  # the lowest 5% of a mask's rows are its feet (research 04_lindenthal_zeroshot/prep.py, 01_socrates)
MIN_MASK_IOU = 0.5  # a SAM3 mask is the box's animal when box and mask box overlap this much (research detect/label_deer.py)
SAM3_SCORE = 0.1  # keep weak SAM3 instances: the box match decides which mask is the animal's, not the score


@dataclass
class Detection:
    x1: float  # box, fractions of image width/height
    y1: float
    x2: float
    y2: float
    species: str
    confidence: float
    distance_m: float | None  # None: the photo did not align to its flag photo, or no ground under the animal
    q05_m: float | None
    q95_m: float | None


@dataclass
class PhotoResult:
    detections: list[Detection]
    match_score: int | None  # homography inliers against the flag photo; < distance.MIN_INLIERS = misfiled / moved camera


def fake(paths: list[Path], calibration: dict, method: str) -> Iterator[PhotoResult]:
    """Deterministic per file name, so tests and demos get stable numbers."""
    for p in paths:
        rng = random.Random(p.name)
        dets = []
        for _ in range(rng.choice([0, 1, 1, 2])):
            d = rng.uniform(3, 25)
            x, y, w = rng.uniform(0, 0.7), rng.uniform(0.3, 0.7), rng.uniform(0.1, 0.3)
            dets.append(Detection(x, y, x + w, min(1, y + w * 0.8), rng.choice(SPECIES), rng.uniform(0.4, 0.99),
                                  round(d, 2), round(d * 0.85, 2), round(d * 1.2, 2)))
        if FAKE_DELAY_S:
            time.sleep(FAKE_DELAY_S)
        yield PhotoResult(dets, rng.choice([9, 60, 180, 320]) if dets else None)  # 9 < MIN_INLIERS: a few photos look misfiled


def species_label(cls: str, score: float) -> str:
    """SpeciesNet class 'uuid;class;order;family;genus;species;common' + score → the name we store.
    Any deer-family prediction is a white-tailed deer (the region's only wild deer); a weak
    prediction is 'unsure' rather than a guessed name; everything else keeps its common name."""
    parts = cls.split(";")
    if "cervidae" in parts and score >= MIN_SPECIES_SCORE:
        return "white-tailed deer"
    if score < MIN_SPECIES_SCORE:
        return "unsure"
    return next((p for p in reversed(parts) if p), "unsure")  # common name, else the finest rank SpeciesNet committed to


def foot_pixel(mask: np.ndarray) -> tuple[int, int] | None:
    """Ground-contact pixel (u, v) of a boolean mask: median column of its lowest FEET_BAND rows, lowest row.
    None for an empty mask. Verbatim rule from the research prep (contact pixel of every distance label)."""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return None
    band = ys >= np.quantile(ys, 1 - FEET_BAND)
    return int(np.median(xs[band])), int(ys[band].max())


def box_iou(a, b) -> float:
    """IoU of two xyxy boxes."""
    iw, ih = max(0.0, min(a[2], b[2]) - max(a[0], b[0])), max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def contacts(boxes: list[list[float]], masks: list[tuple[np.ndarray, list[float]]], width: int, height: int) -> list[tuple[float, float]]:
    """Ground contact per detector box (xyxy pixels), as image fractions: the feet of the SAM3 mask whose own box
    best overlaps it (≥ MIN_MASK_IOU), else the box's bottom centre — a box SAM3 could not outline still gets a number.
    SAM3's box prompt is an exemplar, so it returns every instance it sees (research sam3_wrap.py); match, never take [0]."""
    out = []
    for b in boxes:
        iou, best = max(((box_iou(b, m[1]), m[0]) for m in masks), key=lambda t: t[0], default=(0.0, None))
        foot = foot_pixel(best) if iou >= MIN_MASK_IOU else None
        out.append(((foot[0] + 0.5) / width, (foot[1] + 0.5) / height) if foot is not None  # pixel centre: read_at rounds back to it
                   else ((b[0] + b[2]) / 2 / width, b[3] / height))
    return out


def _is_oom(e: Exception) -> bool:
    return any(s in str(e) for s in ("out of memory", "CUBLAS_STATUS_ALLOC_FAILED", "CUDNN_STATUS_NOT_INITIALIZED"))


class Real:
    """MegaDetector animal boxes, SpeciesNet species per box, RoMa-aligned unified-net distance at each
    box's ground contact. Loaded once, kept resident. FP16 via autocast on CUDA; SpeciesNet batch size
    probed against the VRAM actually free, then halved on any out-of-memory during a run."""

    def __init__(self, weights_dir: Path):
        import numpy as np
        import torch
        from megadetector.detection.run_detector import load_detector
        from speciesnet.classifier import SpeciesNetClassifier
        from speciesnet.utils import BBox

        self.np, self.torch, self.BBox = np, torch, BBox
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.warning = None
        self.weights_dir = weights_dir
        self.manifest = json.loads((weights_dir / "manifest.json").read_text())
        self.md = load_detector(str(weights_dir / self.manifest["megadetector"]), force_cpu=self.device == "cpu")
        self.sn = SpeciesNetClassifier(str(weights_dir / self.manifest["speciesnet"]), device=self.device)
        self.dist = distance.Distance(weights_dir, self.device)
        self.sam3 = None  # (model, processor) once the precise method has been asked for
        if self.device == "cuda":
            gb = torch.cuda.get_device_properties(0).total_memory / 2**30
            if gb < VRAM_FLOOR_GB:
                self.warning = f"This GPU has {gb:.1f} GB of memory, below the {VRAM_FLOOR_GB} GB the app is designed for — runs will be slow."
            self.batch = self._probe_batch()
        else:
            self.batch = 4

    def _autocast(self, dtype=None):
        """Mixed precision on CUDA (fp16 unless told otherwise), nothing on the CPU."""
        return self.torch.autocast("cuda", dtype=dtype or self.torch.float16) if self.device == "cuda" else nullcontext()

    def _probe_batch(self) -> int:
        """Half the largest SpeciesNet batch (≤64) whose forward pass fits right now — the other half
        is headroom for MegaDetector's activations, which are not allocated yet at startup."""
        size = self.sn.IMG_SIZE
        for b in (64, 32, 16, 8, 4, 2, 1):
            try:
                with self.torch.no_grad(), self._autocast():
                    self.sn.model(self.torch.zeros(b, size, size, 3, device=self.device))
                return max(1, b // 2)
            except (self.torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if not _is_oom(e):
                    raise
                self.torch.cuda.empty_cache()
        return 1

    def __call__(self, paths: list[Path], calibration: dict, method: str) -> Iterator[PhotoResult]:
        from PIL import Image

        # ponytail: serial decode + one MegaDetector call per photo; thread-prefetch JPEG decode and
        # batch MD if the dept's photo volume makes a run span days.
        for p in paths:
            with Image.open(p) as im:
                im = im.convert("RGB")
            with self.torch.no_grad(), self._autocast():
                out = self.md.generate_detections_one_image(self.np.array(im), image_id=p.name, detection_threshold=MD_CONF)
            animals = [d for d in out.get("detections", []) if str(d["category"]) == "1"]  # 1 = animal
            if not animals:
                # ponytail: empty frames skip alignment (most of a season); align them too if the
                # moved-camera alarm should fire before the first animal shows up.
                yield PhotoResult([], None)
                continue
            boxes = [d["bbox"] for d in animals]
            names = self._species(im, boxes)
            points = self._precise(im, boxes) if method == "sam3" else [(x + w / 2, y + h) for x, y, w, h in boxes]
            quantiles, inliers = self.dist.read(im, calibration, points)
            dets = []
            for d, name, q in zip(animals, names, quantiles):
                x, y, w, h = d["bbox"]
                q05, q50, q95 = q if q else (None, None, None)
                dets.append(Detection(x, y, x + w, y + h, name, float(d["conf"]), q50, q05, q95))
            yield PhotoResult(dets, inliers)

    def _sam3(self):
        """SAM3 (transformers port of facebook/sam3), loaded on first use so the fast method never pays its VRAM."""
        if self.sam3 is None:
            if "sam3" not in self.manifest:
                raise RuntimeError("The precise method needs the SAM3 weights, which this computer has not downloaded yet "
                                   "— restart the app while online, then try again.")
            from transformers import Sam3Model, Sam3Processor
            d = self.weights_dir / self.manifest["sam3"]
            # ponytail: fp32 weights (3.4 GB) under bf16 autocast as the research ran it; load in bf16 if a small card
            # trips here.
            self.sam3 = Sam3Model.from_pretrained(d).to(self.device).eval(), Sam3Processor.from_pretrained(d)
        return self.sam3

    def _precise(self, im, boxes: list[list[float]]) -> list[tuple[float, float]]:
        """Ground contact per box (relative xywh) from SAM3 masks: the image is encoded once, each box prompts
        on the shared features (research sam3_wrap.segment_from_boxes, which re-encoded per box)."""
        torch = self.torch
        model, proc = self._sam3()
        W, H = im.size
        px = [[x * W, y * H, (x + w) * W, (y + h) * H] for x, y, w, h in boxes]
        # SAM3 must run in bf16 (fp16 overflows in its ViTDet backbone — research sam3_wrap.py); a card without bf16
        # runs it in fp32, slower but right.
        ctx = self._autocast(torch.bfloat16) if self.dist.dtype == torch.bfloat16 else nullcontext()
        with torch.no_grad(), ctx:
            enc = proc(images=im, return_tensors="pt").to(self.device)
            vision = model.get_vision_features(pixel_values=enc.pixel_values)
            masks = []
            for b in px:
                prompt = proc(input_boxes=[[b]], original_sizes=[[H, W]], return_tensors="pt").to(self.device)
                out = model(vision_embeds=vision, **{k: v for k, v in prompt.items() if k != "original_sizes"})
                res = proc.post_process_instance_segmentation(out, threshold=SAM3_SCORE, target_sizes=[(H, W)])[0]
                masks += list(zip(res["masks"].cpu().numpy().astype(bool), res["boxes"].cpu().tolist()))
        return contacts(px, masks, W, H)

    def _species(self, im, boxes: list[list[float]]) -> list[str]:
        """One SpeciesNet crop per box (relative xywh), classified in VRAM-sized batches."""
        crops = [self.sn.preprocess(im, bboxes=[self.BBox(*b)]) for b in boxes]
        names: list[str] = []
        while len(names) < len(crops):
            chunk = crops[len(names):len(names) + self.batch]
            try:
                with self.torch.no_grad(), self._autocast():
                    preds = self.sn.batch_predict([str(j) for j in range(len(chunk))], chunk)
            except (self.torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if not _is_oom(e) or self.batch == 1:
                    raise
                self.torch.cuda.empty_cache()
                self.batch = max(1, self.batch // 2)  # a busy photo mid-run: back off and keep going
                continue
            for pred in preds:
                c = pred.get("classifications")
                names.append(species_label(c["classes"][0], c["scores"][0]) if c else "unsure")
        return names


# --- choosing a backend at engine start -----------------------------------------------------

backend = fake
# status: loading | ready | error. Starts ready-on-fake so the API works before/without warmup (tests, dev).
state: dict = {"status": "ready", "backend": "fake", "device": None, "batch": None, "weights": None,
               "warning": None, "error": None, "download": None}  # download: {done_gb, total_gb} while weights are fetched


def models_installed() -> bool:
    """Is the [inference] extra (torch, MegaDetector, SpeciesNet) importable?"""
    try:
        import megadetector, speciesnet, torch  # noqa: F401
        return True
    except ImportError:
        return False


def warmup() -> None:
    """Pick the backend once: real models when torch + weights are available, else the fake with a
    visible warning. Runs in a thread at engine start; the UI polls `state` until status != loading."""
    global backend
    state.update(status="loading", error=None, warning=None)
    if not models_installed():
        state.update(status="ready", warning="FAKE inference — no models installed (uv sync --extra inference). "
                                             "Numbers are made up.")
        return
    # The models' libraries switch root logging to INFO on import, and the HTTP client then narrates every weights
    # request into the launcher console (seen at the first Windows launch). Warnings only — the window shows the download.
    logging.getLogger().setLevel(logging.WARNING)
    warnings = []
    try:
        w = weights.ensure(progress=lambda done, total: state.update(download={"done_gb": round(done / 2**30, 2),
                                                                               "total_gb": round(total / 2**30, 2)}))
        state["download"] = None
        state["weights"] = w["version"] + (" (offline — cached copy)" if w["offline"] else "")
        if w["problem"]:
            warnings.append(f"Weights could not be checked for updates: {w['problem']}. Using the cached copy.")
        real = Real(w["dir"])
    except Exception as e:
        state["download"] = None
        state.update(status="error", error=str(e) if isinstance(e, weights.WeightsMissing)
                     else f"Models failed to load ({type(e).__name__}: {e}).")
        return
    backend = real
    if real.device != "cuda":
        warnings.append("No GPU visible — running on the CPU, which is many times slower. "
                        "Check that the NVIDIA driver is installed and the card is seated.")
    if real.warning:
        warnings.append(real.warning)
    state.update(status="ready", backend="real", device=real.device, batch=real.batch,
                 warning=" · ".join(warnings) or None)
