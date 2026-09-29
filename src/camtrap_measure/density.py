"""Deer density from the measured distances: camera-trap distance sampling (CTDS; Howe et al. 2017, Methods Ecol
Evol 8:1558), the in-app estimate and the flat file R's `Distance` package reads.

Each camera is a point transect watched in snapshot moments: a camera active T_k seconds with a snapshot interval
t has T_k / t moments, and it sees θ_k / 2π of the circle around it. A detection function g(r) is fitted to the
deer distances r ≤ w (half-normal and hazard-rate, chosen by AIC); P = 2 ∫0^w r g(r) dr / w² is the chance a deer
inside the circle of radius w is seen, and

    D = n / (π w² P Σ_k (T_k / t)(θ_k / 2π))      deer per m²

Every photo is a snapshot moment and every deer box one animal; availability is taken as 1 (a deer in view at a
moment is a deer the camera could see). The 90% interval bootstraps cameras (deer, with fewer than three
cameras), redraws each deer's distance inside its own 90% band, and refits — so it carries the distance
measurement error as well as the sampling error. Seeded: the same inputs give the same interval.

Everything below the settings helpers is pure: rows and photos in, numbers out, testable without the store.
"""

import csv
import io
import math
from datetime import date, datetime
from ntpath import basename  # splits on / and \ alike, as in report.py

import numpy as np
from scipy.optimize import minimize, minimize_scalar

from . import report, store

SPECIES = "white-tailed deer"
DEFAULT_INTERVAL_S = 2.0
DEFAULT_FOV_DEG = 42.0  # the Distance package's duiker example uses 42°; a common trail-camera lens
MIN_DEER = 20  # below this the screen still shows the numbers but says they are too few (60 to 80 is the usual minimum)
BOOTSTRAPS = 1000
SEED = 2017  # Howe et al. 2017; any fixed number would do, it only has to stay the same
BAND_SD = 3.29  # q95 - q05 of a normal is 2 × 1.645 sd
NODES = 96  # Gauss-Legendre nodes for ∫0^w r g(r) dr; the hazard-rate has no closed form

# Field of view by EXIF (make, model), only where the maker's own spec gives it for exactly that model string.
# ponytail: empty on purpose. The dept's cameras report ("BROWNING", "BTC-7E"), and Browning ships several cameras
# under that prefix with different lenses: the Recon Force Elite HP5 (BTC-7E-HP5) manual says 41°, retailers list
# the Recon Force Edge (BTC-7E) at 38.1°, and the EXIF string does not say which one took the photo. A guessed
# lens would move every density by up to 8% without anyone seeing it, so those cameras get 42° marked "check".
FOV_BY_MODEL: dict[tuple[str, str], float] = {}


# --- settings (config.json, "density" key) -------------------------------------------------------------------

def settings() -> dict:
    """{interval_s, truncation_m, cameras: {site: {active_days, fov_deg}}}; None means "use the default"."""
    saved = store.config().get("density") or {}
    return {"interval_s": saved.get("interval_s"), "truncation_m": saved.get("truncation_m"),
            "cameras": saved.get("cameras") or {}}


def save_settings(change: dict) -> dict:
    """Merge a change into the saved settings. A None value puts that setting back to its default.
    Raises ValueError with a plain message for a number that cannot be right."""
    cur = settings()
    for key in ("interval_s", "truncation_m"):
        if key in change:
            v = change[key]
            if v is not None and not (isinstance(v, (int, float)) and 0 < v < 10_000):
                raise ValueError(f"{key} must be a positive number, got {v!r}")
            cur[key] = v
    for site, cam in (change.get("cameras") or {}).items():
        mine = dict(cur["cameras"].get(site) or {})
        if "active_days" in cam:
            v = cam["active_days"]
            if v is not None and not (isinstance(v, (int, float)) and 0 < v <= 36_600):
                raise ValueError(f"Active days for {site} must be a positive number, got {v!r}")
            mine["active_days"] = v
        if "fov_deg" in cam:
            v = cam["fov_deg"]
            if v is not None and not (isinstance(v, (int, float)) and 0 < v <= 360):
                raise ValueError(f"Field of view for {site} must be between 0 and 360 degrees, got {v!r}")
            mine["fov_deg"] = v
        cur["cameras"][site] = {k: v for k, v in mine.items() if v is not None}
    cur["cameras"] = {s: c for s, c in cur["cameras"].items() if c}
    cfg = store.config()  # the same file holds the installer's settings: read it whole, change one key
    cfg["density"] = cur
    store.save_config(cfg)
    return cur


