"""Per-tick keyframe-only bases (snapshot after Blender evaluates the current frame)."""

from __future__ import annotations

from typing import Iterable, Optional

import bpy

from .bake_base_cache import BakeBaseCache
from .defaults import (
    blink_is_configured,
    blink_mapping_is_configured,
    breathing_is_configured,
    breathing_mapping_is_configured,
    get_channel_emotion_mapping,
    get_channel_mapping,
    micro_motion_is_configured,
    micro_motion_mapping_is_configured,
)


def _unique_mappings(mappings: Iterable) -> list:
    seen: set[int] = set()
    out = []
    for mapping in mappings:
        key = id(mapping)
        if key in seen:
            continue
        seen.add(key)
        out.append(mapping)
    return out


def capture_tick_keyframe_bases(
    scene: bpy.types.Scene,
    settings,
    frame: int,
    *,
    channel_targets: Optional[Iterable] = None,
    include_lip: bool = False,
    include_emotion: bool = False,
    include_blink: bool = False,
    include_breathing: bool = False,
    include_micro_motion: bool = False,
    include_all_phoneme_mappings: bool = False,
    include_all_emotion_mappings: bool = False,
    include_all_blink_mappings: bool = False,
    include_all_breathing_mappings: bool = False,
    include_all_micro_motion_mappings: bool = False,
    refresh_frame: bool = False,
    prefer_rest_for_uncached_emotion_layer: bool = False,
) -> BakeBaseCache:
    """Snapshot bind bases for the current frame.

    Must NOT call scene.frame_set() from frame_change handlers (infinite recursion).
    During playback/scrub, bases come from FCurve evaluation or from stripping the
    Pass refresh_frame=True only outside frame_change handlers (e.g. preview slider).
    """
    if refresh_frame:
        from .handlers import handler_tick_active

        if not handler_tick_active():
            scene.frame_set(frame)
    cache = BakeBaseCache()

    phoneme_mappings = []
    emotion_mappings = []
    if channel_targets:
        for target in channel_targets:
            if include_lip:
                mapping = get_channel_mapping(settings, target)
                if mapping is not None:
                    phoneme_mappings.append(mapping)
            if include_emotion:
                emotion_mapping = get_channel_emotion_mapping(settings, target)
                if emotion_mapping is not None:
                    emotion_mappings.append(emotion_mapping)

    if include_all_phoneme_mappings:
        phoneme_mappings.extend(settings.phoneme_mappings)
    if include_all_emotion_mappings:
        emotion_mappings.extend(settings.emotion_mappings)

    phoneme_mappings = _unique_mappings(phoneme_mappings)
    emotion_mappings = _unique_mappings(emotion_mappings)

    if phoneme_mappings:
        cache.capture_phoneme_mappings(phoneme_mappings, frame)
    if emotion_mappings:
        cache.capture_emotion_mappings(
            emotion_mappings,
            frame,
            prefer_rest_for_uncached_layer=prefer_rest_for_uncached_emotion_layer,
        )

    if include_blink or include_all_blink_mappings:
        blink_mappings = [
            m for m in settings.blink_mappings if blink_mapping_is_configured(m)
        ] if include_all_blink_mappings or (include_blink and blink_is_configured(settings)) else []
        if blink_mappings:
            cache.capture_blink_mappings(blink_mappings, frame)

    if include_breathing or include_all_breathing_mappings:
        breathing_mappings = [
            m for m in settings.breathing_mappings if breathing_mapping_is_configured(m)
        ] if include_all_breathing_mappings or (include_breathing and breathing_is_configured(settings)) else []
        if breathing_mappings:
            cache.capture_breathing_mappings(breathing_mappings, frame)

    if include_micro_motion or include_all_micro_motion_mappings:
        micro_mappings = [
            m for m in settings.micro_motion_mappings if micro_motion_mapping_is_configured(m)
        ] if include_all_micro_motion_mappings or (include_micro_motion and micro_motion_is_configured(settings)) else []
        if micro_mappings:
            cache.capture_micro_motion_mappings(micro_mappings, frame)

    return cache


def capture_scene_preview_bases(
    scene: bpy.types.Scene,
    settings,
    frame: int,
    *,
    refresh_frame: bool = True,
) -> BakeBaseCache:
    """Keyframe bases for editor preview sliders (all mapping slots)."""
    return capture_tick_keyframe_bases(
        scene,
        settings,
        frame,
        include_all_phoneme_mappings=bool(settings.phoneme_mappings),
        include_all_emotion_mappings=bool(settings.emotion_mappings),
        include_all_blink_mappings=True,
        include_all_breathing_mappings=True,
        include_all_micro_motion_mappings=True,
        refresh_frame=refresh_frame,
    )
