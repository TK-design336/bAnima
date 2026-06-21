"""Playback-driven lip sync and emotion sync handlers."""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent

from .applicator import apply_weights
from .defaults import (
    check_emotion_configured,
    check_scene_configured,
    ensure_scene_defaults,
    get_channel_emotion_mapping,
    get_channel_mapping,
    resolve_enabled_channel_targets,
)
from .blink_applicator import apply_blink_mapping
from .blink_engine import (
    blink_seed,
    compute_blink_amount,
    compute_blink_eyelid_jitters,
    scene_time_at_frame,
)
from .breathing_engine import compute_breath_phase
from .defaults import (
    blink_is_configured,
    blink_mapping_is_configured,
    breathing_is_configured,
    breathing_mapping_is_configured,
    micro_motion_is_configured,
    micro_motion_mapping_is_configured,
)
from .micro_motion_engine import compute_micro_motion_state, reset_head_smoothing
from .motion_layer_state import (
    reset_motion_layer_state,
    revert_motion_layer_state,
)
from .motion_applicator import (
    apply_breathing_mapping,
    apply_micro_motion_mapping,
)
from .tick_base_cache import capture_tick_keyframe_bases
from .emotion_applicator import apply_emotion_weights
from .emotion_engine import get_emotion_engine
from .engine import get_engine

_LAST_FRAME = None
_WAS_PLAYING = False
_WAS_RENDERING = False
_HANDLER_TICK_DEPTH = 0
_REFRESH_TIMER = None
_LAST_TICK_FRAME_BY_SCENE: dict[int, int] = {}
_LAST_PAUSED_FRAME_BY_SCENE: dict[int, int] = {}


def handler_tick_active() -> bool:
    return _HANDLER_TICK_DEPTH > 0


def _is_playing() -> bool:
    for window in bpy.context.window_manager.windows:
        if window.screen.is_animation_playing:
            return True
    return False


def _is_rendering() -> bool:
    """Animation / preview render in progress."""
    is_job_running = getattr(bpy.app, "is_job_running", None)
    if callable(is_job_running):
        if is_job_running("RENDER") or is_job_running("RENDER_PREVIEW"):
            return True
    return bool(getattr(bpy.app, "is_rendering", False))


def _scene_fps(scene: bpy.types.Scene) -> float:
    return scene.render.fps / scene.render.fps_base


def _update_lip_debug_display(scene: bpy.types.Scene, channel_target, result) -> None:
    settings = scene.blipsync
    settings.debug_channel = channel_target.channel
    settings.debug_phoneme = result.phoneme
    settings.debug_raw_phoneme = result.raw_phoneme
    settings.debug_volume = result.volume


def _update_emotion_debug_display(scene: bpy.types.Scene, result) -> None:
    settings = scene.blipsync
    settings.debug_emotion = result.dominant
    settings.debug_emotion_happy = result.happy
    settings.debug_emotion_sad = result.sad
    settings.debug_emotion_angry = result.angry
    settings.debug_emotion_neutral = result.neutral


def _schedule_animation_refresh() -> None:
    """Re-evaluate keyframes outside handlers (safe to call frame_set)."""
    global _REFRESH_TIMER

    def _refresh(_dummy=None):
        global _REFRESH_TIMER
        _REFRESH_TIMER = None
        for scene in _iter_scenes():
            try:
                scene.frame_set(scene.frame_current)
            except Exception:
                pass
        return None

    if _REFRESH_TIMER is not None:
        try:
            bpy.app.timers.unregister(_REFRESH_TIMER)
        except Exception:
            pass
    _REFRESH_TIMER = bpy.app.timers.register(_refresh, first_interval=0.0)


def _reset_tick_state(scene: bpy.types.Scene) -> None:
    get_engine().reset_smoothing()
    get_emotion_engine().reset_smoothing()
    reset_head_smoothing()
    reset_motion_layer_state()
    global _LAST_FRAME
    _LAST_FRAME = None
    scene_key = int(scene.as_pointer())
    _LAST_TICK_FRAME_BY_SCENE.pop(scene_key, None)
    _LAST_PAUSED_FRAME_BY_SCENE.pop(scene_key, None)


