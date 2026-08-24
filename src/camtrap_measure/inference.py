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
import gc
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
RUN_VRAM_GB = {distance.RESEARCH: 6.5, distance.FAST: 4.5}  # what one photo needs, weights and working memory
                                                            # together (scripts/profile_run.py, 2026-08-23)


def fidelity() -> str:
    """Which of the two sets of settings a run uses: the published pipeline, or the fast one.

    The published pipeline is the default and stays the default — the app exists to put the paper's
    numbers in front of a technician, and a number that is nearly the paper's is worth less than a slow
    one that is. `fidelity` is an expert escape hatch for a computer too small for the published
    settings: `CAMTRAP_FIDELITY=fast`, or "fidelity": "fast" in config.json. What it costs is in
    CONTEXT.md, and every measured photo records which one produced it.
    """
    from . import store

    want = os.environ.get("CAMTRAP_FIDELITY") or store.config().get("fidelity") or distance.RESEARCH
    return want if want in distance.FIDELITIES else distance.RESEARCH
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
    path: Path | None = None  # which photo this answers; the stages finish photos out of order, so results say so


def fake(paths: list[Path], calibration: dict, method: str, *, progress=None) -> Iterator[PhotoResult]:
    """Deterministic per file name, so tests and demos get stable numbers."""
    if progress:
        progress("finding animals", 0, len(paths))
    for i, p in enumerate(paths, 1):
        rng = random.Random(p.name)
        dets = []
        for _ in range(rng.choice([0, 1, 1, 2])):
            d = rng.uniform(3, 25)
            x, y, w = rng.uniform(0, 0.7), rng.uniform(0.3, 0.7), rng.uniform(0.1, 0.3)
            dets.append(Detection(x, y, x + w, min(1, y + w * 0.8), rng.choice(SPECIES), rng.uniform(0.4, 0.99),
                                  round(d, 2), round(d * 0.85, 2), round(d * 1.2, 2)))
        if FAKE_DELAY_S:
            time.sleep(FAKE_DELAY_S)
        yield PhotoResult(dets, rng.choice([9, 60, 180, 320]) if dets else None, p)  # 9 < MIN_INLIERS: some look misfiled
        if progress:
            progress("measuring distances", i, len(paths))


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


def is_oom(e: Exception) -> bool:
    """True for the several ways CUDA says it is out of memory; `measure` turns this into plain words."""
    return any(s in str(e) for s in ("out of memory", "CUBLAS_STATUS_ALLOC_FAILED", "CUDNN_STATUS_NOT_INITIALIZED"))


