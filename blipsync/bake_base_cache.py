"""Snapshot pose/shape-key bases before layered procedural bake."""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

import bpy

from .blend_targets import get_shape_key, pose_axis_rest_value
from .keyframe_eval import try_eval_pose_axis_fcurve, try_eval_shape_key_fcurve
from .motion_layer_state import get_motion_layer_state, LAYER_BREATHING, LAYER_MICRO, reset_motion_layer_state
from .properties import MICRO_MOTION_ALL_SLOT_ATTRS

TrackKey = Tuple


class BakeBaseCache:
    """Per-frame base values captured before inserting procedural keyframes."""

    def __init__(self) -> None:
        self._shape: dict[TrackKey, float] = {}
        self._pose: dict[TrackKey, float] = {}

    @staticmethod
    def _shape_key(mesh: bpy.types.Object, shape_key_name: str, frame: int) -> TrackKey:
        return ("shape", int(mesh.as_pointer()) if mesh else 0, shape_key_name, frame)

    @staticmethod
    def _pose_key(armature: bpy.types.Object, bone_name: str, axis: str, frame: int) -> TrackKey:
        return ("pose", int(armature.as_pointer()) if armature else 0, bone_name, axis, frame)

    def has_shape_base(
        self,
        mesh: bpy.types.Object,
        shape_key_name: str,
        frame: int,
    ) -> bool:
        return self._shape_key(mesh, shape_key_name, frame) in self._shape

    def has_pose_base(
        self,
        armature: bpy.types.Object,
        bone_name: str,
        axis: str,
        frame: int,
    ) -> bool:
        return self._pose_key(armature, bone_name, axis, frame) in self._pose

    def _shape_bind_base(
        self,
        mesh: bpy.types.Object,
        shape_key_name: str,
        frame: int,
        *,
        layer: str = "",
    ) -> float:
        keyed = try_eval_shape_key_fcurve(mesh, shape_key_name, frame)
        if keyed is not None:
            return keyed
        kb = get_shape_key(mesh, shape_key_name)
        rest = float(kb.slider_min) if kb is not None else 0.0
        current = float(kb.value) if kb is not None else rest
        slot_key = get_motion_layer_state().shape_key(mesh, shape_key_name, layer)
        return get_motion_layer_state().resolve_base(
            slot_key, current, rest_fallback=rest,
        )

    def _pose_bind_base(
        self,
        armature: bpy.types.Object,
        bone_name: str,
        axis: str,
        frame: int,
        *,
        layer: str = "",
    ) -> float:
        keyed = try_eval_pose_axis_fcurve(armature, bone_name, axis, frame)
        if keyed is not None:
            return keyed
        bone = armature.pose.bones.get(bone_name)
        if bone is None:
            return 0.0
        from .blend_targets import get_pose_value

        rest = pose_axis_rest_value(axis)
        current = get_pose_value(bone, axis)
        slot_key = get_motion_layer_state().pose_key(armature, bone_name, axis, layer)
        return get_motion_layer_state().resolve_base(
            slot_key,
            current,
            rest_fallback=rest,
            rotation=axis.startswith("ROT"),
        )

    def _capture_shape_bind(self, bind, frame: int, *, layer: str = "") -> None:
        if not bind.mesh or not bind.shape_key:
            return
        kb = get_shape_key(bind.mesh, bind.shape_key)
        if kb is None:
            return
        key = self._shape_key(bind.mesh, bind.shape_key, frame)
        self._shape[key] = self._shape_bind_base(
            bind.mesh, bind.shape_key, frame, layer=layer,
        )

    def _capture_pose_bind(self, pose_bind, frame: int, *, layer: str = "") -> None:
        if not pose_bind.armature or pose_bind.armature.type != "ARMATURE":
            return
        if pose_bind.pose_bone not in pose_bind.armature.pose.bones:
            return
        key = self._pose_key(
            pose_bind.armature, pose_bind.pose_bone, pose_bind.pose_axis, frame,
        )
        self._pose[key] = self._pose_bind_base(
            pose_bind.armature,
            pose_bind.pose_bone,
            pose_bind.pose_axis,
            frame,
            layer=layer,
        )

    def _capture_pose_bind_live(self, pose_bind, frame: int, *, layer: str = "") -> None:
        """Pose base after other procedural layers this tick."""
        self._capture_pose_bind(pose_bind, frame, layer=layer)

    def _capture_shape_bind_live(self, bind, frame: int, *, layer: str = "") -> None:
        self._capture_shape_bind(bind, frame, layer=layer)

    def capture_bind_slot(self, bind_slot, frame: int, *, layer: str = "") -> None:
        for bind in bind_slot.binds:
            self._capture_shape_bind(bind, frame, layer=layer)
        for pose_bind in bind_slot.pose_binds:
            self._capture_pose_bind(pose_bind, frame, layer=layer)

    def capture_phoneme_mapping(self, mapping, frame: int) -> None:
        for expr in mapping.phoneme_exprs:
            for bind in expr.binds:
                self._capture_shape_bind(bind, frame)
            for pose_bind in expr.pose_binds:
                self._capture_pose_bind(pose_bind, frame)

    def capture_emotion_mapping(self, mapping, frame: int) -> None:
        for expr in mapping.emotion_exprs:
            for bind in expr.binds:
                self._capture_shape_bind(bind, frame)
            for pose_bind in expr.pose_binds:
                self._capture_pose_bind(pose_bind, frame)

    def capture_blink_mapping(self, mapping, frame: int) -> None:
        self.capture_bind_slot(mapping.left_eye, frame)
        self.capture_bind_slot(mapping.right_eye, frame)

    def capture_phoneme_mappings(self, mappings: Iterable, frame: int) -> None:
        for mapping in mappings:
            self.capture_phoneme_mapping(mapping, frame)

    def capture_emotion_mappings(self, mappings: Iterable, frame: int) -> None:
        for mapping in mappings:
            self.capture_emotion_mapping(mapping, frame)

    def capture_blink_mappings(self, mappings: Iterable, frame: int) -> None:
        for mapping in mappings:
            self.capture_blink_mapping(mapping, frame)

    def capture_breathing_mappings(self, mappings: Iterable, frame: int) -> None:
        for mapping in mappings:
            self.capture_bind_slot(mapping.targets, frame, layer=LAYER_BREATHING)

    def capture_micro_motion_mappings(self, mappings: Iterable, frame: int) -> None:
        for mapping in mappings:
            for attr in MICRO_MOTION_ALL_SLOT_ATTRS:
                self.capture_bind_slot(getattr(mapping, attr), frame)

    def capture_micro_motion_mappings_live(self, mappings: Iterable, frame: int) -> None:
        """Micro-motion bases from the current pose (after lip/breathing this tick)."""
        for mapping in mappings:
            for attr in MICRO_MOTION_ALL_SLOT_ATTRS:
                self.capture_bind_slot(getattr(mapping, attr), frame, layer=LAYER_MICRO)

    def shape_base(
        self,
        mesh: bpy.types.Object,
        shape_key_name: str,
        frame: int,
        *,
        fallback: float,
    ) -> float:
        key = self._shape_key(mesh, shape_key_name, frame)
        return self._shape.get(key, fallback)

    def pose_base(
        self,
        armature: bpy.types.Object,
        bone_name: str,
        axis: str,
        frame: int,
        *,
        fallback: float,
    ) -> float:
        key = self._pose_key(armature, bone_name, axis, frame)
        return self._pose.get(key, fallback)


