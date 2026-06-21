"""Procedural blink timing with Gaussian intervals."""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

import bpy


def _blink_phase_weight(elapsed: float, close_duration: float, open_duration: float) -> float:
    if elapsed < 0.0:
        return 0.0
    if elapsed < close_duration:
        if close_duration <= 1e-8:
            return 1.0
        return elapsed / close_duration
    elapsed_open = elapsed - close_duration
    if elapsed_open < open_duration:
        if open_duration <= 1e-8:
            return 0.0
        return max(0.0, 1.0 - (elapsed_open / open_duration))
    return 0.0


def blink_seed(mapping, scene: bpy.types.Scene) -> int:
    if mapping.random_seed != 0:
        return int(mapping.random_seed) & 0x7FFFFFFF
    return hash((scene.name_full, mapping.name, "blipsync_blink")) & 0x7FFFFFFF


def compute_eyelid_jitter(
    time_sec: float,
    seed: int,
    speed: float,
    *,
    eye_phase: float = 0.0,
) -> float:
    """Smooth eyelid micro-motion in [-1, 1], independent of blink timing."""
    if speed <= 1e-8:
        return 0.0

    rng = random.Random((seed ^ 0xFAC71177) & 0x7FFFFFFF)
    t = time_sec * speed
    value = 0.0
    norm = 0.0
    for i in range(4):
        phase = rng.uniform(0.0, 2.0 * math.pi) + eye_phase
        freq = 0.38 + i * 0.19 + rng.uniform(-0.04, 0.04)
        amp = 1.0 / (i + 1)
        value += amp * math.sin(2.0 * math.pi * freq * t + phase)
        norm += amp
    if norm <= 1e-8:
        return 0.0
    return max(-1.0, min(1.0, value / norm))


def eyelid_jitter_eye_phases(seed: int) -> tuple[float, float]:
    """Shared rhythm with a subtle left/right phase offset (radians)."""
    rng = random.Random((seed ^ 0xE7E0A00) & 0x7FFFFFFF)
    base = rng.uniform(0.0, 2.0 * math.pi)
    half_spread = rng.uniform(0.04, 0.12)
    return base - half_spread, base + half_spread


def _next_blink_interval(rng: random.Random, mean: float, std: float, *, first: bool) -> float:
    if first:
        return rng.uniform(0.0, mean)
    return max(0.5, rng.gauss(mean, std))


def build_blink_schedule(
    settings,
    seed: int,
    until_time_sec: float,
) -> Tuple[List[Tuple[float, float]], float, float]:
    """Precompute blink windows [(start, end), ...] up to until_time_sec."""
    mean = max(0.5, float(settings.blink_interval_mean))
    jitter = max(0.0, float(settings.blink_jitter))
    std = max(0.01, mean * 0.25 * jitter)
    close_d = max(0.01, float(settings.blink_close_duration))
    open_d = max(0.01, float(settings.blink_open_duration))

    rng = random.Random(seed)
    cursor = 0.0
    limit = until_time_sec + close_d + open_d
    first_interval = True
    schedule: List[Tuple[float, float]] = []

    while cursor < limit:
        interval = _next_blink_interval(rng, mean, std, first=first_interval)
        first_interval = False
        blink_start = cursor + interval
        blink_end = blink_start + close_d + open_d
        schedule.append((blink_start, blink_end))
        if blink_start > until_time_sec:
            break
        cursor = blink_end

    return schedule, close_d, open_d


def compute_blink_amount_from_schedule(
    time_sec: float,
    schedule: List[Tuple[float, float]],
    close_d: float,
    open_d: float,
) -> float:
    for blink_start, blink_end in schedule:
        if time_sec < blink_start:
            return 0.0
        if blink_start <= time_sec < blink_end:
            return _blink_phase_weight(time_sec - blink_start, close_d, open_d)
    return 0.0


def compute_blink_amount(
    time_sec: float,
    settings,
    *,
    seed: Optional[int] = None,
    schedule: Optional[List[Tuple[float, float]]] = None,
    close_d: Optional[float] = None,
    open_d: Optional[float] = None,
) -> float:
    if not settings.blink_enabled:
        return 0.0

    if schedule is not None and close_d is not None and open_d is not None:
        return compute_blink_amount_from_schedule(time_sec, schedule, close_d, open_d)

    mean = max(0.5, float(settings.blink_interval_mean))
    jitter = max(0.0, float(settings.blink_jitter))
    std = max(0.01, mean * 0.25 * jitter)
    close_d = max(0.01, float(settings.blink_close_duration))
    open_d = max(0.01, float(settings.blink_open_duration))

    rng = random.Random(0 if seed is None else seed)
    cursor = 0.0
    limit = time_sec + close_d + open_d
    first_interval = True

    while cursor < limit:
        interval = _next_blink_interval(rng, mean, std, first=first_interval)
        first_interval = False
        blink_start = cursor + interval
        blink_end = blink_start + close_d + open_d
        if blink_start <= time_sec < blink_end:
            return _blink_phase_weight(time_sec - blink_start, close_d, open_d)
        if blink_start > time_sec:
            break
        cursor = blink_end

    return 0.0


def scene_time_at_frame(scene: bpy.types.Scene, frame: float) -> float:
    fps = scene.render.fps / scene.render.fps_base
    return frame / max(fps, 1e-8)


def compute_blink_eyelid_jitters(
    time_sec: float,
    mapping,
    scene: bpy.types.Scene,
    settings,
) -> tuple[float, float]:
    amount = float(mapping.fac_jitter_amount)
    speed = float(settings.blink_eyelid_jitter_speed)
    if amount <= 1e-8 or speed <= 1e-8:
        return 0.0, 0.0
    seed = blink_seed(mapping, scene)
    phase_left, phase_right = eyelid_jitter_eye_phases(seed)
    return (
        compute_eyelid_jitter(time_sec, seed, speed, eye_phase=phase_left),
        compute_eyelid_jitter(time_sec, seed, speed, eye_phase=phase_right),
    )
