"""Sparse keyframe insertion during bake (skip sustained rest values)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import bpy

from .blend_targets import (
    pose_axis_array_index,
    pose_axis_rest_value,
    pose_data_path,
    set_pose_value,
)

TrackKey = Tuple[Any, ...]
State = Dict[str, Optional[float]]

_REST_EPSILON = 1e-5
_CHANGE_EPSILON = 1e-5


class BakeKeyframeTracker:
    """Insert shape-key / pose keys only around rest regions and value changes."""

    def __init__(self, *, step: int = 1, start_frame: int = 1) -> None:
        self.step = max(1, step)
        self.start_frame = start_frame
        self._states: Dict[TrackKey, State] = {}

    def _state(self, key: TrackKey) -> State:
        if key not in self._states:
            self._states[key] = {"last_sampled": None, "last_keyframed": None}
        return self._states[key]

    @staticmethod
    def shape_key_key(mesh: bpy.types.Object, shape_key_name: str) -> TrackKey:
        return ("shape", int(mesh.as_pointer()) if mesh else 0, shape_key_name)

    @staticmethod
    def pose_key(armature: bpy.types.Object, bone_name: str, axis: str) -> TrackKey:
        return ("pose", int(armature.as_pointer()) if armature else 0, bone_name, axis)

    def maybe_shape_key(
        self,
        kb,
        mesh: bpy.types.Object,
        frame: int,
        value: float,
        *,
        rest_value: Optional[float] = None,
    ) -> None:
        if rest_value is None:
            rest_value = float(kb.slider_min)
        state = self._state(self.shape_key_key(mesh, kb.name))
        self._maybe_value_keyframe(
            state,
            frame,
            float(value),
            rest_value,
            insert=lambda f, v: self._insert_shape_key(kb, f, v),
        )

    def maybe_pose_axis(
        self,
        bone,
        armature: bpy.types.Object,
        axis: str,
        frame: int,
        value: float,
        *,
        rest_value: Optional[float] = None,
    ) -> None:
        if rest_value is None:
            rest_value = pose_axis_rest_value(axis)
        state = self._state(self.pose_key(armature, bone.name, axis))
        self._maybe_value_keyframe(
            state,
            frame,
            float(value),
            rest_value,
            insert=lambda f, v: self._insert_pose_axis(bone, axis, f, v),
        )

    def _maybe_value_keyframe(
        self,
        state: State,
        frame: int,
        value: float,
        rest_value: float,
        *,
        insert,
    ) -> None:
        at_rest = abs(value - rest_value) <= _REST_EPSILON
        prev = state["last_sampled"]
        prev_at_rest = prev is None or abs(prev - rest_value) <= _REST_EPSILON

        if prev is not None and prev_at_rest and not at_rest:
            pre_frame = max(self.start_frame, frame - self.step)
            insert(pre_frame, rest_value)
            state["last_keyframed"] = rest_value

        if at_rest:
            if prev is not None and not prev_at_rest:
                insert(frame, value)
                state["last_keyframed"] = value
        else:
            last_keyframed = state["last_keyframed"]
            if last_keyframed is None or abs(value - last_keyframed) > _CHANGE_EPSILON:
                insert(frame, value)
                state["last_keyframed"] = value

        state["last_sampled"] = value

    @staticmethod
    def _insert_shape_key(kb, frame: int, value: float) -> None:
        kb.value = value
        kb.keyframe_insert(data_path="value", frame=frame)

    @staticmethod
    def _insert_pose_axis(bone, axis: str, frame: int, value: float) -> None:
        set_pose_value(bone, axis, value)
        bone.keyframe_insert(
            data_path=pose_data_path(axis),
            index=pose_axis_array_index(axis),
            frame=frame,
        )
