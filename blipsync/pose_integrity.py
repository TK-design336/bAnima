"""Keep procedural motion bookkeeping in sync with external pose edits."""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from .micro_motion_engine import reset_head_smoothing
from .motion_layer_state import invalidate_motion_overlay_state

_OP_EXECUTE_PATCHES: list[tuple[type, object]] = []


def _invalidate_before_pose_edit() -> None:
    invalidate_motion_overlay_state()
    reset_head_smoothing()


def _patch_operator_execute(op_cls: type) -> None:
    if op_cls is None:
        return
    original = op_cls.execute
    if getattr(original, "_blipsync_pose_integrity_wrapped", False):
        return

    def execute(self, context):
        _invalidate_before_pose_edit()
        return original(self, context)

    execute._blipsync_pose_integrity_wrapped = True  # type: ignore[attr-defined]
    op_cls.execute = execute
    _OP_EXECUTE_PATCHES.append((op_cls, original))


def _restore_operator_patches() -> None:
    for op_cls, original in _OP_EXECUTE_PATCHES:
        op_cls.execute = original
    _OP_EXECUTE_PATCHES.clear()


def _patch_pose_operators() -> None:
    for attr in (
        "POSE_OT_transforms_clear",
        "OBJECT_OT_posemode_toggle",
        "ARMATURE_OT_posemode_toggle",
    ):
        _patch_operator_execute(getattr(bpy.types, attr, None))


@persistent
def save_pre(_dummy) -> None:
    _invalidate_before_pose_edit()


@persistent
def undo_post(_dummy) -> None:
    _invalidate_before_pose_edit()


@persistent
def redo_post(_dummy) -> None:
    _invalidate_before_pose_edit()


def register_pose_integrity() -> None:
    _patch_pose_operators()

    if save_pre not in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.append(save_pre)
    if undo_post not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(undo_post)
    if redo_post not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(redo_post)


def unregister_pose_integrity() -> None:
    _restore_operator_patches()

    if save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(save_pre)
    if undo_post in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(undo_post)
    if redo_post in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(redo_post)
