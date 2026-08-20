"""Model A: per-transect monotone interpolation of distance vs pixel row."""
import numpy as np
from scipy.interpolate import PchipInterpolator


def blend(pos, anchors):
    """Linear blend of (position, value) anchors; clamps outside the fan."""
    anchors = sorted(anchors)
    xs = [a[0] for a in anchors]
    ys = [a[1] for a in anchors]
    return float(np.interp(pos, xs, ys))


class _Transect:
    def __init__(self, flags):
        # flags: list of (dist, mean_u, mean_v), one entry per flag
        flags = sorted(flags, key=lambda f: f[2])  # by v ascending (far -> near)
        vs = np.array([f[2] for f in flags])
        ds = np.array([f[0] for f in flags])
        us = np.array([f[1] for f in flags])
        keep = np.concatenate([[True], np.diff(vs) > 1e-6])  # PCHIP needs strict x
        self.vs, self.ds, self.us = vs[keep], ds[keep], us[keep]
        if len(self.vs) >= 2:
            self.v_min, self.v_max = float(self.vs[0]), float(self.vs[-1])
            self.interp = PchipInterpolator(self.vs, self.ds)
        else:
            self.v_min, self.v_max = None, None
            self.interp = None

    def dist(self, v):
        return float(self.interp(v))

    def centerline_u(self, v):
        return float(np.interp(v, self.vs, self.us))


class ModelA:
    def __init__(self, transects):
        self.transects = transects  # dict name -> _Transect

    @classmethod
    def fit(cls, photo):
        transects = {}
        for name in "LCR":
            per_flag = {}
            for g in photo.ground:
                if g.transect == name:
                    per_flag.setdefault(g.dist, []).append(g)
            flags = [(d, float(np.mean([g.u for g in obs])), float(np.mean([g.v for g in obs])))
                     for d, obs in per_flag.items()]
            if len(flags) >= 2:
                t = _Transect(flags)
                if len(t.vs) >= 2:
                    transects[name] = t
        return cls(transects)

    def predict(self, u, v):
        if not self.transects:
            return None, "insufficient_data"
        usable = [t for t in self.transects.values() if t.v_min <= v <= t.v_max]
        if not usable:
            if v > max(t.v_max for t in self.transects.values()):
                return None, "below_range"   # closer than the nearest flag
            return None, "beyond_range"      # farther than the farthest flag (or in a gap)
        anchors = [(t.centerline_u(v), t.dist(v)) for t in usable]
        return blend(u, anchors), "ok"
