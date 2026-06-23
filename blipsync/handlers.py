"""Playback-driven lip sync and emotion sync handlers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Optional

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
from .tick_profiler import (
    TickProfiler,
    append_profile_report,
    default_profile_log_path,
    profiler_section,
)

_LAST_FRAME = None
_WAS_PLAYING = False
_WAS_RENDERING = False
_HANDLER_TICK_DEPTH = 0
_BAKE_DEPTH = 0
_REFRESH_TIMER = None
_LAST_TICK_FRAME_BY_SCENE: dict[int, int] = {}
_LAST_PAUSED_FRAME_BY_SCENE: dict[int, int] = {}
_RENDER_PROFILE_LOG: Optional[Path] = None
_RENDER_PROFILE_FRAMES = 0


def handler_tick_active() -> bool:
    return _HANDLER_TICK_DEPTH > 0


def bake_in_progress() -> bool:
    return _BAKE_DEPTH > 0


@contextmanager
def suspend_realtime_handlers():
    """Suppress frame_change_post while baking (avoids frame_set feedback loops)."""
    global _BAKE_DEPTH
    _BAKE_DEPTH += 1
    try:
        yield
    finally:
        _BAKE_DEPTH = max(0, _BAKE_DEPTH - 1)


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


def _finish_tick_profile(
    scene: bpy.types.Scene,
    settings,
    profiler: TickProfiler,
    *,
    frame: int,
    context: str,
) -> None:
    report = profiler.format_report(frame=frame, context=context)
    if settings.debug_profile_ticks:
        print(report)
    if settings.debug_profile_render and context == "render":
        global _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES
        if _RENDER_PROFILE_LOG is None:
            _RENDER_PROFILE_LOG = default_profile_log_path(scene)
            header = (
                f"blipsync render profile started {context}\n"
                f"realtime_during_render={settings.realtime_during_render}\n"
            )
            append_profile_report(_RENDER_PROFILE_LOG, header)
        append_profile_report(_RENDER_PROFILE_LOG, report)
        _RENDER_PROFILE_FRAMES += 1


def _tick_scene(
    scene: bpy.types.Scene,
    *,
    playing: bool,
    rendering: bool = False,
    profiler: Optional[TickProfiler] = None,
    force: bool = False,
) -> Optional[TickProfiler]:
    global _LAST_FRAME

    ensure_scene_defaults(scene)
    settings = scene.blipsync
    if profiler is None and (settings.debug_profile_ticks or settings.debug_profile_render):
        profiler = TickProfiler()

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
        return profiler

    lip_engine = get_engine()
    emotion_engine = get_emotion_engine()
    targets = resolve_enabled_channel_targets(settings)
    lip_or_emotion = can_run_lip or can_run_emotion
    frame = scene.frame_current
    scene_key = int(scene.as_pointer())

    if playing and not force:
        if _LAST_TICK_FRAME_BY_SCENE.get(scene_key) == frame:
            return profiler
        _LAST_TICK_FRAME_BY_SCENE[scene_key] = frame
    else:
        last_paused = _LAST_PAUSED_FRAME_BY_SCENE.get(scene_key)
        if last_paused is not None and last_paused != frame:
            reset_motion_layer_state()
            reset_head_smoothing()
        _LAST_PAUSED_FRAME_BY_SCENE[scene_key] = frame

    with profiler_section(profiler, "setup_dt"):
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

    with profiler_section(profiler, "capture_cache"):
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
                        if profiler is not None:
                            ctx = "render" if rendering else "tick"
                            _finish_tick_profile(scene, settings, profiler, frame=frame, context=ctx)
                        return profiler
        else:
            debug_target = targets[min(settings.channel_targets_index, len(targets) - 1)]
            for target in targets:
                if can_run_lip:
                    mapping = get_channel_mapping(settings, target)
                    if mapping is not None:
                        with profiler_section(profiler, "lip_analyze"):
                            result = lip_engine.analyze_channel(scene, frame, target)
                        with profiler_section(profiler, "lip_smooth"):
                            weights = lip_engine.update_smoothed_weights(
                                scene, result, dt, target.channel, mapping,
                            )
                        with profiler_section(profiler, "lip_apply"):
                            apply_weights(scene, weights, mapping, **apply_kw)
                        if target == debug_target and not rendering:
                            _update_lip_debug_display(scene, target, result)

                if can_run_emotion:
                    emotion_mapping = get_channel_emotion_mapping(settings, target)
                    if emotion_mapping is not None:
                        with profiler_section(profiler, "emotion_analyze"):
                            emotion_result = emotion_engine.analyze_channel(scene, frame, target)
                        with profiler_section(profiler, "emotion_smooth"):
                            emotion_weights = emotion_engine.update_smoothed_weights(
                                scene, emotion_result, dt, target.channel, emotion_mapping,
                            )
                        with profiler_section(profiler, "emotion_apply"):
                            apply_emotion_weights(
                                scene, emotion_weights, emotion_mapping, **apply_kw,
                            )
                        if target == debug_target and not rendering:
                            _update_emotion_debug_display(scene, emotion_result)

    if settings.blink_enabled and blink_is_configured(settings):
        blink_mappings = [
            mapping for mapping in settings.blink_mappings if blink_mapping_is_configured(mapping)
        ]
        if blink_mappings:
            with profiler_section(profiler, "blink"):
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
            with profiler_section(profiler, "breathing"):
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
            with profiler_section(profiler, "micro_motion"):
                for mapping in micro_mappings:
                    state = compute_micro_motion_state(
                        time_sec, mapping, scene, settings, dt=dt,
                    )
                    apply_micro_motion_mapping(scene, state, mapping, **apply_kw)

    if not playing and not rendering:
        with profiler_section(profiler, "preview"):
            from .preview import apply_scene_previews

            apply_scene_previews(scene, base_cache=live_cache, frame=frame)

    if profiler is not None:
        ctx = "render" if rendering else "tick"
        _finish_tick_profile(scene, settings, profiler, frame=frame, context=ctx)
    return profiler


def profile_tick_at_frame(scene: bpy.types.Scene, frame: int) -> tuple[str, Path]:
    """Run one full tick with profiling (diagnostic operator)."""
    ensure_scene_defaults(scene)
    original = scene.frame_current
    profiler = TickProfiler()
    try:
        scene.frame_set(frame)
        _tick_scene(scene, playing=False, rendering=False, profiler=profiler, force=True)
    finally:
        scene.frame_set(original)
    report = profiler.format_report(frame=frame, context="diagnostic")
    path = default_profile_log_path(scene)
    append_profile_report(path, report)
    return report, path


def _blipsync_scene_wants_handlers(settings) -> bool:
    if settings.enabled or settings.emotion_enabled or settings.blink_enabled:
        return True
    return bool(settings.breathing_enabled or settings.micro_motion_enabled)


def _tick_render_scene(scene: bpy.types.Scene) -> None:
    """Apply blipsync for the current render frame (after animation evaluation)."""
    settings = scene.blipsync
    if not settings.realtime_during_render:
        return
    if not _WAS_RENDERING:
        _begin_render_session(scene)
    _tick_scene(scene, playing=True, rendering=True)


def _begin_render_session(scene: bpy.types.Scene) -> None:
    global _WAS_RENDERING, _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES
    if _WAS_RENDERING:
        return
    _reset_tick_state(scene)
    _WAS_RENDERING = True
    _RENDER_PROFILE_LOG = None
    _RENDER_PROFILE_FRAMES = 0


def _end_render_session(scene: bpy.types.Scene) -> None:
    global _WAS_RENDERING, _LAST_FRAME, _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES
    if not _WAS_RENDERING:
        return
    _WAS_RENDERING = False
    if _RENDER_PROFILE_LOG is not None and _RENDER_PROFILE_FRAMES > 0:
        summary = (
            f"render profile summary: {_RENDER_PROFILE_FRAMES} frame(s) logged\n"
            f"log: {_RENDER_PROFILE_LOG}"
        )
        print(summary)
        append_profile_report(_RENDER_PROFILE_LOG, summary)
    _RENDER_PROFILE_LOG = None
    _RENDER_PROFILE_FRAMES = 0
    revert_motion_layer_state()
    _LAST_FRAME = None
    stop_scene_key = int(scene.as_pointer())
    _LAST_TICK_FRAME_BY_SCENE.pop(stop_scene_key, None)
    _LAST_PAUSED_FRAME_BY_SCENE.pop(stop_scene_key, None)
    _schedule_animation_refresh()


@persistent
def frame_change_pre(scene: bpy.types.Scene, _depsgraph) -> None:
    """Prepare playback/render session before depsgraph evaluates keyframes."""
    if _HANDLER_TICK_DEPTH > 0:
        return
    if bake_in_progress():
        return
    if not getattr(scene, "blipsync", None):
        return

    settings = scene.blipsync
    if not _blipsync_scene_wants_handlers(settings):
        return

    if _is_rendering() and settings.realtime_during_render:
        _begin_render_session(scene)

    if _is_playing() and not _WAS_PLAYING:
        _reset_tick_state(scene)


@persistent
def render_init(_scene: bpy.types.Scene) -> None:
    if bake_in_progress():
        return
    if not getattr(_scene, "blipsync", None):
        return
    settings = _scene.blipsync
    if _blipsync_scene_wants_handlers(settings) and settings.realtime_during_render:
        _begin_render_session(_scene)


@persistent
def render_pre(scene: bpy.types.Scene) -> None:
    """Fallback render tick — some pipelines skip frame_change_post."""
    global _HANDLER_TICK_DEPTH

    if _HANDLER_TICK_DEPTH > 0:
        return
    if bake_in_progress():
        return
    if not getattr(scene, "blipsync", None):
        return
    settings = scene.blipsync
    if not _blipsync_scene_wants_handlers(settings):
        return
    if not settings.realtime_during_render:
        return

    _HANDLER_TICK_DEPTH += 1
    try:
        _tick_render_scene(scene)
    finally:
        _HANDLER_TICK_DEPTH -= 1


@persistent
def render_complete(scene: bpy.types.Scene) -> None:
    _end_render_session(scene)


@persistent
def render_cancel(scene: bpy.types.Scene) -> None:
    _end_render_session(scene)


@persistent
def frame_change_post(scene: bpy.types.Scene, _depsgraph) -> None:
    global _LAST_FRAME, _WAS_PLAYING, _WAS_RENDERING, _HANDLER_TICK_DEPTH
    global _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES

    if _HANDLER_TICK_DEPTH > 0:
        return

    if bake_in_progress():
        return

    if not getattr(scene, "blipsync", None):
        return
    settings = scene.blipsync
    if not _blipsync_scene_wants_handlers(settings):
        if _WAS_RENDERING:
            _end_render_session(scene)
        return

    rendering = _is_rendering()
    _HANDLER_TICK_DEPTH += 1
    try:
        if rendering:
            _tick_render_scene(scene)
            return

        if _WAS_RENDERING:
            _end_render_session(scene)

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
        if not getattr(scene, "blipsync", None):
            continue
        ensure_scene_defaults(scene)
        settings = scene.blipsync
        if settings.render_rt_fixup_v1:
            continue
        settings.render_rt_fixup_v1 = True
        if not settings.realtime_during_render and _blipsync_scene_wants_handlers(settings):
            settings.realtime_during_render = True


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

    if frame_change_pre not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(frame_change_pre)
    if frame_change_post not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_post)
    if render_init not in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.append(render_init)
    if render_pre not in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.append(render_pre)
    if render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(render_complete)
    if render_cancel not in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.append(render_cancel)
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

    if frame_change_pre in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(frame_change_pre)
    if frame_change_post in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(frame_change_post)
    if render_init in bpy.app.handlers.render_init:
        bpy.app.handlers.render_init.remove(render_init)
    if render_pre in bpy.app.handlers.render_pre:
        bpy.app.handlers.render_pre.remove(render_pre)
    if render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(render_complete)
    if render_cancel in bpy.app.handlers.render_cancel:
        bpy.app.handlers.render_cancel.remove(render_cancel)
    if load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post)