def _tick_scene(scene: bpy.types.Scene, *, playing: bool, rendering: bool = False) -> None:
    global _LAST_FRAME

    ensure_scene_defaults(scene)
    settings = scene.blipsync
    lip_ok, _lip_msg = check_scene_configured(scene) if settings.enabled else (True, "")
    emotion_ok, _emotion_msg = check_emotion_configured(scene) if settings.emotion_enabled else (True, "")
    procedural_active = (
        (settings.blink_enabled and blink_is_configured(settings))
        or (settings.breathing_enabled and breathing_is_configured(settings))
        or (settings.micro_motion_enabled and micro_motion_is_configured(settings))
    )
    can_run_lip = settings.enabled and lip_ok
    can_run_emotion = settings.emotion_enabled and emotion_ok
    if not can_run_lip and not can_run_emotion and not procedural_active:
        return

    lip_engine = get_engine()
    emotion_engine = get_emotion_engine()
    targets = resolve_enabled_channel_targets(settings)
    lip_or_emotion = can_run_lip or can_run_emotion
    frame = scene.frame_current
    scene_key = int(scene.as_pointer())

    if playing:
        if _LAST_TICK_FRAME_BY_SCENE.get(scene_key) == frame:
            return
        _LAST_TICK_FRAME_BY_SCENE[scene_key] = frame
    else:
        last_paused = _LAST_PAUSED_FRAME_BY_SCENE.get(scene_key)
        if last_paused is not None and last_paused != frame:
            reset_motion_layer_state()
            reset_head_smoothing()
        _LAST_PAUSED_FRAME_BY_SCENE[scene_key] = frame

    if not playing:
        lip_engine.reset_smoothing()
        emotion_engine.reset_smoothing()
        dt = 1.0 / _scene_fps(scene)
    elif _LAST_FRAME is None:
        dt = 1.0 / _scene_fps(scene)
    else:
        if frame < _LAST_FRAME:
            reset_motion_layer_state()
            reset_head_smoothing()
        dt = abs(frame - _LAST_FRAME) / _scene_fps(scene)
        dt = min(dt, 2.0 / _scene_fps(scene))
        dt = max(dt, 1.0 / 120.0)
    _LAST_FRAME = frame

    live_cache = capture_tick_keyframe_bases(
        scene,
        settings,
        frame,
        channel_targets=targets if lip_or_emotion else None,
        include_lip=can_run_lip,
        include_emotion=can_run_emotion,
        include_blink=settings.blink_enabled and blink_is_configured(settings),
        include_breathing=settings.breathing_enabled and breathing_is_configured(settings),
        include_micro_motion=False,
    )
    apply_kw = dict(base_cache=live_cache, frame=frame)

    if lip_or_emotion:
        if not targets:
            if not (settings.blink_enabled and blink_is_configured(settings)):
                if not (settings.breathing_enabled and breathing_is_configured(settings)):
                    if not (settings.micro_motion_enabled and micro_motion_is_configured(settings)):
                        return
        else:
            phoneme_mappings = []
            emotion_mappings = []
            for target in targets:
                if can_run_lip:
                    mapping = get_channel_mapping(settings, target)
                    if mapping is not None:
                        phoneme_mappings.append(mapping)
                if can_run_emotion:
                    emotion_mapping = get_channel_emotion_mapping(settings, target)
                    if emotion_mapping is not None:
                        emotion_mappings.append(emotion_mapping)

            debug_target = targets[min(settings.channel_targets_index, len(targets) - 1)]
            for target in targets:
                if can_run_lip:
                    mapping = get_channel_mapping(settings, target)
                    if mapping is not None:
                        result = lip_engine.analyze_channel(scene, frame, target)
                        weights = lip_engine.update_smoothed_weights(
                            scene, result, dt, target.channel, mapping,
                        )
                        apply_weights(scene, weights, mapping, **apply_kw)
                        if target == debug_target and not rendering:
                            _update_lip_debug_display(scene, target, result)

                if can_run_emotion:
                    emotion_mapping = get_channel_emotion_mapping(settings, target)
                    if emotion_mapping is not None:
                        emotion_result = emotion_engine.analyze_channel(scene, frame, target)
                        emotion_weights = emotion_engine.update_smoothed_weights(
                            scene, emotion_result, dt, target.channel, emotion_mapping,
                        )
                        apply_emotion_weights(scene, emotion_weights, emotion_mapping, **apply_kw)
                        if target == debug_target and not rendering:
                            _update_emotion_debug_display(scene, emotion_result)

    if settings.blink_enabled and blink_is_configured(settings):
        blink_mappings = [
            mapping for mapping in settings.blink_mappings if blink_mapping_is_configured(mapping)
        ]
        if blink_mappings:
            time_sec = scene_time_at_frame(scene, frame)
            for mapping in blink_mappings:
                amount = compute_blink_amount(
                    time_sec, settings, seed=blink_seed(mapping, scene),
                )
                jitter_left, jitter_right = compute_blink_eyelid_jitters(
                    time_sec, mapping, scene, settings,
                )
                apply_blink_mapping(
                    scene,
                    amount,
                    mapping,
                    fac_jitter_left=jitter_left,
                    fac_jitter_right=jitter_right,
                    **apply_kw,
                )

    time_sec = scene_time_at_frame(scene, frame)

    if settings.breathing_enabled and breathing_is_configured(settings):
        breathing_mappings = [
            m for m in settings.breathing_mappings if breathing_mapping_is_configured(m)
        ]
        if breathing_mappings:
            phase = compute_breath_phase(
                time_sec,
                settings.breathing_bpm,
                settings.breathing_exhale_ratio,
            )
            for mapping in breathing_mappings:
                apply_breathing_mapping(scene, phase, mapping, **apply_kw)

    if settings.micro_motion_enabled and micro_motion_is_configured(settings):
        micro_mappings = [
            m for m in settings.micro_motion_mappings if micro_motion_mapping_is_configured(m)
        ]
        if micro_mappings:
            for mapping in micro_mappings:
                state = compute_micro_motion_state(
                    time_sec, mapping, scene, settings, dt=dt,
                )
                apply_micro_motion_mapping(scene, state, mapping, **apply_kw)

    if not playing and not rendering:
        from .preview import apply_scene_previews

        apply_scene_previews(scene, base_cache=live_cache, frame=frame)


