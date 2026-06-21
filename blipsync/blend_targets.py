"""Low-level shape-key and pose-bone read/write helpers (no applicator imports)."""

from __future__ import annotations

_EULER_ROTATION_MODES = frozenset({"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"})


def get_shape_key(obj, name: str):
    if not obj or obj.type != "MESH" or not obj.data:
        return None
    keys = obj.data.shape_keys
    return keys.key_blocks.get(name) if keys else None


def clamp_shape_key_value(kb, value: float) -> float:
    return max(kb.slider_min, min(kb.slider_max, value))


def pose_axis_rest_value(axis: str) -> float:
    return 1.0 if axis.startswith("SCALE") else 0.0


def pose_axis_array_index(axis: str) -> int:
    if axis.endswith("_X"):
        return 0
    if axis.endswith("_Y"):
        return 1
    if axis.endswith("_Z"):
        return 2
    return 0


def prepare_pose_bone_for_axis(bone, axis: str) -> None:
    if axis.startswith("ROT") and bone.rotation_mode not in _EULER_ROTATION_MODES:
        bone.rotation_mode = "XYZ"


def get_pose_value(bone, axis: str) -> float:
    if axis == "LOC_X":
        return float(bone.location.x)
    if axis == "LOC_Y":
        return float(bone.location.y)
    if axis == "LOC_Z":
        return float(bone.location.z)
    if axis == "ROT_X":
        return float(bone.rotation_euler.x)
    if axis == "ROT_Y":
        return float(bone.rotation_euler.y)
    if axis == "ROT_Z":
        return float(bone.rotation_euler.z)
    if axis == "SCALE_X":
        return float(bone.scale.x)
    if axis == "SCALE_Y":
        return float(bone.scale.y)
    if axis == "SCALE_Z":
        return float(bone.scale.z)
    return 0.0


def set_pose_value(bone, axis: str, value: float) -> None:
    prepare_pose_bone_for_axis(bone, axis)
    if axis == "LOC_X":
        bone.location.x = value
    elif axis == "LOC_Y":
        bone.location.y = value
    elif axis == "LOC_Z":
        bone.location.z = value
    elif axis == "ROT_X":
        bone.rotation_euler.x = value
    elif axis == "ROT_Y":
        bone.rotation_euler.y = value
    elif axis == "ROT_Z":
        bone.rotation_euler.z = value
    elif axis == "SCALE_X":
        bone.scale.x = value
    elif axis == "SCALE_Y":
        bone.scale.y = value
    elif axis == "SCALE_Z":
        bone.scale.z = value


def reset_pose_value(bone, axis: str) -> None:
    set_pose_value(bone, axis, pose_axis_rest_value(axis))


def pose_data_path(axis: str) -> str:
    if axis.startswith("LOC"):
        return "location"
    if axis.startswith("ROT"):
        return "rotation_euler"
    return "scale"


def keyframe_pose_axis(bone, axis: str, frame: int) -> None:
    prepare_pose_bone_for_axis(bone, axis)
    bone.keyframe_insert(
        data_path=pose_data_path(axis),
        index=pose_axis_array_index(axis),
        frame=frame,
    )
