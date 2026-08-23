"""Where a measurement run spends its time, stage by stage, on this computer's GPU.

Optimising inference without a profile is guessing: the run is five different models and a JPEG
decode, and which one dominates is a fact about the card, not about the code. This script loads the
real backend exactly as the engine does, measures one folder of photos, and prints per-stage
milliseconds plus what the GPU was actually doing while it ran.

It touches nothing in the app: the stages are timed by wrapping the calls in place, and the results
are thrown away rather than written to the store.

    uv run python scripts/profile_run.py <folder> --site MAS_CAM01 --flag IMG_0004.JPG
    uv run python scripts/profile_run.py <folder> --site <camera> --flag <photo> --method sam3

Close the app window first: models loaded twice will not fit in 8 GB.
"""

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camtrap_measure import inference, measure, store  # noqa: E402

TIMES: dict[str, list[float]] = defaultdict(list)
PEAKS: dict[str, list[float]] = defaultdict(list)  # GB this stage added on top of what was already held


def timed(name, fn, torch):
    """Wall time of one call with the GPU drained on both sides — CUDA is asynchronous, so an
    unsynchronised timer bills the next stage for this one's work."""
    def wrapper(*a, **kw):
        cuda = torch.cuda.is_available()
        if cuda:
            torch.cuda.synchronize()
            before = torch.cuda.memory_allocated()
            torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        finally:
            if cuda:
                torch.cuda.synchronize()
                PEAKS[name].append((torch.cuda.max_memory_allocated() - before) / 2**30)
            TIMES[name].append((time.perf_counter() - t0) * 1000)
    return wrapper


class GpuWatch:
    """utilization.gpu and memory.used sampled while the run happens: the honest answer to
    'is it really using the GPU', because it is the driver talking, not the app."""

    def __init__(self, every_ms=200):
        self.every_ms, self.samples, self.stop = every_ms, [], threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self.stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
                util, mem = (int(x) for x in out.stdout.strip().splitlines()[0].split(","))
                self.samples.append((util, mem))
            except Exception:
                pass
            self.stop.wait(self.every_ms / 1000)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *e):
        self.stop.set()
        self.thread.join(timeout=2)


def vram(torch) -> str:
    """What the card and what this process think, side by side: `reserved` is memory torch holds in its
    own cache and will not hand back to another program until empty_cache()."""
    if not torch.cuda.is_available():
        return "no cuda"
    free, total = torch.cuda.mem_get_info()
    return (f"free {free / 2**30:.2f} / {total / 2**30:.2f} GB - torch allocated "
            f"{torch.cuda.memory_allocated() / 2**30:.2f} GB, reserved {torch.cuda.memory_reserved() / 2**30:.2f} GB")


def instrument(real, torch):
    """Wrap every stage of one photo's journey. What is left over after these is decode and numpy."""
    real.md.generate_detections_one_image = timed("megadetector", real.md.generate_detections_one_image, torch)
    real._species = timed("speciesnet", real._species, torch)
    real._precise = timed("sam3", real._precise, torch)
    real.dist.align = timed("roma align", real.dist.align, torch)
    real.dist.read = timed("distance total", real.dist.read, torch)
    real.dist.net = timed("unified net", real.dist.net, torch)


