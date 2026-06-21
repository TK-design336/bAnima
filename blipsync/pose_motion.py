"""Pose bind amounts for procedural breathing / micro-motion."""

from __future__ import annotations

import math


def default_motion_amount(axis: str) -> float:
    if axis.startswith("SCALE"):
        return 1.0
    if axis.startswith("ROT"):
        return 5.0
    if axis.startswith("LOC"):
        return 0.01
    return 1.0


def clamp_motion_amount(pose_bind) -> None:
    axis = pose_bind.pose_axis
    value = float(pose_bind.motion_amount)
    if axis.startswith("SCALE"):
        clamped = max(0.5, min(2.0, value))
    elif axis.startswith("ROT"):
        clamped = max(-180.0, min(180.0, value))
    elif axis.startswith("LOC"):
        clamped = max(-1.0, min(1.0, value))
    else:
        clamped = value
    if abs(clamped - value) > 1e-9:
        pose_bind.motion_amount = clamped


def motion_pose_final_value(pose_bind, drive: float, *, offset: float = 0.0) -> float:
    """Map procedural drive [0, 1] or signed noise to a pose axis value."""
    amount = float(pose_bind.motion_amount)
    axis = pose_bind.pose_axis

    if axis.startswith("ROT"):
        extent = math.radians(amount)
        if abs(offset) > 1e-8:
            return extent * offset
        return extent * drive

    if axis.startswith("LOC"):
        if abs(offset) > 1e-8:
            return amount * offset
        return amount * drive

    if axis.startswith("SCALE"):
        blend = max(0.0, min(1.0, abs(offset if abs(offset) > 1e-8 else drive)))
        return 1.0 + (amount - 1.0) * blend

    return amount * drive
