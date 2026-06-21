"""Procedural breathing phase computation."""

from __future__ import annotations

import math


def compute_breath_phase(time_sec: float, bpm: float, exhale_ratio: float) -> float:
    """Return breathing amount in [0, 1] (inhale peak=1, exhale end=0)."""
    bpm = max(1.0, float(bpm))
    ratio = max(1.0, float(exhale_ratio))
    cycle = 60.0 / bpm
    if cycle <= 1e-8:
        return 0.0

    t = time_sec % cycle
    inhale_frac = 1.0 / (1.0 + ratio)
    inhale_d = cycle * inhale_frac
    exhale_d = cycle - inhale_d

    if t < inhale_d:
        u = t / max(inhale_d, 1e-8)
        return 0.5 * (1.0 - math.cos(math.pi * u))
    u = (t - inhale_d) / max(exhale_d, 1e-8)
    return 0.5 * (1.0 + math.cos(math.pi * u))
