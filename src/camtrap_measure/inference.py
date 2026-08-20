"""The inference boundary: photos in, detections out. Everything GPU/torch lives behind `backend`.

`backend(paths, calibration, method)` takes the photos of one calibration window (so a real
implementation can batch them), the window's fitted calibration (`ModelB.to_dict()`), and the
method name; it yields one `list[Detection]` per path, in order.

Two implementations: `fake` (deterministic per file name; ships so the app runs and demos without
a GPU) and `Real` (MegaDetector boxes → SpeciesNet species; distance comes with ticket 07).
`warmup()` picks one at engine start and records what it chose in `state` for the status line.
"""

import json
import os
import random
import time
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from . import weights

METHODS = {"md": "MegaDetector (fast)", "sam3": "MegaDetector + SAM3 (precise, slower)"}
SPECIES = ["white-tailed deer", "white-tailed deer", "white-tailed deer", "raccoon", "unsure"]
FAKE_DELAY_S = float(os.environ.get("CAMTRAP_FAKE_DELAY", "0"))  # per photo, to demo the progress display
MD_CONF = 0.15  # deliberately low: weak boxes are kept and land in the suspicious gallery (ticket 09), never silently binned
MIN_SPECIES_SCORE = 0.2  # below this SpeciesNet is guessing → "unsure" (research knob, detect/speciesnet_wrap.py)
VRAM_FLOOR_GB = 8  # CONTEXT "Performance envelope": the design floor; smaller cards run, with a warning


@dataclass
class Detection:
    x1: float  # box, fractions of image width/height
    y1: float
    x2: float
    y2: float
    species: str
    confidence: float
    distance_m: float | None
    q05_m: float | None
    q95_m: float | None
    match_score: float | None  # RoMa alignment to the flag reference; low = misfiled / moved camera


def fake(paths: list[Path], calibration: dict, method: str) -> Iterator[list[Detection]]:
    """Deterministic per file name, so tests and demos get stable numbers."""
    for p in paths:
        rng = random.Random(p.name)
        dets = []
        for _ in range(rng.choice([0, 1, 1, 2])):
            d = rng.uniform(3, 25)
            x, y, w = rng.uniform(0, 0.7), rng.uniform(0.3, 0.7), rng.uniform(0.1, 0.3)
            dets.append(Detection(x, y, x + w, min(1, y + w * 0.8), rng.choice(SPECIES), rng.uniform(0.4, 0.99),
                                  round(d, 2), round(d * 0.85, 2), round(d * 1.2, 2), rng.uniform(0.5, 0.99)))
        if FAKE_DELAY_S:
            time.sleep(FAKE_DELAY_S)
        yield dets


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


def _is_oom(e: Exception) -> bool:
    return any(s in str(e) for s in ("out of memory", "CUBLAS_STATUS_ALLOC_FAILED", "CUDNN_STATUS_NOT_INITIALIZED"))


class Real:
    """MegaDetector animal boxes, SpeciesNet species per box. Loaded once, kept resident.
    FP16 via autocast on CUDA; SpeciesNet batch size probed against the VRAM actually free,
    then halved on any out-of-memory during a run."""

    def __init__(self, weights_dir: Path):
        import numpy as np
        import torch
        from megadetector.detection.run_detector import load_detector
        from speciesnet.classifier import SpeciesNetClassifier
        from speciesnet.utils import BBox

        self.np, self.torch, self.BBox = np, torch, BBox
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.warning = None
        manifest = json.loads((weights_dir / "manifest.json").read_text())
        self.md = load_detector(str(weights_dir / manifest["megadetector"]), force_cpu=self.device == "cpu")
        self.sn = SpeciesNetClassifier(str(weights_dir / manifest["speciesnet"]), device=self.device)
        if self.device == "cuda":
            gb = torch.cuda.get_device_properties(0).total_memory / 2**30
            if gb < VRAM_FLOOR_GB:
                self.warning = f"This GPU has {gb:.1f} GB of memory, below the {VRAM_FLOOR_GB} GB the app is designed for — runs will be slow."
            self.batch = self._probe_batch()
        else:
            self.batch = 4

    def _autocast(self):
        return self.torch.autocast("cuda", dtype=self.torch.float16) if self.device == "cuda" else nullcontext()

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

    def __call__(self, paths: list[Path], calibration: dict, method: str) -> Iterator[list[Detection]]:
        from PIL import Image

        # ponytail: serial decode + one MegaDetector call per photo; thread-prefetch JPEG decode and
        # batch MD if the dept's photo volume makes a run span days.
        for p in paths:
            with Image.open(p) as im:
                im = im.convert("RGB")
            with self.torch.no_grad(), self._autocast():
                out = self.md.generate_detections_one_image(self.np.array(im), image_id=p.name, detection_threshold=MD_CONF)
            boxes = [d for d in out.get("detections", []) if str(d["category"]) == "1"]  # 1 = animal
            names = self._species(im, [d["bbox"] for d in boxes])
            dets = []
            for d, name in zip(boxes, names):
                x, y, w, h = d["bbox"]
                # ponytail: distance/interval/match score are None until ticket 07 wires the unified net + RoMa.
                dets.append(Detection(x, y, x + w, y + h, name, float(d["conf"]), None, None, None, None))
            yield dets

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
               "warning": None, "error": None}


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
    warnings = []
    try:
        w = weights.ensure()
        state["weights"] = w["version"] + (" (offline — cached copy)" if w["offline"] else "")
        if w["problem"]:
            warnings.append(f"Weights could not be checked for updates: {w['problem']}. Using the cached copy.")
        real = Real(w["dir"])
    except Exception as e:
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