@persistent
def frame_change_post(scene: bpy.types.Scene, _depsgraph) -> None:
    global _LAST_FRAME, _WAS_PLAYING, _WAS_RENDERING, _HANDLER_TICK_DEPTH

    if _HANDLER_TICK_DEPTH > 0:
        return

    if not getattr(scene, "blipsync", None):
        return
    settings = scene.blipsync
    if not settings.enabled and not settings.emotion_enabled and not settings.blink_enabled:
        if not settings.breathing_enabled and not settings.micro_motion_enabled:
            return

    rendering = _is_rendering()
    _HANDLER_TICK_DEPTH += 1
    try:
        if rendering:
            if not _WAS_RENDERING:
                _reset_tick_state(scene)
                _WAS_RENDERING = True
            _tick_scene(scene, playing=True, rendering=True)
            return

        if _WAS_RENDERING:
            _WAS_RENDERING = False
            revert_motion_layer_state()
            _LAST_FRAME = None
            stop_scene_key = int(scene.as_pointer())
            _LAST_TICK_FRAME_BY_SCENE.pop(stop_scene_key, None)
            _LAST_PAUSED_FRAME_BY_SCENE.pop(stop_scene_key, None)
            _schedule_animation_refresh()

        playing = _is_playing()
        if not playing:
            if _WAS_PLAYING:
                get_engine().reset_smoothing()
                get_emotion_engine().reset_smoothing()
                reset_head_smoothing()
                revert_motion_layer_state()
                _LAST_FRAME = None
                stop_scene_key = int(scene.as_pointer())
                _LAST_TICK_FRAME_BY_SCENE.pop(stop_scene_key, None)
                _LAST_PAUSED_FRAME_BY_SCENE.pop(stop_scene_key, None)
                _WAS_PLAYING = False
                _schedule_animation_refresh()
                return
            _WAS_PLAYING = False
            _tick_scene(scene, playing=False)
            return

        if not _WAS_PLAYING:
            _reset_tick_state(scene)

        _WAS_PLAYING = True
        _tick_scene(scene, playing=True)
    finally:
        _HANDLER_TICK_DEPTH -= 1


def _iter_scenes():
    """Blender 5.x: bpy.data is restricted during addon enable."""
    try:
        return list(bpy.data.scenes)
    except (AttributeError, TypeError):
        return []


@persistent
def load_post(_dummy1, _dummy2) -> None:
    for scene in _iter_scenes():
        if getattr(scene, "blipsync", None):
            ensure_scene_defaults(scene)


_INIT_TIMER = None


def _deferred_scene_init() -> None:
    global _INIT_TIMER
    _INIT_TIMER = None
    for scene in _iter_scenes():
        if getattr(scene, "blipsync", None):
            ensure_scene_defaults(scene)
    return None


def register_handlers() -> None:
    global _INIT_TIMER

    from .deps_installer import schedule_auto_install
    from .pose_integrity import register_pose_integrity

    schedule_auto_install()
    register_pose_integrity()

    if frame_change_post not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_post)
    if load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post)

    if _INIT_TIMER is None:
        _INIT_TIMER = bpy.app.timers.register(_deferred_scene_init, first_interval=0.1)


def unregister_handlers() -> None:
    global _INIT_TIMER, _REFRESH_TIMER

    from .pose_integrity import unregister_pose_integrity

    unregister_pose_integrity()

    if _REFRESH_TIMER is not None:
        try:
            bpy.app.timers.unregister(_REFRESH_TIMER)
        except Exception:
            pass
        _REFRESH_TIMER = None

    if _INIT_TIMER is not None:
        try:
            bpy.app.timers.unregister(_INIT_TIMER)
        except Exception:
            pass
        _INIT_TIMER = None

    if frame_change_post in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(frame_change_post)
    if load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post)