class Real:
    """MegaDetector animal boxes, SpeciesNet species per box, RoMa-aligned unified-net distance at each
    box's ground contact.

    The models load in two stages and are dropped again, because they never have to be resident at the
    same moment, and on an 8 GB card shared with the desktop that is the difference between fitting and
    spilling into system memory. Stage one — MegaDetector and SpeciesNet — answers *which photos hold an
    animal, and what it is*. Stage two — RoMa and the unified net — answers *how far away*, and only for
    the photos stage one found something in. A folder of empty frames never loads stage two at all, and
    when a run ends both stages go and the card goes back to whatever else the technician is running.

    Constructing this loads nothing: the window opens without waiting for 6 GB of weights, and an idle
    app holds no VRAM. The first run pays the loading, and the run's own status says so while it happens.
    """

    def __init__(self, weights_dir: Path, fidelity_: str | None = None):
        import numpy as np
        import torch
        from speciesnet.utils import BBox

        self.np, self.torch, self.BBox = np, torch, BBox
        self.fidelity = fidelity_ or fidelity()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.gpu = self._gpu_name()
        self.weights_dir = weights_dir
        self.manifest = json.loads((weights_dir / "manifest.json").read_text())
        self.precision = str(distance.autocast_dtype(torch, self.device, self.fidelity)).replace("torch.", "")
        self.warning = self._card_warning()
        self.batch = None if self.device == "cuda" else 4  # probed when SpeciesNet arrives, not before
        self._detect = None  # (MegaDetector, SpeciesNet) while stage one is loaded
        self._dist = None    # distance.Distance while stage two is loaded
        self.sam3 = None     # (model, processor) once the precise method has been asked for

    def _card_warning(self) -> str | None:
        """Whether this card can hold a run — asked of the driver alone, with no model loaded yet."""
        if self.device != "cuda":
            return None
        free, total = self.torch.cuda.mem_get_info()
        gb, free_gb = total / 2**30, free / 2**30
        if round(gb) < VRAM_FLOOR_GB:  # an "8 GB" card reports ~7.99 GiB usable (seen on the dept RTX 2060 SUPER)
            return (f"This GPU has {gb:.1f} GB of memory, below the {VRAM_FLOOR_GB} GB the app is designed for "
                    "— runs will be slow.")
        if free_gb < RUN_VRAM_GB[self.fidelity]:
            # The dept machine shares its card with the desktop, Chrome and Teams. Short of memory the
            # run does not usually fail — Windows quietly serves the overflow from system memory over
            # PCIe, and the same photo takes ten times as long (33 s against 3 s, measured 2026-08-23).
            return (f"Only {free_gb:.1f} GB of the GPU's {gb:.1f} GB is free, and a run needs about "
                    f"{RUN_VRAM_GB[self.fidelity]:.1f} GB — other programs are using the card. Measuring "
                    "will be several times slower until Chrome, Teams or other heavy windows are closed.")
        return None

    def detecting(self) -> tuple:
        """Stage one, loaded on first use: MegaDetector and SpeciesNet."""
        if self._detect is None:
            from megadetector.detection.run_detector import load_detector
            from speciesnet.classifier import SpeciesNetClassifier

            md = load_detector(str(self.weights_dir / self.manifest["megadetector"]), force_cpu=self.device == "cpu")
            sn = SpeciesNetClassifier(str(self.weights_dir / self.manifest["speciesnet"]), device=self.device)
            self._detect = (md, sn)
            if self.device == "cuda":
                self.batch = self._probe_batch(sn)
                # The probe's largest successful trial stays in the allocator's cache — 2.9 GB of this
                # card, held but unused (measured 2026-08-23). Nothing else can have it, and on a card
                # this size the run then overflows into system memory.
                self.torch.cuda.empty_cache()
        return self._detect

    def measuring(self):
        """Stage two, loaded on first use: RoMa, DINOv2 and the unified distance net."""
        if self._dist is None:
            self._dist = distance.Distance(self.weights_dir, self.device, self.fidelity)
        return self._dist

    def release(self, detect: bool = True, measure: bool = True) -> None:
        """Drop what is loaded and hand the memory back.

        Dropping the reference is not enough by itself: Python may still hold the graph in a reference
        cycle, and torch keeps freed blocks in a cache of its own where no other program can reach them.
        Both are asked explicitly. Called between the stages of a run, and again when the run ends."""
        if detect:
            self._detect = None
        if measure:
            self._dist, self.sam3 = None, None
        gc.collect()
        if self.device == "cuda":
            self.torch.cuda.empty_cache()

    @property
    def loaded(self) -> list[str]:
        """Which stages are on the card right now, so an idle app holding nothing is visible on the
        status line rather than merely claimed."""
        return ([] if self._detect is None else ["finding animals"]) + \
               ([] if self._dist is None else ["measuring distances"])

    def _gpu_name(self) -> str:
        """What the status line shows, so "is it really using the GPU?" has an answer on screen: the card's
        own name, from the driver, or plainly that there is none."""
        if self.device != "cuda":
            return "CPU only — no GPU in use"
        p = self.torch.cuda.get_device_properties(0)
        return f"{p.name} ({p.total_memory / 2**30:.1f} GB)"

    def _autocast(self, dtype=None):
        """Mixed precision on CUDA (fp16 unless told otherwise), nothing on the CPU."""
        return self.torch.autocast("cuda", dtype=dtype or self.torch.float16) if self.device == "cuda" else nullcontext()

    def _probe_batch(self, sn) -> int:
        """Half the largest SpeciesNet batch (≤64) whose forward pass fits right now — the other half
        is headroom for MegaDetector's activations, which are not allocated yet when this runs."""
        size = sn.IMG_SIZE
        for b in (64, 32, 16, 8, 4, 2, 1):
            try:
                with self.torch.no_grad(), self._autocast():
                    sn.model(self.torch.zeros(b, size, size, 3, device=self.device))
                return max(1, b // 2)
            except (self.torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if not is_oom(e):
                    raise
                self.torch.cuda.empty_cache()
        return 1

    @staticmethod
    def _open(p: Path):
        from PIL import Image

        with Image.open(p) as im:
            return im.convert("RGB")

    def __call__(self, paths: list[Path], calibration: dict, method: str, *, progress=None) -> Iterator[PhotoResult]:
        """Every photo through stage one, then only the photos with an animal through stage two.

        Results come back as each photo gets its final answer, which is not the order they were given
        in: an empty frame is finished in stage one and says so at once, while a photo with a deer in it
        is not finished until stage two has aligned it. Each result names its own photo for that reason.

        Photos are decoded twice, once per stage — 47 ms against the seconds a stage costs, and the
        alternative is holding a whole SD card of 6 MB frames in RAM.
        """
        def tick(phase, done, total):
            if progress:
                progress(phase, done, total)

        md, _ = self.detecting()
        tick("finding animals", 0, len(paths))
        found = []  # (path, animals, species names) — only the photos worth measuring
        for i, p in enumerate(paths, 1):
            im = self._open(p)
            with self.torch.no_grad(), self._autocast():
                out = md.generate_detections_one_image(self.np.array(im), image_id=p.name, detection_threshold=MD_CONF)
            animals = [d for d in out.get("detections", []) if str(d["category"]) == "1"]  # 1 = animal
            if not animals:
                # An empty frame is done here: no species to name, nothing to align, and its answer is
                # written now rather than held until the end of the run. Most of a season is this photo.
                # ponytail: they are never aligned, so a camera that moved is only noticed once something
                # walks past it. Align a sample of empty frames if the alarm should fire sooner.
                yield PhotoResult([], None, p)
            else:
                found.append((p, animals, self._species(im, [d["bbox"] for d in animals])))
            tick("finding animals", i, len(paths))

        # MegaDetector and SpeciesNet leave the card before RoMa arrives; they are not needed again.
        self.release(detect=True, measure=False)
        if not found:
            return  # a folder with nothing in it never loads the measuring models at all

        dist = self.measuring()
        tick("measuring distances", 0, len(found))
        for i, (p, animals, names) in enumerate(found, 1):
            im = self._open(p)
            boxes = [d["bbox"] for d in animals]
            points = self._precise(im, boxes) if method == "sam3" else [(x + w / 2, y + h) for x, y, w, h in boxes]
            quantiles, inliers = dist.read(im, calibration, points)
            dets = []
            for d, name, q in zip(animals, names, quantiles):
                x, y, w, h = d["bbox"]
                q05, q50, q95 = q if q else (None, None, None)
                dets.append(Detection(x, y, x + w, y + h, name, float(d["conf"]), q50, q05, q95))
            yield PhotoResult(dets, inliers, p)
            tick("measuring distances", i, len(found))

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
        ctx = self._autocast(torch.bfloat16) if self.measuring().dtype == torch.bfloat16 else nullcontext()
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
        _, sn = self.detecting()
        crops = [sn.preprocess(im, bboxes=[self.BBox(*b)]) for b in boxes]
        names: list[str] = []
        while len(names) < len(crops):
            chunk = crops[len(names):len(names) + self.batch]
            try:
                with self.torch.no_grad(), self._autocast():
                    preds = sn.batch_predict([str(j) for j in range(len(chunk))], chunk)
            except (self.torch.cuda.OutOfMemoryError, RuntimeError) as e:
                if not is_oom(e) or self.batch == 1:
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
state: dict = {"status": "ready", "backend": "fake", "device": None, "gpu": None, "precision": None,
               "fidelity": None, "batch": None, "weights": None, "warning": None, "error": None, "download": None}  # download: {done_gb, total_gb} while weights are fetched


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
        state["weights"] = w["version"] + (" (installed with the app)" if w.get("bundled")
                                           else " (offline — cached copy)" if w["offline"] else "")
        if w["problem"]:
            warnings.append(f"Weights could not be checked for updates: {w['problem']}. Using the cached copy.")
        real = Real(w["dir"])  # constructing it loads nothing: the first run pays for the weights
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
    state.update(status="ready", backend="real", device=real.device, gpu=real.gpu, batch=real.batch,
                 precision=real.precision, fidelity=real.fidelity,
                 warning=" · ".join(warnings) or None)


def live() -> dict:
    """What is true now rather than at warmup: which stages are holding VRAM, and the SpeciesNet batch
    size, which is not known until SpeciesNet has been loaded and probed for the first time."""
    b = backend
    # asked of the object, not of its class: the fake is a plain function and tests put their own
    # stand-ins here, and neither is a Real
    return {"loaded": list(getattr(b, "loaded", [])), "batch": getattr(b, "batch", None)}


def release() -> None:
    """Hand the card back. Called when a run ends: an app sitting idle should hold no VRAM."""
    free = getattr(backend, "release", None)
    if free:
        free()
