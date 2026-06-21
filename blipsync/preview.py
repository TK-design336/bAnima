"""Editor preview for individual mapping slots (ignored during playback)."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .bake_base_cache import BakeBaseCache

from .applicator import apply_weights
from .blink_applicator import _apply_eye_slot
from .blink_engine import scene_time_at_frame
from .emotion_applicator import apply_emotion_weights
from .micro_motion_engine import compute_micro_motion_state
from .motion_applicator import (
    _apply_gaze_saccade_to_bind_slot,
    _apply_head_sway_to_bind_slot,
    _apply_morph_amount_to_bind_slot,
    _apply_phase_to_bind_slot,
)
from .properties import MICRO_MOTION_GAZE_SHAPE_SLOTS
from .tick_base_cache import capture_scene_preview_bases


def _tag_redraw_3d(context) -> None:
    if context is None or getattr(context, "screen", None) is None:
        return
    for window in context.window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def on_preview_amount_changed(context) -> None:
    if context is None:
        return
    from .handlers import _is_playing, _tick_scene

    if _is_playing():
        return
    scene = context.scene
    scene.frame_set(scene.frame_current)
    _tick_scene(scene, playing=False)
    _tag_redraw_3d(context)


def apply_scene_previews(
    scene: bpy.types.Scene,
    *,
    base_cache: Optional["BakeBaseCache"] = None,
    frame: Optional[int] = None,
) -> None:
    if not getattr(scene, "blipsync", None):
        return
    settings = scene.blipsync
    max_blend = settings.max_blend_value
    if frame is None:
        frame = scene.frame_current
    if base_cache is None:
        base_cache = capture_scene_preview_bases(scene, settings, frame)
    apply_kw = dict(base_cache=base_cache, frame=frame)

    for mapping in settings.phoneme_mappings:
        weights = {"__volume__": 1.0}
        has_preview = False
        for expr in mapping.phoneme_exprs:
            amount = float(expr.preview_amount)
            if amount > 1e-8:
                weights[expr.label] = amount
                has_preview = True
        if not has_preview:
            continue
        apply_weights(
            scene,
            weights,
            mapping,
            only_labels=set(weights.keys()) - {"__volume__"},
            **apply_kw,
        )

    for mapping in settings.emotion_mappings:
        weights = {}
        has_preview = False
        for expr in mapping.emotion_exprs:
            amount = float(expr.preview_amount)
            if amount > 1e-8:
                weights[expr.label] = amount
                has_preview = True
        if not has_preview:
            continue
        apply_emotion_weights(
            scene,
            weights,
            mapping,
            only_labels=set(weights.keys()),
            **apply_kw,
        )

    for mapping in settings.blink_mappings:
        for eye_slot in (mapping.left_eye, mapping.right_eye):
            amount = float(eye_slot.preview_amount)
            if amount <= 1e-8:
                continue
            _apply_eye_slot(eye_slot, amount, max_blend, **apply_kw)

    for mapping in settings.breathing_mappings:
        slot = mapping.targets
        amount = float(slot.preview_amount)
        if amount <= 1e-8:
            continue
        _apply_phase_to_bind_slot(
            slot,
            amount,
            max_blend,
            motion_amount_mode=True,
            **apply_kw,
        )

    time_sec = scene_time_at_frame(scene, frame)
    gaze_shape_attrs = {attr for attr, _label in MICRO_MOTION_GAZE_SHAPE_SLOTS}

    for mapping in settings.micro_motion_mappings:
        state = compute_micro_motion_state(
            time_sec, mapping, scene, settings,
        )
        head_binds = state.get("head_binds", [])
        gaze_h = float(state.get("gaze_bone_horizontal", 0.0))
        gaze_v = float(state.get("gaze_bone_vertical", 0.0))
        gaze_shapes = state.get("gaze_shape_weights", {})
        eyebrow_noise = float(state.get("eyebrow_noise", 0.0))
        mouth_noise = float(state.get("mouth_noise", 0.0))

        slots = (
            ("head", mapping.head),
            ("left_eye", mapping.left_eye),
            ("right_eye", mapping.right_eye),
            ("look_up", mapping.look_up),
            ("look_down", mapping.look_down),
            ("look_left", mapping.look_left),
            ("look_right", mapping.look_right),
            ("eyebrows", mapping.eyebrows),
            ("mouth_open", mapping.mouth_open),
        )
        for attr, slot in slots:
            amount = float(slot.preview_amount)
            if amount <= 1e-8:
                continue

            if attr == "head":
                scaled = [v * amount for v in head_binds]
                _apply_head_sway_to_bind_slot(slot, scaled, **apply_kw)
            elif attr in ("left_eye", "right_eye") and mapping.gaze_control == "BONE":
                _apply_gaze_saccade_to_bind_slot(
                    slot, max_blend, gaze_h * amount, gaze_v * amount, **apply_kw,
                )
            elif attr in gaze_shape_attrs and mapping.gaze_control == "SHAPE_KEY":
                _apply_morph_amount_to_bind_slot(
                    slot, float(gaze_shapes.get(attr, 0.0)) * amount, max_blend, **apply_kw,
                )
            elif attr == "eyebrows":
                _apply_phase_to_bind_slot(
                    slot, 0.0, max_blend,
                    morph_offset=eyebrow_noise * amount,
                    motion_amount_mode=True,
                    **apply_kw,
                )
            elif attr == "mouth_open":
                _apply_phase_to_bind_slot(
                    slot, 0.0, max_blend,
                    morph_offset=mouth_noise * amount,
                    motion_amount_mode=True,
                    **apply_kw,
                )
