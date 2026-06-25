"""Apply procedural blink weights to shape keys and pose bones (layered over keyframes)."""

from __future__ import annotations

from typing import Iterable, Optional, Set, TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache
    from .bake_keyframes import BakeKeyframeTracker

from .blend_targets import get_shape_key, reset_pose_value
from .defaults import blink_mapping_is_configured
from .motion_layer_state import LAYER_BLINK
from .layer_applicator import apply_layered_pose, apply_layered_shape
from .pose_motion import procedural_pose_from_blend


def reset_blink_eye_slot(eye_slot) -> None:
    for bind in eye_slot.binds:
        kb = get_shape_key(bind.mesh, bind.shape_key)
        if kb:
            kb.value = kb.slider_min
    for pose_bind in eye_slot.pose_binds:
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        reset_pose_value(
            pose_bind.armature.pose.bones[pose_bind.pose_bone],
            pose_bind.pose_axis,
        )


def reset_blink_mapping(blink_mapping) -> None:
    reset_blink_eye_slot(blink_mapping.left_eye)
    reset_blink_eye_slot(blink_mapping.right_eye)


def reset_blink_mappings(mappings: Iterable) -> None:
    seen: Set[int] = set()
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        reset_blink_mapping(mapping)


def _apply_eye_slot(
    eye_slot,
    amount: float,
    max_blend: float,
    *,
    fac_jitter: float = 0.0,
    fac_jitter_amount: float = 0.0,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    apply_context=None,
    track_layer_state: bool = True,
) -> None:
    blink_blend = max(0.0, min(1.0, amount)) * max_blend
    jitter_blend = fac_jitter * fac_jitter_amount * max_blend

    shape_targets: dict[tuple, tuple] = {}
    pose_targets: dict[tuple, tuple] = {}

    for bind in eye_slot.binds:
        if not bind.mesh or not bind.shape_key:
            continue
        kb = get_shape_key(bind.mesh, bind.shape_key)
        if kb is None:
            continue
        blend = max(0.0, min(max_blend, blink_blend + jitter_blend))
        target = kb.slider_min + (bind.weight_value - kb.slider_min) * blend
        shape_targets[(int(bind.mesh.as_pointer()), bind.shape_key)] = (
            kb, bind.mesh, target,
        )

    for pose_bind in eye_slot.pose_binds:
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
        procedural = procedural_pose_from_blend(pose_bind, blink_blend)
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
        layer=LAYER_BLINK,
        apply_context=apply_context,
        track_layer_state=track_layer_state,
    )
    for kb, mesh, target in shape_targets.values():
        apply_layered_shape(kb, mesh, target, **kw)
    for bone, armature, axis, procedural in pose_targets.values():
        apply_layered_pose(bone, armature, axis, procedural, **kw)


def apply_blink_mapping(
    scene: bpy.types.Scene,
    amount: float,
    blink_mapping,
    *,
    fac_jitter_left: float = 0.0,
    fac_jitter_right: float = 0.0,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    reset: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    apply_context=None,
    track_layer_state: bool = True,
) -> None:
    if not blink_mapping_is_configured(blink_mapping):
        return

    settings = scene.blipsync
    if reset:
        reset_blink_mapping(blink_mapping)

    max_blend = settings.max_blend_value
    jitter_amount = float(blink_mapping.fac_jitter_amount)
    kw = dict(
        insert_keyframes=insert_keyframes,
        frame=frame,
        keyframe_tracker=keyframe_tracker,
        base_cache=base_cache,
        apply_context=apply_context,
        track_layer_state=track_layer_state,
    )
    _apply_eye_slot(
        blink_mapping.left_eye,
        amount,
        max_blend,
        fac_jitter=fac_jitter_left,
        fac_jitter_amount=jitter_amount,
        **kw,
    )
    _apply_eye_slot(
        blink_mapping.right_eye,
        amount,
        max_blend,
        fac_jitter=fac_jitter_right,
        fac_jitter_amount=jitter_amount,
        **kw,
    )