# --- what goes in ---------------------------------------------------------------------------------------------

def deer_rows(rows: list[dict], photos: list[dict]) -> tuple[list[dict], dict]:
    """The deer rows a density may use, and the counts the screen explains them with.
    A photo measured with both methods has rows under each; only the method it was last measured with counts,
    or every deer in it would count twice. Of the deer-like rows (white-tailed deer and unsure), the suspicious
    ones never enter — that includes every row without a distance, and every unsure animal."""
    current = {p["path"]: p["method"] for p in photos}
    mine = [r for r in rows if r["method"] == current.get(r["path"], r["method"])]
    deer = [r for r in mine if r["species"] in report.DEER]
    clean = [r for r in deer if not report.reasons(r) and r["species"] == SPECIES and r["distance_m"] is not None]
    return clean, {"deer": len(deer), "suspicious": len(deer) - len(clean)}


def _day(captured_at: str) -> date:
    return datetime.fromisoformat(captured_at).date()


def default_days(photos: list[dict]) -> dict[str, int | None]:
    """Active days per camera: first to last photo, whole calendar days counted inclusively. None for a camera
    with no dated photo — there is nothing to count from, and the screen asks for the number."""
    spans: dict[str, list[date]] = {}
    for p in photos:
        spans.setdefault(p["site"], [])
        if p["captured_at"]:
            spans[p["site"]].append(_day(p["captured_at"]))
    return {s: ((max(d) - min(d)).days + 1 if d else None) for s, d in spans.items()}


def camera_setup(photos: list[dict], saved: dict) -> list[dict]:
    """One line per camera in scope: its active days and field of view, saved value over default."""
    days = default_days(photos)
    models = {}
    for p in photos:
        models.setdefault(p["site"], (p.get("make") or "", p.get("model") or ""))
    out = []
    for site in sorted(days):
        own = saved.get(site) or {}
        known = FOV_BY_MODEL.get(models[site])
        fov = own.get("fov_deg") or known or DEFAULT_FOV_DEG
        out.append({"site": site, "model": " ".join(m for m in models[site] if m) or None,
                    "active_days": own.get("active_days") or days[site], "active_days_default": days[site],
                    "fov_deg": fov, "fov_default": known or DEFAULT_FOV_DEG,
                    "fov_checked": bool(own.get("fov_deg")) or known is not None})
    return out


def default_truncation(distances: list[float]) -> float | None:
    """The 95th percentile of the distances, rounded up to the metre (at least 1 m)."""
    if not distances:
        return None
    return float(max(1, math.ceil(np.percentile(distances, 95))))


def effort(cams: list[dict], interval_s: float) -> dict[str, float]:
    """Per camera: snapshot moments (active seconds / interval) × the fraction of the circle it sees."""
    return {c["site"]: c["active_days"] * 86_400 / interval_s * c["fov_deg"] / 360 for c in cams if c["active_days"]}


# --- detection function ---------------------------------------------------------------------------------------

_X, _WT = np.polynomial.legendre.leggauss(NODES)


def _g(model: str, r: np.ndarray, sigma: float, b: float | None) -> np.ndarray:
    if model == "half-normal":
        return np.exp(-r * r / (2 * sigma * sigma))
    with np.errstate(divide="ignore", over="ignore"):
        return -np.expm1(-np.power(np.maximum(r, 1e-12) / sigma, -b))


def _mu(model: str, w: float, sigma: float, b: float | None) -> float:
    """∫0^w r g(r) dr."""
    if model == "half-normal":
        return sigma * sigma * -math.expm1(-w * w / (2 * sigma * sigma))
    r = (_X + 1) * w / 2
    return float(np.sum(_WT * r * _g(model, r, sigma, b)) * w / 2)


