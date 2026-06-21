"""Procedural head sway, gaze saccades, and facial micro-noise."""

from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

import bpy

from .blink_engine import compute_eyelid_jitter


def motion_seed(mapping, scene: bpy.types.Scene, namespace: str) -> int:
    if mapping.random_seed != 0:
        return int(mapping.random_seed) & 0x7FFFFFFF
    return hash((scene.name_full, mapping.name, namespace)) & 0x7FFFFFFF


def reset_head_smoothing(mapping=None) -> None:
    """Reset micro-motion pose bases (playback / scrub)."""
    from .micro_pose_base import reset_micro_pose_bases

    reset_micro_pose_bases()


def _smooth_step(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return 0.5 * (1.0 - math.cos(math.pi * u))


def _lo_hi(min_val: float, max_val: float, *, floor: float) -> Tuple[float, float]:
    lo = max(floor, min(min_val, max_val))
    hi = max(lo, max(min_val, max_val))
    return lo, hi


def _head_bind_schedule_1d(
    rng: random.Random,
    time_sec: float,
    interval_min: float,
    interval_max: float,
    motion_time_min: float,
    motion_time_max: float,
) -> float:
    """One pose-bind axis: wait → move to random target → return to neutral.

    Returns normalized offset in [-1, 1]. Deterministic from time_sec + rng seed.
    """
    lo_i, hi_i = _lo_hi(interval_min, interval_max, floor=0.1)
    lo_m, hi_m = _lo_hi(motion_time_min, motion_time_max, floor=0.01)

    cursor = 0.0
    pos = 0.0
    limit = time_sec + hi_i + hi_m * 2.0 + 1.0

    while cursor <= limit:
        interval = rng.uniform(lo_i, hi_i)
        wait_end = cursor + interval
        if time_sec < wait_end:
            return pos

        target = rng.uniform(-1.0, 1.0)
        travel_d = rng.uniform(lo_m, hi_m)
        travel_end = wait_end + travel_d
        if time_sec < travel_end:
            u = (time_sec - wait_end) / travel_d
            return pos + (target - pos) * _smooth_step(u)

        return_d = rng.uniform(lo_m, hi_m)
        return_end = travel_end + return_d
        if time_sec < return_end:
            u = (time_sec - travel_end) / return_d
            return target + (0.0 - target) * _smooth_step(u)

        pos = 0.0
        cursor = return_end

    return pos


def compute_head_sway_binds(
    mapping,
    time_sec: float,
    seed: int,
    settings,
) -> List[float]:
    """Per head pose-bind offset in radians (full amplitude; weight applied at apply time)."""
    pose_binds = mapping.head.pose_binds
    if not pose_binds:
        return []

    amplitude_deg = float(settings.micro_head_sway_amplitude)
    if amplitude_deg <= 1e-8:
        return [0.0] * len(pose_binds)

    amp_rad = math.radians(amplitude_deg)
    interval_min = float(settings.micro_head_sway_interval_min)
    interval_max = float(settings.micro_head_sway_interval_max)
    motion_time_min = float(settings.micro_head_sway_motion_time_min)
    motion_time_max = float(settings.micro_head_sway_motion_time_max)

    offsets: List[float] = []
    for bind_index in range(len(pose_binds)):
        bind_seed = (seed ^ (0x0EAD57A1 + bind_index * 0x517CC1B7)) & 0x7FFFFFFF
        rng = random.Random(bind_seed)
        norm = _head_bind_schedule_1d(
            rng,
            time_sec,
            interval_min,
            interval_max,
            motion_time_min,
            motion_time_max,
        )
        offsets.append(norm * amp_rad)
    return offsets


def _lerp2(
    a: Tuple[float, float],
    b: Tuple[float, float],
    t: float,
) -> Tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _saccade_schedule_2d(
    rng: random.Random,
    time_sec: float,
    interval_min: float,
    interval_max: float,
    travel_time: float,
    return_time: float,
) -> Tuple[float, float]:
    """Unified gaze offset (x=horizontal, y=vertical) in [-1, 1] for both eyes."""
    lo = max(0.1, min(interval_min, interval_max))
    hi = max(lo, max(interval_min, interval_max))
    travel_d = max(0.01, float(travel_time))
    return_d = max(0.01, float(return_time))

    cursor = 0.0
    pos = (0.0, 0.0)
    limit = time_sec + travel_d + return_d + hi

    while cursor <= limit:
        interval = rng.uniform(lo, hi)
        wait_end = cursor + interval
        if time_sec < wait_end:
            return pos

        target = (rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0))
        travel_end = wait_end + travel_d
        if time_sec < travel_end:
            u = (time_sec - wait_end) / travel_d
            return _lerp2(pos, target, _smooth_step(u))

        return_end = travel_end + return_d
        if time_sec < return_end:
            u = (time_sec - travel_end) / return_d
            return _lerp2(target, (0.0, 0.0), _smooth_step(u))

        pos = (0.0, 0.0)
        cursor = return_end

    return pos


