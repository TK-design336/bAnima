"""Read keyframe-interpolated values without scene.frame_set (handler-safe)."""

from __future__ import annotations

from typing import Optional

import bpy

from .blend_targets import (
    get_shape_key,
    pose_axis_array_index,
    pose_axis_rest_value,
    pose_data_path,
)


def _escape_path_name(name: str) -> str:
    return name.replace("\\", "\\\\").replace('"', '\\"')


def _find_fcurve(anim_data, data_path: str, index: int = 0):
    if not anim_data or not anim_data.action:
        return None
    return anim_data.action.fcurves.find(data_path, index=index)


def _eval_fcurve(anim_data, data_path: str, index: int, frame: float) -> Optional[float]:
    fc = _find_fcurve(anim_data, data_path, index)
    if fc is None:
        return None
    try:
        return float(fc.evaluate(frame))
    except Exception:
        return None


def try_eval_shape_key_fcurve(
    mesh_obj: bpy.types.Object,
    shape_key_name: str,
    frame: float,
) -> Optional[float]:
    """Return FCurve-interpolated shape-key value, or None if not keyed."""
    if not mesh_obj or mesh_obj.type != "MESH":
        return None
    path = f'key_blocks["{_escape_path_name(shape_key_name)}"].value'
    sk = mesh_obj.data.shape_keys if mesh_obj.data else None
    if sk is not None:
        value = _eval_fcurve(sk.animation_data, path, 0, frame)
        if value is not None:
            return value
    return _eval_fcurve(mesh_obj.animation_data, path, 0, frame)


def eval_shape_key_value(
    mesh_obj: bpy.types.Object,
    shape_key_name: str,
    frame: float,
) -> float:
    kb = get_shape_key(mesh_obj, shape_key_name)
    if kb is None:
        return 0.0
    keyed = try_eval_shape_key_fcurve(mesh_obj, shape_key_name, frame)
    if keyed is not None:
        return keyed
    return float(kb.slider_min)


def try_eval_pose_axis_fcurve(
    armature_obj: bpy.types.Object,
    bone_name: str,
    axis: str,
    frame: float,
) -> Optional[float]:
    if not armature_obj or armature_obj.type != "ARMATURE":
        return None
    if bone_name not in armature_obj.pose.bones:
        return None
    path = (
        f'pose.bones["{_escape_path_name(bone_name)}"].'
        f"{pose_data_path(axis)}"
    )
    return _eval_fcurve(
        armature_obj.animation_data,
        path,
        pose_axis_array_index(axis),
        frame,
    )


def eval_pose_axis_value(
    armature_obj: bpy.types.Object,
    bone_name: str,
    axis: str,
    frame: float,
) -> float:
    keyed = try_eval_pose_axis_fcurve(armature_obj, bone_name, axis, frame)
    if keyed is not None:
        return keyed
    return pose_axis_rest_value(axis)