def _nll(model: str, r: np.ndarray, w: float, sigma: float, b: float | None = None) -> float:
    """−log L of f(r) = r g(r) / ∫0^w r g(r) dr, the pdf of the distances a point transect observes."""
    mu = _mu(model, w, sigma, b)
    g = _g(model, r, sigma, b)
    if not mu > 0 or np.any(g <= 0):
        return math.inf
    return float(-np.sum(np.log(r) + np.log(g)) + len(r) * math.log(mu))


def fit_half_normal(r: np.ndarray, w: float) -> dict:
    lo, hi = math.log(w) - 7, math.log(w) + 5  # σ from w/1000 to 150 w: flat enough to be the uniform at the top
    res = minimize_scalar(lambda s: _nll("half-normal", r, w, math.exp(s)), bounds=(lo, hi), method="bounded")
    nll = float(res.fun)
    return {"model": "half-normal", "sigma": math.exp(res.x), "b": None, "nll": nll, "aic": 2 * nll + 2}


def fit_hazard_rate(r: np.ndarray, w: float, start: dict | None = None) -> dict | None:
    """Hazard-rate g = 1 − exp(−(r/σ)^−b), shape b held in [1, 20] (b < 1 is not a shoulder).
    Started from a few shapes because its likelihood has flat ridges; None if no start converges. The bootstrap
    passes the point estimate's fit as the one start: three starts a replicate took 19 s for 1000 replicates."""
    starts = ([(math.log(start["sigma"]), start["b"])] if start else
              [(math.log(float(np.median(r))), b0) for b0 in (1.5, 3.0, 6.0)])
    best = None
    for x0 in starts:
        # Nelder-Mead, not a gradient method: scipy's numeric gradient asks the array-API layer whether its input
        # is a torch tensor, and while the model warmup is still importing torch that raises (seen on the first
        # live run, 2026-09-28). Nelder-Mead never asks.
        res = minimize(lambda p: _nll("hazard-rate", r, w, math.exp(p[0]), p[1]), x0=list(x0), method="Nelder-Mead",
                       bounds=[(math.log(w) - 7, math.log(w) + 5), (1.0, 20.0)], options={"xatol": 1e-3, "fatol": 1e-4})
        if np.isfinite(res.fun) and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        return None
    nll = float(best.fun)
    return {"model": "hazard-rate", "sigma": math.exp(best.x[0]), "b": float(best.x[1]), "nll": nll,
            "aic": 2 * nll + 4}


def fit(r: np.ndarray, w: float, like: dict | None = None) -> tuple[dict, dict | None]:
    """(chosen fit, the other fit). Given `like`, a fit already chosen, only that model is refitted, starting from
    it: what the bootstrap does, so the interval is the chosen model's. Hazard-rate needs a few distances to have
    a shape; below 3 it is not tried."""
    if like and like["model"] == "half-normal":
        return fit_half_normal(r, w), None
    if like:
        return fit_hazard_rate(r, w, like) or fit_half_normal(r, w), None
    hn = fit_half_normal(r, w)
    hr = fit_hazard_rate(r, w) if len(r) >= 3 else None
    if hr is not None and hr["aic"] < hn["aic"]:
        return hr, hn
    return hn, hr


def detection_p(f: dict, w: float) -> float:
    """P = 2 ∫0^w r g(r) dr / w²: the chance a deer somewhere in the circle of radius w is seen."""
    return 2 * _mu(f["model"], w, f["sigma"], f["b"]) / (w * w)


def pdf(f: dict, w: float, r: np.ndarray) -> np.ndarray:
    return r * _g(f["model"], r, f["sigma"], f["b"]) / _mu(f["model"], w, f["sigma"], f["b"])


def density(n: int, p: float, w: float, total_effort: float) -> float:
    """Deer per m²."""
    return n / (math.pi * w * w * p * total_effort)


# --- the interval ---------------------------------------------------------------------------------------------