def table(rows, headers):
    w = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = "  ".join(h.ljust(w[i]) for i, h in enumerate(headers))
    print(line)
    print("  ".join("-" * x for x in w))
    for r in rows:
        print("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--site", required=True)
    ap.add_argument("--flag", required=True)
    ap.add_argument("--method", default=inference.DEFAULT_METHOD, choices=list(inference.METHODS))
    ap.add_argument("--limit", type=int, default=0, help="measure only the first N photos")
    ap.add_argument("--batch", type=int, default=0, help="override the probed SpeciesNet batch size")
    ap.add_argument("--empty-cache", action="store_true", help="release the allocator's cache after warmup")
    args = ap.parse_args()

    import torch

    print(f"torch {torch.__version__} · cuda available: {torch.cuda.is_available()} · "
          f"built for cuda {torch.version.cuda}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"device 0: {p.name} · {p.total_memory / 2**30:.1f} GB · compute {p.major}.{p.minor} · "
              f"bf16 {torch.cuda.is_bf16_supported()}")

    cal = next((r for r in store.calibrations() if r["site"] == args.site and r["image_name"] == args.flag), None)
    if cal is None:
        print(f"no calibration for {args.site}/{args.flag} — run Sync in the app first")
        return 1
    photos = measure.jpegs(Path(args.folder))[: args.limit or None]
    print(f"{len(photos)} photos · method {args.method}\n")

    t0 = time.perf_counter()
    inference.warmup()
    load_s = time.perf_counter() - t0
    if inference.state["backend"] != "real":
        print(f"backend is {inference.state['backend']} — {inference.state['warning'] or inference.state['error']}")
        return 1
    real = inference.backend
    if args.batch:
        real.batch = args.batch
    if args.empty_cache:
        torch.cuda.empty_cache()
    print(f"models loaded in {load_s:.1f}s · device {real.device} · speciesnet batch {real.batch}")
    if real.warning:
        print(f"warning: {real.warning}")
    print(f"VRAM after load: {vram(torch)}")
    instrument(real, torch)

    ref = {**cal, "ref_path": str(store.ref_path(args.site, args.flag))}
    per_photo = []
    with GpuWatch() as watch:
        run0 = time.perf_counter()
        for i, res in enumerate(real([p for p in photos], ref, args.method)):
            per_photo.append(time.perf_counter() - run0 - sum(per_photo))
            print(f"  {photos[i].name}: {len(res.detections)} animals, "
                  f"match {res.match_score}, {per_photo[-1] * 1000:.0f} ms")
        total_s = time.perf_counter() - run0
    print(f"VRAM after run:  {vram(torch)}")
    if torch.cuda.is_available():
        print(f"peak this process: {torch.cuda.max_memory_allocated() / 2**30:.2f} GB allocated, "
              f"{torch.cuda.max_memory_reserved() / 2**30:.2f} GB reserved")

    print()
    rows = []
    for name, xs in TIMES.items():
        peak = f"{max(PEAKS[name]):.2f}" if PEAKS.get(name) else ""
        rows.append([name, len(xs), f"{statistics.mean(xs):.0f}", f"{statistics.median(xs):.0f}",
                     f"{min(xs):.0f}", f"{max(xs):.0f}", f"{sum(xs) / 1000:.1f}",
                     f"{100 * sum(xs) / 1000 / total_s:.0f}%", peak])
    accounted = sum(sum(TIMES[k]) for k in TIMES if k not in ("unified net", "roma align"))  # nested inside "distance total"
    rows.append(["decode + numpy + rest", len(photos), "", "", "", "",
                 f"{total_s - accounted / 1000:.1f}", f"{100 * (total_s - accounted / 1000) / total_s:.0f}%", ""])
    table(rows, ["stage", "calls", "mean ms", "median", "min", "max", "total s", "share", "peak GB"])

    print(f"\nrun: {total_s:.1f}s for {len(photos)} photos = {total_s / len(photos):.2f} s/photo "
          f"= {60 * len(photos) / total_s:.0f} photos/min = {3600 * len(photos) / total_s:.0f} photos/hour")
    if watch.samples:
        utils = [u for u, _ in watch.samples]
        mems = [m for _, m in watch.samples]
        print(f"GPU while measuring: utilisation mean {statistics.mean(utils):.0f}% max {max(utils)}% "
              f"(idle samples {sum(1 for u in utils if u < 5)}/{len(utils)}) · "
              f"memory {min(mems)}-{max(mems)} MiB")
    print(json.dumps({k: round(statistics.mean(v), 1) for k, v in TIMES.items()}, indent=None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
