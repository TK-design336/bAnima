"""Track procedural offsets so layered motion does not accumulate each frame."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

TrackKey = Tuple

LAYER_DEFAULT = ""
LAYER_PHONEME = "phoneme"
LAYER_EMOTION = "emotion"
LAYER_BLINK = "blink"
LAYER_BREATHING = "breathing"
LAYER_MICRO = "micro"
_EPSILON = 1e-5
_EPSILON_ROT = 1e-4


def _match_epsilon(current: float, reference: float, *, rotation: bool = False) -> float:
    tol = _EPSILON_ROT if rotation else _EPSILON
    return max(tol, abs(reference) * 1e-6)


@dataclass
class _LayerEntry:
    last_delta: float = 0.0
    last_written: Optional[float] = None
    last_base: Optional[float] = None


class MotionLayerState:
    """Per-target state for additive procedural layers (realtime only)."""

    def __init__(self) -> None:
        self._entries: Dict[TrackKey, _LayerEntry] = {}

    def clear(self) -> None:
        self._entries.clear()

    @staticmethod
    def pose_key(armature, bone_name: str, axis: str, layer: str = LAYER_DEFAULT) -> TrackKey:
        return ("pose", armature, bone_name, axis, layer)

    @staticmethod
    def shape_key(mesh, shape_key_name: str, layer: str = LAYER_DEFAULT) -> TrackKey:
        return ("shape", mesh, shape_key_name, layer)

    def tracked_shape_delta(self, mesh, shape_key_name: str) -> float:
        mesh_ptr = int(mesh.as_pointer()) if mesh else 0
        total = 0.0
        for key, entry in self._entries.items():
            if key[0] != "shape":
                continue
            key_mesh = key[1]
            key_ptr = int(key_mesh.as_pointer()) if key_mesh else 0
            if key_ptr != mesh_ptr or key[2] != shape_key_name:
                continue
            if entry.last_written is not None:
                total += entry.last_delta
        return total

    def tracked_pose_delta(self, armature, bone_name: str, axis: str) -> float:
        arm_ptr = int(armature.as_pointer()) if armature else 0
        total = 0.0
        for key, entry in self._entries.items():
            if key[0] != "pose":
                continue
            key_arm = key[1]
            key_ptr = int(key_arm.as_pointer()) if key_arm else 0
            if key_ptr != arm_ptr or key[2] != bone_name or key[3] != axis:
                continue
            if entry.last_written is not None:
                total += entry.last_delta
        return total

    def revert_all(self) -> None:
        """Restore bases by removing all procedural layer deltas (e.g. on playback stop)."""
        from collections import defaultdict

        from .blend_targets import get_pose_value, get_shape_key, set_pose_value

        pose_groups: dict[tuple, list[_LayerEntry]] = defaultdict(list)
        shape_groups: dict[tuple, list[_LayerEntry]] = defaultdict(list)

        for key, entry in list(self._entries.items()):
            if entry.last_written is None:
                continue
            kind = key[0]
            if kind == "shape":
                shape_groups[(key[1], key[2])].append(entry)
            elif kind == "pose":
                pose_groups[(key[1], key[2], key[3])].append(entry)

        for (mesh, shape_name), entries in shape_groups.items():
            try:
                if mesh is None or getattr(mesh, "type", None) != "MESH":
                    continue
                kb = get_shape_key(mesh, shape_name)
                if kb is None:
                    continue
                current = float(kb.value)
                kb.value = current - sum(entry.last_delta for entry in entries)
            except ReferenceError:
                continue

        for (armature, bone_name, axis), entries in pose_groups.items():
            try:
                if armature is None or getattr(armature, "type", None) != "ARMATURE":
                    continue
                bone = armature.pose.bones.get(bone_name)
                if bone is None:
                    continue
                current = get_pose_value(bone, axis)
                set_pose_value(bone, axis, current - sum(entry.last_delta for entry in entries))
            except ReferenceError:
                continue

        self.clear()

    def resolve_base(
        self,
        key: TrackKey,
        current: float,
        *,
        rest_fallback: float,
        cached_base: Optional[float] = None,
        rotation: bool = False,
    ) -> float:
        if cached_base is not None:
            return cached_base

        entry = self._entries.get(key)
        if entry is None or entry.last_written is None or entry.last_base is None:
            return rest_fallback

        eps = _match_epsilon(current, entry.last_written, rotation=rotation)
        if abs(current - entry.last_written) <= eps:
            # Cancelled writes store last_written at animation rest (often 0) while
            # last_base was poisoned negative; never reuse that base on the next frame.
            rest_eps = _match_epsilon(entry.last_written, rest_fallback, rotation=rotation)
            if abs(entry.last_written - rest_fallback) <= rest_eps:
                return rest_fallback
            return entry.last_base

        stripped = current - entry.last_delta
        if abs(stripped - entry.last_base) <= eps:
            return entry.last_base

        # External pose edit (transforms clear, undo, etc.) — drop stale bookkeeping.
        entry.last_delta = 0.0
        entry.last_written = None
        entry.last_base = None
        return current

    def capture_base(
        self,
        key: TrackKey,
        current: float,
        *,
        rest_fallback: float,
        rotation: bool = False,
    ) -> float:
        """Strip a prior procedural write when tracked; else use evaluated current."""
        entry = self._entries.get(key)
        if entry is None or entry.last_written is None or entry.last_base is None:
            return current
        return self.resolve_base(
            key, current, rest_fallback=rest_fallback, rotation=rotation,
        )

    def commit(
        self,
        key: TrackKey,
        delta: float,
        final: float,
        base: float,
    ) -> None:
        entry = self._entries.setdefault(key, _LayerEntry())
        entry.last_delta = delta
        entry.last_written = final
        entry.last_base = base


_motion_layer_state = MotionLayerState()


def get_motion_layer_state() -> MotionLayerState:
    return _motion_layer_state


def reset_motion_layer_state() -> None:
    _motion_layer_state.clear()


def invalidate_motion_overlay_state() -> None:
    """Drop layer bookkeeping without touching pose/shape values."""
    reset_motion_layer_state()


def motion_layers_out_of_sync() -> bool:
    """True when depsgraph reset dropped a procedural write we still track."""
    from .blend_targets import get_pose_value, get_shape_key

    for key, entry in _motion_layer_state._entries.items():
        if entry.last_written is None:
            continue
        try:
            if key[0] == "shape":
                mesh, shape_name = key[1], key[2]
                if mesh is None or getattr(mesh, "type", None) != "MESH":
                    continue
                kb = get_shape_key(mesh, shape_name)
                if kb is None:
                    continue
                current = float(kb.value)
                rotation = False
            elif key[0] == "pose":
                armature, bone_name, axis = key[1], key[2], key[3]
                if armature is None or getattr(armature, "type", None) != "ARMATURE":
                    continue
                bone = armature.pose.bones.get(bone_name)
                if bone is None:
                    continue
                current = get_pose_value(bone, axis)
                rotation = axis.startswith("ROT")
            else:
                continue
            eps = _match_epsilon(current, entry.last_written, rotation=rotation)
            if abs(current - entry.last_written) > eps:
                return True
        except ReferenceError:
            continue
    return False


def revert_motion_layer_state() -> None:
    _motion_layer_state.revert_all()
