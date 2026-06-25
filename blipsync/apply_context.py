"""Apply-path context for viewport vs render (RNA vs DNA-silent overlay)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import bpy

RENDER_APPLY_OVERLAY = "OVERLAY"
RENDER_APPLY_RNA = "RNA"


@dataclass(frozen=True)
class ApplyContext:
    """Controls how shape/pose values are written during a tick."""

    render_apply_mode: str = RENDER_APPLY_RNA
    rendering: bool = False

    def uses_overlay(self) -> bool:
        return self.rendering and self.render_apply_mode == RENDER_APPLY_OVERLAY

    def shape_write_silent(self) -> bool:
        return False

    def track_layer_state(self) -> bool:
        """Overlay render uses RNA writes; layer bookkeeping stays enabled."""
        return True


def resolve_apply_context(settings, *, rendering: bool) -> ApplyContext:
    mode = getattr(settings, "render_apply_mode", RENDER_APPLY_OVERLAY)
    if mode not in (RENDER_APPLY_OVERLAY, RENDER_APPLY_RNA):
        mode = RENDER_APPLY_OVERLAY
    return ApplyContext(render_apply_mode=mode, rendering=rendering)


def uses_overlay_render(settings) -> bool:
    return (
        bool(getattr(settings, "realtime_during_render", False))
        and getattr(settings, "render_apply_mode", RENDER_APPLY_OVERLAY) == RENDER_APPLY_OVERLAY
    )


_LOCK_SAVED: dict[int, bool] = {}


def begin_overlay_render_session(scene: bpy.types.Scene) -> None:
    """Lock UI during render to avoid viewport / notifier races (Blender docs)."""
    scene_key = int(scene.as_pointer())
    if scene_key not in _LOCK_SAVED:
        _LOCK_SAVED[scene_key] = bool(scene.render.use_lock_interface)
    scene.render.use_lock_interface = True


def end_overlay_render_session(scene: bpy.types.Scene) -> None:
    from .dna_apply import flush_touched_shape_keys_to_rna

    flush_touched_shape_keys_to_rna()
    scene_key = int(scene.as_pointer())
    if scene_key in _LOCK_SAVED:
        scene.render.use_lock_interface = _LOCK_SAVED.pop(scene_key)


def merge_apply_context(apply_kw: dict, apply_context: Optional[ApplyContext]) -> dict:
    if apply_context is None:
        return apply_kw
    merged = dict(apply_kw)
    merged["apply_context"] = apply_context
    if not apply_context.track_layer_state():
        merged["track_layer_state"] = False
    return merged
