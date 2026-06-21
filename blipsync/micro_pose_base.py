"""Fixed bind-pose bases for micro-motion pose binds (avoids per-frame strip jitter)."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .blend_targets import get_pose_value, pose_axis_rest_value
from .keyframe_eval import try_eval_pose_axis_fcurve

BaseKey = Tuple[int, str, str]

_MICRO_POSE_BASES: Dict[BaseKey, float] = {}


def reset_micro_pose_bases() -> None:
    _MICRO_POSE_BASES.clear()


def micro_pose_base(
    armature,
    bone_name: str,
    axis: str,
    frame: Optional[int],
) -> float:
    """Return the animation base for a micro-motion pose bind.

    Keyed axes use the FCurve each frame. Unkeyed axes use the pose value
    captured once at playback / scrub start so micro offsets do not accumulate
    or fight the previous frame's write.
    """
    if frame is not None:
        keyed = try_eval_pose_axis_fcurve(armature, bone_name, axis, frame)
        if keyed is not None:
            return keyed

    if armature is None:
        return pose_axis_rest_value(axis)

    key: BaseKey = (int(armature.as_pointer()), bone_name, axis)
    if key in _MICRO_POSE_BASES:
        return _MICRO_POSE_BASES[key]

    bone = armature.pose.bones.get(bone_name)
    value = get_pose_value(bone, axis) if bone else pose_axis_rest_value(axis)
    _MICRO_POSE_BASES[key] = value
    return value
