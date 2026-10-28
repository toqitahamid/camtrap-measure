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
import threading
import time
import zlib
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import distance, lineup, weights

METHODS = {
    "md": {"label": "MegaDetector box (faster)",
           "hint": "Reads the distance at the bottom of the MegaDetector box around each animal. Fine for most photos."},
    "sam3": {"label": "SAM3 outline (more exact)",
             "hint": "SAM3 traces each animal and reads the distance where its feet touch the ground. "
                     "Several times slower. Better when an animal is partly hidden."},
}
# ponytail: which method is the default is decided by the research-repo comparison (an open question:
# bbox-bottom vs mask ground contact on the labeled data); until then the fast one. One-line change.
DEFAULT_METHOD = "md"
SPECIES = ["white-tailed deer", "white-tailed deer", "white-tailed deer", "raccoon", "unsure"]
FAKE_DELAY_S = float(os.environ.get("CAMTRAP_FAKE_DELAY", "0"))  # per photo, to demo the progress display
DETECT_MODELS = ["MegaDetector", "SpeciesNet"]  # stage one, by the names the status bar shows
SAM3_MODEL = "SAM 3"                            # stage two's optional extra: only the precise method loads it
MD_CONF = 0.15  # deliberately low: weak boxes are kept and land in the suspicious gallery, never silently binned
MIN_SPECIES_SCORE = 0.2  # below this SpeciesNet is guessing → "unsure" (research knob, detect/speciesnet_wrap.py)
VRAM_FLOOR_GB = 8  # the design floor (the dept workstation has an 8 GB RTX 2060 SUPER); smaller cards run, with a warning
RUN_VRAM_GB = {distance.RESEARCH: 6.5, distance.FAST: 4.5}  # what one photo needs, weights and working memory
                                                            # together (scripts/profile_run.py, 2026-08-23)