def bootstrap(deer: list[dict], efforts: dict[str, float], w: float, chosen: dict, reps: int = BOOTSTRAPS,
              seed: int = SEED) -> tuple[float, float]:
    """90% percentile interval of D (per m²). Resamples cameras with replacement — a camera brings its deer and
    its effort, so cameras with no deer count too — or, with fewer than three cameras, the deer themselves.
    Every deer's distance is redrawn from Normal(distance, (q95 − q05) / 3.29) and the deer counts only if the
    redraw lands inside w, so a deer near w can move in or out as its own band allows."""
    rng = np.random.default_rng(seed)
    sites = sorted(efforts)
    by_site = {s: [d for d in deer if d["site"] == s] for s in sites}
    total = sum(efforts.values())
    out = []
    for _ in range(reps):
        if len(sites) >= 3:
            pick = rng.integers(0, len(sites), len(sites))
            rows = [d for i in pick for d in by_site[sites[i]]]
            eff = sum(efforts[sites[i]] for i in pick)
        else:
            rows = [deer[i] for i in rng.integers(0, len(deer), len(deer))] if deer else []
            eff = total
        if not rows:
            out.append(0.0)
            continue
        mid = np.array([d["distance_m"] for d in rows])
        sd = np.array([(d["q95_m"] - d["q05_m"]) / BAND_SD if d["q05_m"] is not None and d["q95_m"] is not None
                       else 0.0 for d in rows])
        r = np.abs(rng.normal(mid, sd))  # reflected at the camera: a distance cannot be negative
        r = r[(r <= w) & (r > 0)]
        if len(r) == 0:
            out.append(0.0)
            continue
        f, _ = fit(r, w, chosen)
        out.append(density(len(r), detection_p(f, w), w, eff))
    lo, hi = np.percentile(out, [5, 95])
    return float(lo), float(hi)


# --- the screen and the file ----------------------------------------------------------------------------------

def _bins(r: np.ndarray, w: float) -> tuple[list[dict], float]:
    k = int(min(12, max(5, round(math.sqrt(len(r))))))
    width = w / k
    counts = np.histogram(r, bins=k, range=(0, w))[0]
    return [{"lo": round(i * width, 2), "hi": round((i + 1) * width, 2), "n": int(c)} for i, c in enumerate(counts)], width


def estimate(rows: list[dict], photos: list[dict], saved: dict, reps: int | None = None) -> dict:
    """Everything the DENSITY screen draws, from the rows and photos in its filters and the saved settings."""
    deer, counts = deer_rows(rows, photos)
    cams = camera_setup(photos, saved["cameras"])
    interval_s = saved["interval_s"] or DEFAULT_INTERVAL_S
    efforts = effort(cams, interval_s)
    dated = [d for d in deer if d["site"] in efforts]  # a camera with no active days is out, with its deer
    auto_w = default_truncation([d["distance_m"] for d in dated])
    w = saved["truncation_m"] or auto_w
    inside = [d for d in dated if w and d["distance_m"] <= w]
    beyond = [d for d in dated if not (w and d["distance_m"] <= w)]
    # used + beyond + suspicious + no_days_deer = deer, so the line on screen adds up
    out = {"species": SPECIES, "deer": counts["deer"], "suspicious": counts["suspicious"], "beyond": len(beyond),
           "no_days": sum(1 for c in cams if not c["active_days"]), "no_days_deer": len(deer) - len(dated),
           "used": len(inside), "interval_s": interval_s, "interval_default_s": DEFAULT_INTERVAL_S,
           "truncation_m": w, "truncation_default_m": auto_w, "cameras": cams,
           "effort": round(sum(efforts.values()), 2), "min_deer": MIN_DEER, "too_few": len(inside) < MIN_DEER,
           "fit": None, "bins": [], "curve": [], "density": None}
    if not inside:
        return out
    r = np.array([d["distance_m"] for d in inside])
    r = np.maximum(r, 1e-3)  # a distance of exactly 0 has zero likelihood under r g(r); it is a deer at the lens
    chosen, other = fit(r, w)
    p = detection_p(chosen, w)
    d_m2 = density(len(r), p, w, sum(efforts.values()))
    ci = bootstrap(inside + beyond, efforts, w, chosen, reps or BOOTSTRAPS)
    bins, width = _bins(r, w)
    xs = np.linspace(0, w, 61)
    curve = pdf(chosen, w, xs) * len(r) * width  # expected deer per bin, so the curve sits on the bars
    out.update(
        fit={"model": chosen["model"], "sigma": round(chosen["sigma"], 3),
             "b": round(chosen["b"], 3) if chosen["b"] is not None else None, "aic": round(chosen["aic"], 2),
             "other": {"model": other["model"], "aic": round(other["aic"], 2)} if other else None},
        bins=bins, curve=[{"r": round(float(x), 3), "n": round(float(y), 4)} for x, y in zip(xs, curve)],
        density={"per_km2": d_m2 * 1e6, "lo": ci[0] * 1e6, "hi": ci[1] * 1e6,
                 "p": p, "edr_m": w * math.sqrt(p)})
    return out