def capture_additive_bake_bases(
    scene: bpy.types.Scene,
    frames: Iterable[int],
    *,
    phoneme_mappings: Optional[Iterable] = None,
    emotion_mappings: Optional[Iterable] = None,
    blink_mappings: Optional[Iterable] = None,
    breathing_mappings: Optional[Iterable] = None,
    micro_motion_mappings: Optional[Iterable] = None,
) -> BakeBaseCache:
    """Evaluate existing animation at each frame and store bind bases."""
    reset_motion_layer_state()
    cache = BakeBaseCache()
    phoneme_mappings = list(phoneme_mappings or ())
    emotion_mappings = list(emotion_mappings or ())
    blink_mappings = list(blink_mappings or ())
    breathing_mappings = list(breathing_mappings or ())
    micro_motion_mappings = list(micro_motion_mappings or ())
    if not any((
        phoneme_mappings,
        emotion_mappings,
        blink_mappings,
        breathing_mappings,
        micro_motion_mappings,
    )):
        return cache

    # FCurve evaluation only — do not scene.frame_set() here. frame_set during bake
    # would fire frame_change_post and re-run lip/emotion/blink/motion per frame.
    for frame in frames:
        if phoneme_mappings:
            cache.capture_phoneme_mappings(phoneme_mappings, frame)
        if emotion_mappings:
            cache.capture_emotion_mappings(emotion_mappings, frame)
        if blink_mappings:
            cache.capture_blink_mappings(blink_mappings, frame)
        if breathing_mappings:
            cache.capture_breathing_mappings(breathing_mappings, frame)
        if micro_motion_mappings:
            cache.capture_micro_motion_mappings(micro_motion_mappings, frame)

    return cache