def fidelity() -> str:
    """Which of the two sets of settings a run uses: the published pipeline, or the fast one.

    The published pipeline is the default and stays the default — the app exists to put the paper's
    numbers in front of a technician, and a number that is nearly the paper's is worth less than a slow
    one that is. `fidelity` is an expert escape hatch for a computer too small for the published
    settings: `CAMTRAP_FIDELITY=fast`, or "fidelity": "fast" in config.json. It costs a few centimetres
    (see distance.RESEARCH / FAST), and every measured photo records which one produced it.
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
    match_score: int | None  # homography inliers of the line-up used: the photo's own against the flag photo by day,
                             # the borrowed day photo's at night or by the day rule; < distance.MIN_INLIERS = misfiled
                             # / moved camera
    path: Path | None = None  # which photo this answers; the stages finish photos out of order, so results say so
    alignment: dict | None = None  # how it was lined up (lineup.Line.public); None from backends that do not say


def fake(paths: list[Path], calibration: dict, method: str, *, progress=None) -> Iterator[PhotoResult]:
    """Deterministic per file name, so tests and demos get stable numbers. Made-up numbers with no line-up rules
    behind them; FakeModels below runs the real rules with stand-in models."""
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
        # the range factor k travels with the weights (the range-factor change, ADR 0004): read once here, applied to every read-out in __call__
        self.range_k, self.range_problem = distance.range_factor(self.manifest)
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
            return (f"This graphics card has {gb:.1f} GB of memory, less than the {VRAM_FLOOR_GB} GB the app "
                    "needs. Measuring will be slow.")
        if free_gb < RUN_VRAM_GB[self.fidelity]:
            # The dept machine shares its card with the desktop, Chrome and Teams. Short of memory the
            # run does not usually fail — Windows quietly serves the overflow from system memory over
            # PCIe, and the same photo takes ten times as long (33 s against 3 s, measured 2026-08-23).
            return ("Other programs are using the graphics card, so measuring will be several times slower. "
                    "Close Chrome, Teams or other heavy windows to speed it up.")
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
            self.__dict__.pop("_crops", None)  # the photos _link cropped: an idle app keeps none of them
        gc.collect()
        if self.device == "cuda":
            self.torch.cuda.empty_cache()

    @property
    def loaded(self) -> list[str]:
        """Which models are on the card right now, by the name the status bar shows, so an idle app
        holding nothing is visible there rather than merely claimed.

        Names, not stage labels: the bar already says what the app is doing ("finding animals"), and the
        question this answers is the other one — which models that takes. SAM 3 is listed only once it is
        really loaded, which is on the first photo of a precise run and never in a fast one."""
        return ([] if self._detect is None else list(DETECT_MODELS)) + \
               ([] if self._dist is None else list(distance.MODELS)) + \
               ([] if self.sam3 is None else [SAM3_MODEL])

    def _gpu_name(self) -> str:
        """What the status line shows, so "is it really using the GPU?" has an answer on screen: the card's
        own name, from the driver, or plainly that there is none."""
        if self.device != "cuda":
            return "CPU only, no GPU in use"
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

    # --- the model calls the run makes; FakeModels replaces exactly these ---------------------------------------

    def _find(self, im, p: Path) -> list[dict]:
        """MegaDetector on one photo, at MD_CONF: every class it finds."""
        md, _ = self.detecting()
        with self.torch.no_grad(), self._autocast():
            out = md.generate_detections_one_image(self.np.array(im), image_id=p.name, detection_threshold=MD_CONF)
        return out.get("detections", [])

    def _link(self, target: Path, reference: Path) -> tuple:
        """One seeded RoMa + MAGSAC line-up target -> reference, both banner-cropped. -> (H | None, inliers).
        The reference is the flag photo, or (the Night rule) a day photo of the camera: B -> A for the move check,
        night -> A and night -> B for the vote.
        A photo that will not decode raises here (lineup.UNREADABLE); the planner, the only caller, turns that
        into a failed link, so one broken anchor does not stop the run."""
        crops = self.__dict__.setdefault("_crops", {})
        if len(crops) > 16:  # a run walks back and forth over the same few day photos; keep those, not the season
            crops.clear()
        keys = []
        for q in (target, reference):
            k = (q, q.stat().st_mtime_ns)  # a flag photo downloaded again after a relabel is a new picture
            if k not in crops:
                crops[k] = distance.crop_banner(self._open(q))
            keys.append(k)
        return self.measuring().align(crops[keys[1]], crops[keys[0]])

    def _read(self, dist, im, calibration: dict, Hm, points: list[tuple[float, float]]) -> list[tuple | None]:
        """[q05, q50, q95] at pixel points, read through the line-up Hm into the flag photo of `calibration`. Raw:
        __call__ widens each by the range factor k before it becomes a Detection."""
        return dist.quantiles(dist.predict(im, calibration, Hm), points)

    def link_setting(self) -> str:
        """What a stored link was measured under, beyond its two files: the fidelity, RoMa's refinement resolution
        (fast fidelity picks it by the card) and the weights version. A link kept under another setting is measured
        again, so "Measure again" after a weights update or a fidelity change lines the photos up again."""
        res = distance.upsample_res(self.torch, self.device, self.fidelity)
        return f"{self.fidelity} upsample {res} weights {self.manifest['version']}"

    def __call__(self, paths: list[Path], calibration: dict, method: str, *, progress=None) -> Iterator[PhotoResult]:
        """Every photo through stage one, then only the photos with an animal through stage two.

        Results come back as each photo gets its final answer, which is not the order they were given
        in: an empty frame is finished in stage one and says so at once, while a photo with a deer in it
        is not finished until stage two has aligned it. Each result names its own photo for that reason.

        Each photo with an animal is lined up by the rules in lineup.py (the Night-rule and day-rule changes): directly by day when its
        own line-up is strong, else by the day rule (Copy or Fallback from a clear day photo near it); at night by the
        Night rule, through a day photo of the same camera before or after it (Copy, or Chain when the camera moved),
        never against the flag photo directly. The links a night photo needs are measured when it is measured,
        whatever the order, and kept.

        Photos are decoded twice, once per stage — 47 ms against the seconds a stage costs, and the
        alternative is holding a whole SD card of 6 MB frames in RAM.
        """
        def tick(phase, done, total):
            if progress:
                progress(phase, done, total)

        plan = lineup.Planner(self._link, calibration, self.link_setting())
        self.detecting()
        tick("finding animals", 0, len(paths))
        found = []  # (path, animals, species names) — only the photos worth measuring
        for i, p in enumerate(paths, 1):
            im = self._open(p)
            animals = [d for d in self._find(im, p) if str(d["category"]) == "1"]  # 1 = animal
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
            line = plan.plan(p)
            width, height = im.size
            px = [(u * width, v * height) for u, v in points]
            quantiles = [None] * len(px) if line.H is None else self._read(dist, im, calibration, line.H, px)
            dets = []
            for d, name, q in zip(animals, names, quantiles):
                x, y, w, h = d["bbox"]
                # the one place a range is made: widened by this manifest's range factor k (1.0 = raw) before it is
                # stored, shown, exported or logged (the range-factor change, ADR 0004)
                q05, q50, q95 = distance.widen(*q, self.range_k) if q else (None, None, None)
                dets.append(Detection(x, y, x + w, y + h, name, float(d["conf"]), q50, q05, q95))
            yield PhotoResult(dets, line.score, p, line.public())
            tick("measuring distances", i, len(found))

    def align_score(self, photo: Path, calibration: dict) -> int:
        """How many points of one photo line up with a flag photo: the run's own RoMa alignment, with no
        detector and no distance read. What the Compare dialog asks (the site-folder change)."""
        dist = self.measuring()
        ref_crop, _, _ = dist.reference(calibration)
        return dist.align(ref_crop, distance.crop_banner(self._open(photo)))[1]

    def _sam3(self):
        """SAM3 (transformers port of facebook/sam3), loaded on first use so the fast method never pays its VRAM."""
        if self.sam3 is None:
            # The app downloads no SAM3 (weights.SKIP, 2026-10-12): only a machine that got it before has the folder.
            if "sam3" not in self.manifest or not (self.weights_dir / self.manifest["sam3"]).is_dir():
                raise RuntimeError("SAM3 outline is not on this computer, and the app no longer downloads it. "
                                   "Measure with the MegaDetector box instead.")
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


class FakeModels(Real):
    """`Real`'s own two-stage run with made-up models in place of MegaDetector, SpeciesNet, RoMa and the net, so the
    line-up rules, the staging and the store run end to end without a GPU (tests/test_lineup.py). Only the model
    calls differ (`_find`, `_species`, `_link`, `_read`, loading and releasing); everything between them is Real's.

    Deterministic per file name: `boxes` maps a file name to its detector boxes [(category, x, y, w, h), ...]
    (default one small animal); `links` maps (target name, reference name) to inliers, or (inliers, dx, dy) for a
    homography that shifts by (dx, dy) px (default 8,000 points and a sub-pixel shift). A link decodes both photos
    first, as Real's does, so a broken file fails where it would fail there. The distance read is a plain function
    of where the line-up puts the point, so two line-ups give two numbers. `weights` is the manifest version the
    links are kept under; `range_k`, when given, is the manifest's range factor (the range-factor change, ADR 0004). `calls` records every
    model call, and asking a model that is not loaded fails, as running it off the card would."""

    DEFAULT_BOX = ("1", 0.40, 0.30, 0.10, 0.20)

    def __init__(self, boxes: dict | None = None, links: dict | None = None, fidelity_: str = distance.RESEARCH,
                 weights: str = "test", range_k=None):
        self.np, self.torch, self.fidelity, self.device = np, None, fidelity_, "cpu"  # cpu: link_setting asks no torch
        self.manifest = {"version": weights, **({} if range_k is None else {distance.RANGE_K: range_k})}
        self.range_k, self.range_problem = distance.range_factor(self.manifest)
        self.gpu, self.precision, self.warning, self.batch = "test models", None, None, None
        self._detect = self._dist = self.sam3 = None
        self.box_table, self.link_table = boxes or {}, links or {}
        self.calls: list[tuple] = []

    def detecting(self):
        self._detect = self._detect or ("MegaDetector", "SpeciesNet")
        return self._detect

    def measuring(self):
        self._dist = self._dist or "RoMa + net"
        return self._dist

    def release(self, detect: bool = True, measure: bool = True) -> None:
        self.calls.append(("release", detect, measure))
        if detect:
            self._detect = None
        if measure:
            self._dist = None

    def _find(self, im, p: Path) -> list[dict]:
        assert self._detect is not None, "the detector was asked for while it was not loaded"
        self.calls.append(("detect", p.name))
        return [{"category": c, "conf": 0.9, "bbox": [x, y, w, h]}
                for c, x, y, w, h in self.box_table.get(p.name, [self.DEFAULT_BOX])]

    def _species(self, im, boxes) -> list[str]:
        return ["white-tailed deer"] * len(boxes)

    def _precise(self, im, boxes) -> list[tuple[float, float]]:
        return [(x + w / 2, y + h) for x, y, w, h in boxes]

    def _link(self, target: Path, reference: Path) -> tuple:
        assert self._dist is not None, "RoMa was asked for while it was not loaded"
        for q in (target, reference):
            self._open(q)
        self.calls.append(("link", target.name, reference.name))
        got = self.link_table.get((target.name, reference.name))
        if got is None:
            got = (8000, (zlib.crc32(f"{target.name}>{reference.name}".encode()) % 7) / 10, 0.0)
        inliers, dx, dy = got if isinstance(got, tuple) else (got, 0.0, 0.0)
        return (np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], float) if inliers >= 4 else None), inliers

    def _read(self, dist, im, calibration: dict, Hm, points) -> list[tuple]:
        assert self._dist is not None, "the distance model was asked for while it was not loaded"
        out = []
        for u, v in points:
            q = Hm @ np.array([u, v, 1.0])
            q50 = round(4 + (q[0] / q[2] - u) / 10 + (q[1] / q[2] - v) / 5 + 6 * v / im.height, 4)
            out.append((round(q50 * 0.8, 4), q50, round(q50 * 1.25, 4)))
        return out


# --- choosing a backend at engine start -----------------------------------------------------

backend = fake
# status: loading | ready | error. Starts ready-on-fake so the API works before/without warmup (tests, dev).
state: dict = {"status": "ready", "backend": "fake", "device": None, "gpu": None, "precision": None,
               "fidelity": None, "batch": None, "weights": None, "warning": None, "error": None, "download": None}  # download: {done_gb, total_gb} while weights are fetched


# What weights_version() says when no manifest exists anywhere: no manifest uses it, so no answer the real models
# read is current under it. Every Test mode answer is stamped with it (measure.start_jobs), manifest on disk or not.
NO_WEIGHTS_VERSION = "none (test mode)"


def test_mode() -> bool:
    """Is the backend the fake or a stand-in with no weights manifest of its own (made-up numbers)?"""
    return not (getattr(backend, "manifest", None) or {}).get("version")


def weights_version() -> str:
    """The manifest version of the models in use: what an answer is stamped with and checked against
    (measure.current_answer). While the models load, and on the fake, the weights folder's manifest stands in, so a
    listing at startup does not call every answer "Out of date"; with no manifest there either, NO_WEIGHTS_VERSION."""
    if not test_mode():
        return backend.manifest["version"]
    from . import store

    pinned = os.environ.get("CAMTRAP_WEIGHTS_DIR")
    try:
        return json.loads(((Path(pinned) if pinned else store.DATA_DIR / "weights") / "manifest.json").read_text())["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return NO_WEIGHTS_VERSION


def range_k() -> float:
    """The range factor k the running models widen every 90% range by (distance.widen, the range-factor change, ADR 0004): the loaded
    manifest's `range_k`, or 1.0 (raw) when it has none or an unusable one. 1.0 in Test mode and on the fake, whose
    made-up ranges are never widened. What the researcher log records next to weights_version."""
    return 1.0 if test_mode() else float(getattr(backend, "range_k", 1.0))


def range_problem() -> str | None:
    """Why the loaded manifest's `range_k` was not used (distance.range_factor), or None. For the research log only:
    nothing about k reaches the window or the status payload (decided 2026-10-13: staff never see k)."""
    return None if test_mode() else getattr(backend, "range_problem", None)


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
        state.update(status="ready", warning="FAKE inference: no models installed (uv sync --extra inference). "
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
        state["weights"] = w["version"] + (" (offline — cached copy)" if w["offline"]
                                           else " (installed with the app)" if w.get("bundled") else "")
        if w["problem"]:
            warnings.append(f"Weights could not be checked for updates: {w['problem']}. Using the cached copy.")
        if w.get("notice"):
            warnings.append(w["notice"])
        real = Real(w["dir"])  # constructing it loads nothing: the first run pays for the weights
        if getattr(real, "range_problem", None):  # an unusable range_k: raw ranges. Never in the window (staff never
            # see k, decided 2026-10-13): the launcher log here, and the research log on each measured photo
            from .main import say  # stdlib-only module: no import cycle

            say(f"range factor: {real.range_problem}")
    except Exception as e:
        state["download"] = None
        state.update(status="error", error=str(e) if isinstance(e, weights.WeightsMissing)
                     else f"Models failed to load ({type(e).__name__}: {e}).")
        return
    backend = real
    if real.device != "cuda":
        warnings.append("No graphics card found, so measuring will be many times slower. "
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


_aligning = threading.Lock()  # one alignment at a time: two would load the models twice


def alignment(photo: Path, calibrations: list[dict]) -> list[int]:
    """Points of `photo` that line up with each flag photo (each calibration carries `ref_path`). The real backend
    loads RoMa once for all of them (seconds) and hands the card back after; the test backend makes up a stable
    number per photo and flag photo."""
    with _aligning:
        score = getattr(backend, "align_score", None)
        if score is None:
            if FAKE_DELAY_S:
                time.sleep(FAKE_DELAY_S)
            return [random.Random(f"{photo.name}|{c['site']}|{c['image_name']}").choice([54, 150, 276, 8600, 8900, 9100])
                    for c in calibrations]
        try:
            return [score(photo, c) for c in calibrations]
        finally:
            release()