R_HEADER = """\
# CamTrap Measure: camera-trap distance sampling flat file for R's Distance package; {when}
# filters: site={site}; from={date_from}; to={date_to}; folder={folder}; species=white-tailed deer, suspicious rows left out
# snapshot interval t = {interval} s; truncation w = {w} m; one row per deer within w, one row with distance NA per camera with no deer
# Region.Label: one stratum; Area: 0, so dht2 reports density only; Sample.Label: camera
# Effort: that camera's snapshot moments (active seconds / t) times the fraction of the circle it sees (field of view / 360)
#   The field of view is already in Effort, so leave sample_fraction at 1. (The package's camera-trap example keeps Effort as
#   moments and passes sample_fraction = view angle / 360 instead; the two are the same when every camera has the same lens.)
# object: deer id; distance: metres from the camera; size: 1, every box is one animal; availability is taken as 1 (no multiplier)
# In R:
#   library(Distance)
#   d <- read.csv("this file.csv", comment.char = "#")
#   cu <- convert_units("meter", NULL, "square kilometer")
#   fit <- ds(d, transect = "point", key = "hn", truncation = {w}, convert_units = cu)   # or key = "hr"
#   dht2(fit, flatfile = d, strat_formula = ~1, er_est = "P2", convert_units = cu)
"""
R_COLUMNS = ["Region.Label", "Area", "Sample.Label", "Effort", "object", "distance", "size", "photo", "timestamp"]


def export_csv(rows: list[dict], photos: list[dict], saved: dict, filters: dict) -> str:
    """The flat file: the same deer, cameras, effort and truncation as the screen, in the Distance package's columns."""
    deer, _ = deer_rows(rows, photos)
    cams = camera_setup(photos, saved["cameras"])
    interval_s = saved["interval_s"] or DEFAULT_INTERVAL_S
    efforts = effort(cams, interval_s)
    deer = [d for d in deer if d["site"] in efforts]
    w = saved["truncation_m"] or default_truncation([d["distance_m"] for d in deer])
    inside = [d for d in deer if w and d["distance_m"] <= w]
    buf = io.StringIO()
    buf.write(R_HEADER.format(when=datetime.now().astimezone().isoformat(timespec="seconds"),
                              site=filters.get("site") or "all", date_from=filters.get("date_from") or "start",
                              date_to=filters.get("date_to") or "end", folder=filters.get("folder") or "all",
                              interval=f"{interval_s:g}", w=f"{w:g}" if w else "NA"))
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(R_COLUMNS)
    obj = 0
    for site in sorted(efforts):
        mine = [d for d in inside if d["site"] == site]
        eff = round(efforts[site], 4)
        if not mine:
            out.writerow(["study", 0, site, eff, "NA", "NA", "NA", "", ""])
        for d in mine:
            obj += 1
            out.writerow(["study", 0, site, eff, obj, d["distance_m"], 1, basename(d["path"]), d["captured_at"] or ""])
    return buf.getvalue()
