"""Annotation QC: monotonicity checks, leave-one-flag-out CV."""
import copy

import numpy as np

from .model_a import ModelA
from .model_b import ModelB


def flag_pixels(photo):
    per_flag = {}
    for g in photo.ground:
        per_flag.setdefault((g.dist, g.transect), []).append(g)
    return {k: (float(np.mean([g.u for g in v])), float(np.mean([g.v for g in v])))
            for k, v in per_flag.items()}


def monotonicity(photo):
    violations = []
    for name in "LCR":
        # ground v must strictly decrease with distance
        pix = sorted(((d, uv) for (d, t), uv in flag_pixels(photo).items() if t == name))
        for (d1, (_, v1)), (d2, (_, v2)) in zip(pix, pix[1:]):
            if v2 >= v1:
                violations.append({"transect": name, "kind": "ground_v",
                                   "dist_a": d1, "dist_b": d2,
                                   "detail": f"v {v1:.0f} -> {v2:.0f} (must decrease)"})
        # apparent scale (px per cm) must strictly decrease with distance
        scale = {}
        for s in photo.size:
            if s.transect == name:
                scale.setdefault(s.dist, []).append(s.px_len / s.cm_len)
        sc = sorted((d, float(np.median(v))) for d, v in scale.items())
        for (d1, s1), (d2, s2) in zip(sc, sc[1:]):
            if s2 >= s1:
                violations.append({"transect": name, "kind": "size_scale",
                                   "dist_a": d1, "dist_b": d2,
                                   "detail": f"px/cm {s1:.2f} -> {s2:.2f} (must decrease)"})
    return violations


def _without_flag(photo, dist, transect):
    ph = copy.deepcopy(photo)
    ph.ground = [g for g in ph.ground if not (g.dist == dist and g.transect == transect)]
    ph.size = [s for s in ph.size if not (s.dist == dist and s.transect == transect)]
    return ph


def loo_cv(photo):
    rows = []
    for (dist, transect), (u, v) in sorted(flag_pixels(photo).items()):
        held_out = _without_flag(photo, dist, transect)
        pa, sa = ModelA.fit(held_out).predict(u, v)
        pb, sb = ModelB.fit(held_out).predict(u, v)
        n = sum(1 for g in photo.ground if g.dist == dist and g.transect == transect)
        rows.append({"site": photo.site, "image": photo.image,
                     "transect": transect, "dist": dist, "n_obs": n,
                     "pred_a": pa, "err_a": None if pa is None else pa - dist,
                     "pred_b": pb, "err_b": None if pb is None else pb - dist})
    return rows

