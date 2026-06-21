"""Apply emotion sync weights to shape keys and pose bones (layered over keyframes)."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set, TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache
    from .bake_keyframes import BakeKeyframeTracker

from .blend_targets import get_shape_key, reset_pose_value
from .defaults import merge_unconfigured_high_emotion_weights
from .layer_applicator import apply_layered_pose, apply_layered_shape
from .pose_motion import procedural_pose_from_blend


def reset_emotion_mapping(emotion_mapping) -> None:
    for expr in emotion_mapping.emotion_exprs:
        for bind in expr.binds:
            kb = get_shape_key(bind.mesh, bind.shape_key)
            if kb:
                kb.value = kb.slider_min
        for pose_bind in expr.pose_binds:
            if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
                continue
            if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
                continue
            reset_pose_value(
                pose_bind.armature.pose.bones[pose_bind.pose_bone],
                pose_bind.pose_axis,
            )


def reset_emotion_mappings(mappings: Iterable) -> None:
    seen: Set[int] = set()
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        reset_emotion_mapping(mapping)


def apply_emotion_weights(
    scene: bpy.types.Scene,
    weights: Dict[str, float],
    emotion_mapping,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    reset: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    only_labels: Optional[Set[str]] = None,
    base_cache: Optional["BakeBaseCache"] = None,
) -> None:
    settings = scene.blipsync
    if reset:
        reset_emotion_mapping(emotion_mapping)

    weights = merge_unconfigured_high_emotion_weights(weights, emotion_mapping)

    shape_targets: dict[tuple, tuple] = {}
    pose_targets: dict[tuple, tuple] = {}

    for expr in emotion_mapping.emotion_exprs:
        label = expr.label
        if only_labels is not None and label not in only_labels:
            continue
        ratio = weights.get(label, 0.0)

        for bind in expr.binds:
            if not bind.mesh or not bind.shape_key:
                continue
            kb = get_shape_key(bind.mesh, bind.shape_key)
            if not kb:
                continue
            blend = max(0.0, ratio * settings.max_blend_value)
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
            drive = max(0.0, ratio * settings.max_blend_value)
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
    )
    for kb, mesh, target in shape_targets.values():
        apply_layered_shape(kb, mesh, target, **kw)
    for bone, armature, axis, procedural in pose_targets.values():
        apply_layered_pose(bone, armature, axis, procedural, **kw)
