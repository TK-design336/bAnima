"""Apply lip sync weights to shape keys and pose bones (layered over keyframes)."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache
    from .bake_keyframes import BakeKeyframeTracker

from .blend_targets import (
    clamp_shape_key_value as _clamp_shape_key_value,
    get_pose_value as _get_pose_value,
    get_shape_key as _get_shape_key,
    keyframe_pose_axis as _keyframe_pose_axis,
    pose_axis_array_index as _pose_axis_array_index,
    pose_axis_rest_value as _pose_axis_rest_value,
    pose_data_path as _pose_data_path,
    prepare_pose_bone_for_axis as _prepare_pose_bone_for_axis,
    reset_pose_value as _reset_pose_value,
    set_pose_value as _set_pose_value,
)
from .motion_layer_state import LAYER_PHONEME
from .layer_applicator import apply_layered_pose, apply_layered_shape
from .pose_motion import procedural_pose_from_blend


def reset_mapping(phoneme_mapping) -> None:
    for expr in phoneme_mapping.phoneme_exprs:
        for bind in expr.binds:
            kb = _get_shape_key(bind.mesh, bind.shape_key)
            if kb:
                kb.value = kb.slider_min
        for pose_bind in expr.pose_binds:
            if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
                continue
            if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
                continue
            _reset_pose_value(
                pose_bind.armature.pose.bones[pose_bind.pose_bone],
                pose_bind.pose_axis,
            )


def reset_mappings(mappings: Iterable) -> None:
    seen: Set[int] = set()
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        reset_mapping(mapping)


def apply_weights(
    scene: bpy.types.Scene,
    weights: Dict[str, float],
    phoneme_mapping,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    reset: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    only_labels: Optional[Set[str]] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    apply_context=None,
    track_layer_state: bool = True,
) -> None:
    settings = scene.blipsync
    volume = weights.get("__volume__", 0.0)
    if reset:
        reset_mapping(phoneme_mapping)

    shape_targets: dict[tuple, tuple] = {}
    pose_targets: dict[tuple, tuple] = {}

    for expr in phoneme_mapping.phoneme_exprs:
        phoneme = expr.label
        if only_labels is not None and phoneme not in only_labels:
            continue
        ratio = weights.get(phoneme, 0.0)

        for bind in expr.binds:
            if not bind.mesh or not bind.shape_key:
                continue
            kb = _get_shape_key(bind.mesh, bind.shape_key)
            if not kb:
                continue
            blend = max(0.0, ratio * volume * settings.max_blend_value)
            target = kb.slider_min + (bind.weight_value - kb.slider_min) * blend
            shape_targets[(int(bind.mesh.as_pointer()), bind.shape_key)] = (
                kb, bind.mesh, target,
            )

        for pose_bind in expr.pose_binds:
            if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
                continue
            if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
                continue
            bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
            drive = max(0.0, ratio * volume * settings.max_blend_value)
            procedural = procedural_pose_from_blend(pose_bind, drive)
            pose_targets[
                (
                    int(pose_bind.armature.as_pointer()),
                    pose_bind.pose_bone,
                    pose_bind.pose_axis,
                )
            ] = (bone, pose_bind.armature, pose_bind.pose_axis, procedural)

    kw = dict(
        frame=frame,
        base_cache=base_cache,
        insert_keyframes=insert_keyframes,
        keyframe_tracker=keyframe_tracker,
        layer=LAYER_PHONEME,
        apply_context=apply_context,
        track_layer_state=track_layer_state,
    )
    for kb, mesh, target in shape_targets.values():
        apply_layered_shape(kb, mesh, target, **kw)
    for bone, armature, axis, procedural in pose_targets.values():
        apply_layered_pose(bone, armature, axis, procedural, **kw)
