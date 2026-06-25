"""Apply breathing and micro-motion procedural weights (layered over keyframes)."""

from __future__ import annotations

from typing import Iterable, Optional, Set, TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache
    from .bake_keyframes import BakeKeyframeTracker

from .blend_targets import (
    get_shape_key,
    pose_axis_array_index,
    pose_axis_rest_value,
    reset_pose_value,
)
from .defaults import (
    breathing_mapping_is_configured,
    micro_motion_mapping_is_configured,
)
from .layer_applicator import apply_layered_pose, apply_layered_shape, procedural_delta
from .motion_layer_state import LAYER_BREATHING, LAYER_MICRO
from .pose_bind_order import iter_pose_binds_sorted, sort_pose_binds
from .properties import MICRO_MOTION_ALL_SLOT_ATTRS, MICRO_MOTION_GAZE_SHAPE_SLOTS
from .pose_motion import motion_pose_final_value


def reset_bind_slot(bind_slot) -> None:
    for bind in bind_slot.binds:
        kb = get_shape_key(bind.mesh, bind.shape_key)
        if kb:
            kb.value = kb.slider_min
    for pose_bind in sort_pose_binds(bind_slot.pose_binds):
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        reset_pose_value(
            pose_bind.armature.pose.bones[pose_bind.pose_bone],
            pose_bind.pose_axis,
        )


def reset_breathing_mapping(mapping) -> None:
    reset_bind_slot(mapping.targets)


def reset_micro_motion_mapping(mapping) -> None:
    for attr in MICRO_MOTION_ALL_SLOT_ATTRS:
        reset_bind_slot(getattr(mapping, attr))


def reset_breathing_mappings(mappings: Iterable) -> None:
    seen: Set[int] = set()
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        reset_breathing_mapping(mapping)


def reset_micro_motion_mappings(mappings: Iterable) -> None:
    seen: Set[int] = set()
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        reset_micro_motion_mapping(mapping)


def _axis_index(axis: str) -> int:
    return pose_axis_array_index(axis)


def _gaze_offset_for_pose_axis(axis: str, horizontal: float, vertical: float) -> float:
    if axis == "ROT_X":
        return vertical
    if axis == "ROT_Y":
        return horizontal
    if axis == "ROT_Z":
        return horizontal
    return 0.0


def _procedural_delta(procedural: float, rest: float) -> float:
    return procedural_delta(procedural, rest)


def _apply_layered_pose(
    bone,
    armature: bpy.types.Object,
    axis: str,
    procedural: float,
    *,
    frame: Optional[int] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    insert_keyframes: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    layer: str = "",
    track_layer_state: bool = True,
) -> float:
    return apply_layered_pose(
        bone,
        armature,
        axis,
        procedural,
        frame=frame,
        base_cache=base_cache,
        insert_keyframes=insert_keyframes,
        keyframe_tracker=keyframe_tracker,
        layer=layer,
        track_layer_state=track_layer_state,
    )


def _apply_layered_shape(
    kb,
    mesh: bpy.types.Object,
    procedural_target: float,
    *,
    frame: Optional[int] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    insert_keyframes: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    layer: str = "",
    track_layer_state: bool = True,
    apply_context=None,
) -> float:
    return apply_layered_shape(
        kb,
        mesh,
        procedural_target,
        frame=frame,
        base_cache=base_cache,
        insert_keyframes=insert_keyframes,
        keyframe_tracker=keyframe_tracker,
        layer=layer,
        track_layer_state=track_layer_state,
        apply_context=apply_context,
    )


def _apply_head_sway_to_bind_slot(
    bind_slot,
    bind_offsets: list[float],
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    layer: str = "",
    track_layer_state: bool = True,
) -> None:
    """Apply per pose-bind head offsets (each bind has its own schedule)."""
    for bind_index, pose_bind in iter_pose_binds_sorted(bind_slot.pose_binds):
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
        offset = bind_offsets[bind_index] if bind_index < len(bind_offsets) else 0.0
        if pose_bind.pose_axis.startswith("ROT") or pose_bind.pose_axis.startswith("LOC"):
            procedural = offset * pose_bind.weight
        else:
            procedural = pose_axis_rest_value(pose_bind.pose_axis)
        _apply_layered_pose(
            bone,
            pose_bind.armature,
            pose_bind.pose_axis,
            procedural,
            frame=frame,
            base_cache=base_cache,
            insert_keyframes=insert_keyframes,
            keyframe_tracker=keyframe_tracker,
            layer=layer,
            track_layer_state=track_layer_state,
        )