def compute_gaze_saccade(
    time_sec: float,
    seed: int,
    settings,
    mapping,
) -> Tuple[Tuple[float, float], Dict[str, float]]:
    """Unified saccade for both eyes. Returns ((horizontal_rad, vertical_rad), shape_key_weights)."""
    zero_bone = (0.0, 0.0)
    zero_shape = {
        "look_up": 0.0,
        "look_down": 0.0,
        "look_left": 0.0,
        "look_right": 0.0,
    }
    if not settings.micro_saccade_enabled:
        return zero_bone, zero_shape

    rng = random.Random((seed ^ 0x5ACCADE) & 0x7FFFFFFF)
    off_x, off_y = _saccade_schedule_2d(
        rng,
        time_sec,
        float(settings.micro_saccade_interval_min),
        float(settings.micro_saccade_interval_max),
        float(settings.micro_saccade_travel_time),
        float(settings.micro_saccade_return_time),
    )

    if getattr(mapping, "gaze_control", "BONE") == "BONE":
        amp = math.radians(float(settings.micro_saccade_amplitude_deg))
        if amp <= 1e-8:
            return zero_bone, zero_shape
        return (off_x * amp, off_y * amp), zero_shape

    intensity = float(settings.micro_saccade_intensity)
    if intensity <= 1e-8:
        return zero_bone, zero_shape
    return zero_bone, {
        "look_up": max(0.0, off_y) * intensity,
        "look_down": max(0.0, -off_y) * intensity,
        "look_left": max(0.0, -off_x) * intensity,
        "look_right": max(0.0, off_x) * intensity,
    }


def compute_facial_noise(
    time_sec: float,
    seed: int,
    intensity: float,
    *,
    slot_phase: float = 0.0,
) -> float:
    if intensity <= 1e-8:
        return 0.0
    return compute_eyelid_jitter(
        time_sec, seed, speed=0.6, eye_phase=slot_phase,
    ) * intensity


def compute_micro_motion_state(
    time_sec: float,
    mapping,
    scene: bpy.types.Scene,
    settings,
    *,
    dt: float = 0.0,
) -> dict:
    seed = motion_seed(mapping, scene, "blipsync_micro_motion")
    head_binds = compute_head_sway_binds(mapping, time_sec, seed, settings)
    gaze_bone_offset, gaze_shape_weights = compute_gaze_saccade(
        time_sec, seed, settings, mapping,
    )
    noise_intensity = float(settings.micro_facial_noise_intensity)
    return {
        "head_binds": head_binds,
        "gaze_bone_horizontal": gaze_bone_offset[0],
        "gaze_bone_vertical": gaze_bone_offset[1],
        "gaze_shape_weights": gaze_shape_weights,
        "eyebrow_noise": compute_facial_noise(time_sec, seed, noise_intensity, slot_phase=0.0),
        "mouth_noise": compute_facial_noise(time_sec, seed, noise_intensity, slot_phase=1.7),
    }
