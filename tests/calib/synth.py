"""Synthetic PhotoData generators for tests."""
import numpy as np

from camtrap_measure.calib.data import GroundObs, PhotoData, SizeObs
from camtrap_measure.calib.model_b import PlaneParams, world_to_pixel, predicted_px


def flat_photo(dists=range(2, 16), transects=(("L", 700.0), ("C", 960.0), ("R", 1220.0))):
    """Toy mapping: ground v = 1000 - 30*dist; transect u constant per transect."""
    ph = PhotoData("SYN", "SYN.JPG", 1920, 1080)
    for t, u in transects:
        for d in dists:
            ph.ground.append(GroundObs(u, 1000.0 - 30.0 * d, float(d), t, "wire_point", 1.0))
    return ph


def projective_photo(f=3000.0, h=1.2, pitch=0.12, roll=0.02, noise_px=0.0, seed=0,
                     azimuths_deg=(-10.0, 0.0, 10.0), dists=range(2, 16)):
    """PhotoData rendered from a known camera; returns (photo, true_params)."""
    rng = np.random.default_rng(seed)
    p = PlaneParams(f, h, pitch, roll)
    cx, cy = 960.0, 540.0
    ph = PhotoData("SYN", "SYN.JPG", 1920, 1080)
    for name, az in zip("LCR", np.radians(azimuths_deg)):
        for d in dists:
            x, z = d * np.sin(az), d * np.cos(az)
            u, v = world_to_pixel(x, h, z, p, cx, cy)
            u += rng.normal(0, noise_px)
            v += rng.normal(0, noise_px)
            ph.ground.append(GroundObs(float(u), float(v), float(d), name, "wire_point", 1.0))
            px = predicted_px(float(d), 6.35, p, vertical=True) + rng.normal(0, noise_px)
            ph.size.append(SizeObs(float(u), float(v) - 20.0, float(max(px, 1.0)), 6.35,
                                   float(d), name, "vspan", 1.0, True))
    return ph, p
