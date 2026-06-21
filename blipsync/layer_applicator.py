"""Shared layered apply (keyframes + procedural delta, no drift)."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache
    from .bake_keyframes import BakeKeyframeTracker

from .blend_targets import (
    clamp_shape_key_value,
    get_pose_value,
    keyframe_pose_axis,
    pose_axis_rest_value,
    set_pose_value,
)
from .keyframe_eval import eval_pose_axis_value, eval_shape_key_value, try_eval_pose_axis_fcurve
from .motion_layer_state import get_motion_layer_state, LAYER_MICRO
from .micro_pose_base import micro_pose_base


def procedural_delta(procedural: float, rest: float) -> float:
    return procedural - rest


def _resolve_pose_base(
    armature,
    bone_name: str,
    axis: str,
    frame: Optional[int],
    base_cache: Optional["BakeBaseCache"],
    *,
    layer: str = "",
) -> float:
    if base_cache is not None and frame is not None:
        if base_cache.has_pose_base(armature, bone_name, axis, frame):
            return base_cache.pose_base(
                armature, bone_name, axis, frame, fallback=0.0,
            )
    if layer == LAYER_MICRO:
        return micro_pose_base(armature, bone_name, axis, frame)
    keyed = try_eval_pose_axis_fcurve(armature, bone_name, axis, frame) if frame is not None else None
    if keyed is not None:
        return keyed
    bone = armature.pose.bones.get(bone_name) if armature else None
    if bone is None:
        return pose_axis_rest_value(axis)
    current = get_pose_value(bone, axis)
    rest = pose_axis_rest_value(axis)
    if not layer:
        return current
    return get_motion_layer_state().resolve_base(
        get_motion_layer_state().pose_key(armature, bone_name, axis, layer),
        current,
        rest_fallback=rest,
        rotation=axis.startswith("ROT"),
    )


def _resolve_shape_base(
    mesh,
    shape_key_name: str,
    kb,
    frame: Optional[int],
    base_cache: Optional["BakeBaseCache"],
) -> float:
    if base_cache is not None and frame is not None:
        if base_cache.has_shape_base(mesh, shape_key_name, frame):
            return base_cache.shape_base(
                mesh, shape_key_name, frame, fallback=0.0,
            )
    if frame is not None:
        return eval_shape_key_value(mesh, shape_key_name, frame)
    return float(kb.value) if kb is not None else 0.0


def apply_layered_pose(
    bone,
    armature,
    axis: str,
    procedural: float,
    *,
    frame: Optional[int] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    insert_keyframes: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    layer: str = "",
) -> float:
    rest = pose_axis_rest_value(axis)
    delta = procedural_delta(procedural, rest)
    base = _resolve_pose_base(
        armature, bone.name, axis, frame, base_cache, layer=layer,
    )
    final = base + delta
    set_pose_value(bone, axis, final)
    if not insert_keyframes:
        layer_state = get_motion_layer_state()
        layer_state.commit(
            layer_state.pose_key(armature, bone.name, axis, layer),
            delta,
            final,
            base,
        )
    if insert_keyframes and frame is not None:
        if keyframe_tracker is not None:
            keyframe_tracker.maybe_pose_axis(
                bone, armature, axis, frame, final, rest_value=base,
            )
        else:
            keyframe_pose_axis(bone, axis, frame)
    return final


def apply_layered_shape(
    kb,
    mesh,
    procedural_target: float,
    *,
    frame: Optional[int] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    insert_keyframes: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    layer: str = "",
) -> float:
    rest = float(kb.slider_min)
    delta = procedural_delta(procedural_target, rest)
    base = _resolve_shape_base(mesh, kb.name, kb, frame, base_cache)
    final = clamp_shape_key_value(kb, base + delta)
    kb.value = final
    if not insert_keyframes:
        layer_state = get_motion_layer_state()
        layer_state.commit(
            layer_state.shape_key(mesh, kb.name, layer),
            delta,
            final,
            base,
        )
    if insert_keyframes and frame is not None:
        if keyframe_tracker is not None:
            keyframe_tracker.maybe_shape_key(kb, mesh, frame, final, rest_value=base)
        else:
            kb.keyframe_insert(data_path="value", frame=frame)
    return final
