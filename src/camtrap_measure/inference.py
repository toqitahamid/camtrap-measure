"""The inference boundary: photos in, detections out. Everything GPU/torch lives behind `backend`.

`backend(paths, calibration, method)` takes the photos of one calibration window (so a real
implementation can batch them), the window's fitted calibration (`ModelB.to_dict()`), and the
method name; it yields one `list[Detection]` per path, in order. `fake` ships with the app so
the whole thing runs and demos without a GPU; ticket 06 swaps in the real one.
"""

import os
import random
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

METHODS = {"md": "MegaDetector (fast)", "sam3": "MegaDetector + SAM3 (precise, slower)"}
SPECIES = ["white-tailed deer", "white-tailed deer", "white-tailed deer", "raccoon", "unsure"]
FAKE_DELAY_S = float(os.environ.get("CAMTRAP_FAKE_DELAY", "0"))  # per photo, to demo the progress display


@dataclass
class Detection:
    x1: float  # box, fractions of image width/height
    y1: float
    x2: float
    y2: float
    species: str
    confidence: float
    distance_m: float
    q05_m: float
    q95_m: float
    match_score: float  # RoMa alignment to the flag reference; low = misfiled / moved camera


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


backend = fake