def _apply_pose_offset_to_bind_slot(
    bind_slot,
    max_blend: float,
    pose_offset: tuple[float, float, float],
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    layer: str = "",
    track_layer_state: bool = True,
) -> None:
    for pose_bind in sort_pose_binds(bind_slot.pose_binds):
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
        axis_idx = _axis_index(pose_bind.pose_axis)
        offset = pose_offset[axis_idx] if axis_idx < len(pose_offset) else 0.0
        if pose_bind.pose_axis.startswith("ROT") or pose_bind.pose_axis.startswith("LOC"):
            procedural = offset * pose_bind.weight
        else:
            procedural = pose_axis_rest_value(pose_bind.pose_axis)
        _apply_layered_pose(
            bone,
            pose_bind.armature,
            pose_bind.pose_axis,
            procedural,
            frame=frame,
            base_cache=base_cache,
            insert_keyframes=insert_keyframes,
            keyframe_tracker=keyframe_tracker,
            layer=layer,
            track_layer_state=track_layer_state,
        )


def _apply_gaze_saccade_to_bind_slot(
    bind_slot,
    max_blend: float,
    horizontal: float,
    vertical: float,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    layer: str = "",
    track_layer_state: bool = True,
) -> None:
    for pose_bind in sort_pose_binds(bind_slot.pose_binds):
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            continue
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            continue
        bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
        offset = _gaze_offset_for_pose_axis(
            pose_bind.pose_axis, horizontal, vertical,
        )
        procedural = offset * pose_bind.weight
        _apply_layered_pose(
            bone,
            pose_bind.armature,
            pose_bind.pose_axis,
            procedural,
            frame=frame,
            base_cache=base_cache,
            insert_keyframes=insert_keyframes,
            keyframe_tracker=keyframe_tracker,
            layer=layer,
            track_layer_state=track_layer_state,
        )


def _apply_morph_amount_to_bind_slot(
    bind_slot,
    amount: float,
    max_blend: float,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    layer: str = "",
    track_layer_state: bool = True,
) -> None:
    morph_blend = max(0.0, min(1.0, amount)) * max_blend
    for bind in bind_slot.binds:
        if not bind.mesh or not bind.shape_key:
            continue
        kb = get_shape_key(bind.mesh, bind.shape_key)
        if kb is None:
            continue
        procedural_target = kb.slider_min + (bind.weight_value - kb.slider_min) * morph_blend
        _apply_layered_shape(
            kb,
            bind.mesh,
            procedural_target,
            frame=frame,
            base_cache=base_cache,
            insert_keyframes=insert_keyframes,
            keyframe_tracker=keyframe_tracker,
            layer=layer,
        )


def _motion_drive(
    phase_blend: float,
    morph_offset: float,
    max_blend: float,
    axis: str,
) -> float:
    if abs(phase_blend) > 1e-8:
        return phase_blend
    if abs(morph_offset) > 1e-8:
        if axis.startswith("ROT") or axis.startswith("LOC"):
            return morph_offset * max_blend
        return abs(morph_offset) * max_blend
    return 0.0


def _pose_bind_procedural_value(
    pose_bind,
    phase_blend: float,
    offset: float,
    morph_offset: float,
    max_blend: float,
    *,
    motion_amount_mode: bool,
) -> float:
    if motion_amount_mode:
        drive = _motion_drive(phase_blend, morph_offset, max_blend, pose_bind.pose_axis)
        return motion_pose_final_value(pose_bind, drive, offset=offset)

    if pose_bind.pose_axis.startswith("ROT") or pose_bind.pose_axis.startswith("LOC"):
        if abs(offset) > 1e-8:
            return offset * pose_bind.weight
        return phase_blend * pose_bind.weight
    return max(0.0, phase_blend * pose_bind.weight)


def _apply_phase_to_bind_slot(
    bind_slot,
    amount: float,
    max_blend: float,
    *,
    pose_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    morph_offset: float = 0.0,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    morph_only: bool = False,
    pose_only: bool = False,
    motion_amount_mode: bool = False,
    base_cache: Optional["BakeBaseCache"] = None,
    layer: str = "",
    track_layer_state: bool = True,
    apply_context=None,
) -> None:
    phase_blend = max(0.0, min(1.0, amount)) * max_blend

    if not pose_only:
        for bind in bind_slot.binds:
            if not bind.mesh or not bind.shape_key:
                continue
            kb = get_shape_key(bind.mesh, bind.shape_key)
            if kb is None:
                continue
            morph_blend = max(0.0, min(max_blend, phase_blend + morph_offset * max_blend))
            procedural_target = kb.slider_min + (bind.weight_value - kb.slider_min) * morph_blend
            _apply_layered_shape(
                kb,
                bind.mesh,
                procedural_target,
                frame=frame,
                base_cache=base_cache,
                insert_keyframes=insert_keyframes,
                keyframe_tracker=keyframe_tracker,
                layer=layer,
                track_layer_state=track_layer_state,
                apply_context=apply_context,
            )

    if not morph_only:
        for pose_bind in sort_pose_binds(bind_slot.pose_binds):
            if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
                continue
            if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
                continue
            bone = pose_bind.armature.pose.bones[pose_bind.pose_bone]
            axis_idx = _axis_index(pose_bind.pose_axis)
            offset = pose_offset[axis_idx] if axis_idx < len(pose_offset) else 0.0
            procedural = _pose_bind_procedural_value(
                pose_bind,
                phase_blend,
                offset,
                morph_offset,
                max_blend,
                motion_amount_mode=motion_amount_mode,
            )
            _apply_layered_pose(
                bone,
                pose_bind.armature,
                pose_bind.pose_axis,
                procedural,
                frame=frame,
                base_cache=base_cache,
                insert_keyframes=insert_keyframes,
                keyframe_tracker=keyframe_tracker,
                layer=layer,
                track_layer_state=track_layer_state,
            )


def apply_breathing_mapping(
    scene: bpy.types.Scene,
    phase: float,
    mapping,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    reset: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    pose_only: bool = False,
    track_layer_state: bool = True,
    apply_context=None,
) -> None:
    if not breathing_mapping_is_configured(mapping):
        return
    if reset:
        reset_breathing_mapping(mapping)
    max_blend = scene.blipsync.max_blend_value
    _apply_phase_to_bind_slot(
        mapping.targets,
        phase,
        max_blend,
        insert_keyframes=insert_keyframes,
        frame=frame,
        keyframe_tracker=keyframe_tracker,
        motion_amount_mode=True,
        base_cache=base_cache,
        layer=LAYER_BREATHING,
        pose_only=pose_only,
        track_layer_state=track_layer_state,
        apply_context=apply_context,
    )


def apply_micro_motion_mapping(
    scene: bpy.types.Scene,
    state: dict,
    mapping,
    *,
    insert_keyframes: bool = False,
    frame: Optional[int] = None,
    reset: bool = False,
    keyframe_tracker: Optional["BakeKeyframeTracker"] = None,
    base_cache: Optional["BakeBaseCache"] = None,
    pose_only: bool = False,
    track_layer_state: bool = True,
    apply_context=None,
) -> None:
    if not micro_motion_mapping_is_configured(mapping):
        return
    if reset:
        reset_micro_motion_mapping(mapping)

    max_blend = scene.blipsync.max_blend_value
    head_binds = state.get("head_binds", [])
    gaze_horizontal = float(state.get("gaze_bone_horizontal", 0.0))
    gaze_vertical = float(state.get("gaze_bone_vertical", 0.0))
    gaze_shape_weights = state.get("gaze_shape_weights", {})
    eyebrow_noise = float(state.get("eyebrow_noise", 0.0))
    mouth_noise = float(state.get("mouth_noise", 0.0))

    kw = dict(
        insert_keyframes=insert_keyframes,
        frame=frame,
        keyframe_tracker=keyframe_tracker,
        base_cache=base_cache,
        layer=LAYER_MICRO,
        track_layer_state=track_layer_state,
        apply_context=apply_context,
    )

    _apply_head_sway_to_bind_slot(mapping.head, head_binds, **kw)

    if mapping.gaze_control == "BONE":
        for eye_attr in ("left_eye", "right_eye"):
            _apply_gaze_saccade_to_bind_slot(
                getattr(mapping, eye_attr),
                max_blend,
                gaze_horizontal,
                gaze_vertical,
                **kw,
            )
    elif not pose_only:
        for attr, _label in MICRO_MOTION_GAZE_SHAPE_SLOTS:
            _apply_morph_amount_to_bind_slot(
                getattr(mapping, attr),
                float(gaze_shape_weights.get(attr, 0.0)),
                max_blend,
                **kw,
            )

    _apply_phase_to_bind_slot(
        mapping.eyebrows,
        0.0,
        max_blend,
        morph_offset=eyebrow_noise,
        motion_amount_mode=True,
        pose_only=pose_only,
        **kw,
    )
    _apply_phase_to_bind_slot(
        mapping.mouth_open,
        0.0,
        max_blend,
        morph_offset=mouth_noise,
        motion_amount_mode=True,
        pose_only=pose_only,
        **kw,
    )
