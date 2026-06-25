"""Playback-driven lip sync and emotion sync handlers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import bpy
from bpy.app.handlers import persistent

from .apply_context import (
    ApplyContext,
    begin_overlay_render_session,
    end_overlay_render_session,
    merge_apply_context,
    resolve_apply_context,
    uses_overlay_render,
)
from .applicator import apply_weights
from .defaults import (
    check_emotion_configured,
    check_scene_configured,
    ensure_scene_defaults,
    get_channel_emotion_mapping,
    get_channel_mapping,
    resolve_enabled_channel_targets,
    scene_has_active_previews,
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
    invalidate_motion_overlay_state,
    motion_layers_out_of_sync,
    revert_motion_layer_state,
)
from .motion_applicator import (
    apply_breathing_mapping,
    apply_micro_motion_mapping,
)
from .tick_base_cache import capture_tick_keyframe_bases
from .emotion_applicator import apply_emotion_weights
from .emotion_engine import get_emotion_engine
from .engine import get_engine, mapped_phoneme_ratios
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
_DEPSGRAPH_ENSURE_COUNT: dict[tuple[int, int], int] = {}
_RENDER_PROFILE_LOG: Optional[Path] = None
_RENDER_PROFILE_FRAMES = 0
_RENDER_OVERLAY_ACTIVE = False


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
    settings.debug_emotion = str(result.dominant)
    settings.debug_emotion_happy = float(result.happy)
    settings.debug_emotion_sad = float(result.sad)
    settings.debug_emotion_angry = float(result.angry)
    settings.debug_emotion_neutral = float(result.neutral)
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES", "DOPESHEET_EDITOR", "NLA_EDITOR"}:
                area.tag_redraw()


def _instant_lip_weights(scene: bpy.types.Scene, result, mapping) -> dict[str, float]:
    """Paused/scrub mode: apply current analysis without smoothing lag."""
    settings = scene.blipsync
    blend_ratios = mapped_phoneme_ratios(result.phoneme_ratios)
    weights: dict[str, float] = {}
    sum_weight = 0.0
    for expr in mapping.phoneme_exprs:
        phoneme = expr.label
        if settings.use_phoneme_blend:
            value = float(blend_ratios.get(phoneme, 0.0))
        else:
            value = 1.0 if phoneme == result.phoneme else 0.0
        weights[phoneme] = value
        sum_weight += value
    if sum_weight > 0.0:
        for key in list(weights.keys()):
            weights[key] /= sum_weight
    weights["__volume__"] = result.volume if result.raw_volume > 0.0 else 0.0
    return weights


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
    revert_motion_layer_state()
    global _LAST_FRAME
    _LAST_FRAME = None
    scene_key = int(scene.as_pointer())
    _LAST_TICK_FRAME_BY_SCENE.pop(scene_key, None)
    _LAST_PAUSED_FRAME_BY_SCENE.pop(scene_key, None)
    _clear_depsgraph_ensure_for_scene(scene_key)


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
                f"render_apply_mode={getattr(settings, 'render_apply_mode', 'OVERLAY')}\n"
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
    reapply_from_cache: bool = False,
    apply_context: Optional[ApplyContext] = None,
) -> Optional[TickProfiler]:
    global _LAST_FRAME

    ensure_scene_defaults(scene)
    settings = scene.blipsync
    if settings.__class__.__name__ == "_PropertyDeferred":
        return profiler
    if profiler is None and (settings.debug_profile_ticks or settings.debug_profile_render):
        profiler = TickProfiler()

    lip_ok, _lip_msg = check_scene_configured(scene) if settings.enabled else (True, "")
    emotion_ok, _emotion_msg = check_emotion_configured(scene) if settings.emotion_enabled else (True, "")
    targets = resolve_enabled_channel_targets(settings)
    procedural_active = (
        (settings.blink_enabled and blink_is_configured(settings))
        or (settings.breathing_enabled and breathing_is_configured(settings))
        or (settings.micro_motion_enabled and micro_motion_is_configured(settings))
    )
    can_run_lip = settings.enabled and lip_ok
    can_run_emotion = settings.emotion_enabled and bool(targets)
    preview_active = scene_has_active_previews(settings)
    if not can_run_lip and not can_run_emotion and not procedural_active and not preview_active:
        return profiler

    lip_engine = get_engine()
    emotion_engine = get_emotion_engine()
    lip_or_emotion = can_run_lip or can_run_emotion
    frame = scene.frame_current
    scene_key = int(scene.as_pointer())

    # Blender may fire frame_change_post more than once per frame (depsgraph refresh).
    # A repeat pass must re-apply motion: keyframe eval can reset pose/shapes after our
    # first apply, and stale layer bookkeeping would otherwise capture a zeroed base.
    reapply_same_frame = playing and _LAST_TICK_FRAME_BY_SCENE.get(scene_key) == frame
    if reapply_same_frame or reapply_from_cache:
        invalidate_motion_overlay_state()
    elif playing:
        _LAST_TICK_FRAME_BY_SCENE[scene_key] = frame
    else:
        last_paused = _LAST_PAUSED_FRAME_BY_SCENE.get(scene_key)
        if last_paused is not None and last_paused != frame:
            revert_motion_layer_state()
            reset_head_smoothing()
        _LAST_PAUSED_FRAME_BY_SCENE[scene_key] = frame

    with profiler_section(profiler, "setup_dt"):
        if not playing:
            lip_engine.reset_smoothing()
            emotion_engine.reset_smoothing()
            dt = 1.0 / _scene_fps(scene)
        elif _LAST_FRAME is None:
            dt = 1.0 / _scene_fps(scene)
        elif frame == _LAST_FRAME:
            dt = 0.0
        else:
            if frame < _LAST_FRAME:
                revert_motion_layer_state()
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
            include_all_phoneme_mappings=preview_active,
            include_all_emotion_mappings=preview_active,
            include_all_blink_mappings=preview_active,
            include_all_breathing_mappings=preview_active,
            include_all_micro_motion_mappings=preview_active,
            prefer_rest_for_uncached_emotion_layer=reapply_from_cache,
        )
    apply_kw = merge_apply_context(
        dict(base_cache=live_cache, frame=frame),
        apply_context if apply_context is not None else (
            resolve_apply_context(settings, rendering=rendering) if rendering else None
        ),
    )

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
                        if reapply_from_cache:
                            result = lip_engine.last_results.get(target.channel)
                        else:
                            with profiler_section(profiler, "lip_analyze"):
                                result = lip_engine.analyze_channel(scene, frame, target)
                        if result is not None:
                            with profiler_section(profiler, "lip_smooth"):
                                if playing:
                                    weights = lip_engine.update_smoothed_weights(
                                        scene, result, dt, target.channel, mapping,
                                    )
                                else:
                                    weights = _instant_lip_weights(scene, result, mapping)
                            with profiler_section(profiler, "lip_apply"):
                                apply_weights(scene, weights, mapping, **apply_kw)
                            if not reapply_from_cache and target == debug_target and not rendering:
                                _update_lip_debug_display(scene, target, result)

                if can_run_emotion:
                    emotion_mapping = get_channel_emotion_mapping(settings, target)
                    if emotion_mapping is not None:
                        if reapply_from_cache:
                            emotion_result = emotion_engine.last_results.get(target.channel)
                        else:
                            with profiler_section(profiler, "emotion_analyze"):
                                emotion_result = emotion_engine.analyze_channel(scene, frame, target)
                        if emotion_result is not None:
                            with profiler_section(profiler, "emotion_smooth"):
                                emotion_weights = emotion_engine.update_smoothed_weights(
                                    scene, emotion_result, dt, target.channel, emotion_mapping,
                                )
                            with profiler_section(profiler, "emotion_apply"):
                                apply_emotion_weights(
                                    scene, emotion_weights, emotion_mapping, **apply_kw,
                                )
                            if target == debug_target:
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

    if not playing and not rendering and preview_active:
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


def _clear_depsgraph_ensure_for_scene(scene_key: int) -> None:
    global _DEPSGRAPH_ENSURE_COUNT
    _DEPSGRAPH_ENSURE_COUNT = {
        key: count
        for key, count in _DEPSGRAPH_ENSURE_COUNT.items()
        if key[0] != scene_key
    }


def _ensure_procedural_after_depsgraph(scene: bpy.types.Scene, *, rendering: bool) -> None:
    """Re-apply when depsgraph wiped our writes after frame_change_post."""
    settings = scene.blipsync
    scene_key = int(scene.as_pointer())
    frame = scene.frame_current
    if _LAST_TICK_FRAME_BY_SCENE.get(scene_key) != frame:
        return
    ensure_key = (scene_key, frame)

    if _DEPSGRAPH_ENSURE_COUNT.get(ensure_key, 0) >= 2:
        return
    out_of_sync = motion_layers_out_of_sync()
    if not out_of_sync:
        return

    _DEPSGRAPH_ENSURE_COUNT[ensure_key] = _DEPSGRAPH_ENSURE_COUNT.get(ensure_key, 0) + 1
    _tick_scene(scene, playing=True, rendering=rendering, reapply_from_cache=True)


def _blipsync_scene_wants_handlers(settings) -> bool:
    if settings.enabled or settings.emotion_enabled or settings.blink_enabled:
        return True
    return bool(settings.breathing_enabled or settings.micro_motion_enabled)


def _is_vrm_spring_frame_change_pre_handler(handler) -> bool:
    return (
        getattr(handler, "__name__", "") == "frame_change_pre"
        and getattr(handler, "__module__", "").endswith(".editor.spring_bone1.handler")
    )


def _ensure_frame_change_pre_before_vrm_spring() -> None:
    """Run bAnima's render pose pre-pass before VRM Spring Bone frame_change_pre."""
    handlers = bpy.app.handlers.frame_change_pre
    try:
        if frame_change_pre in handlers:
            handlers.remove(frame_change_pre)
        insert_index = len(handlers)
        for index, handler in enumerate(handlers):
            if _is_vrm_spring_frame_change_pre_handler(handler):
                insert_index = index
                break
        handlers.insert(insert_index, frame_change_pre)
    except Exception:
        if frame_change_pre not in handlers:
            handlers.append(frame_change_pre)


def _vrm_spring_bone_handler_present() -> bool:
    return any(
        _is_vrm_spring_frame_change_pre_handler(handler)
        for handler in bpy.app.handlers.frame_change_pre
    )


def _tick_render_vrm_spring_pose_prepass(scene: bpy.types.Scene) -> None:
    """Pose-only render pre-pass for VRM Spring Bone.

    The VRM add-on advances Spring Bone in frame_change_pre, not depsgraph.
    This makes the parent bones visible to Spring Bone without writing shape keys
    or replacing the normal post-eval render tick.
    """
    ensure_scene_defaults(scene)
    settings = scene.blipsync
    can_run_breathing = settings.breathing_enabled and breathing_is_configured(settings)
    can_run_micro = settings.micro_motion_enabled and micro_motion_is_configured(settings)
    if not can_run_breathing and not can_run_micro:
        return

    frame = scene.frame_current
    with profiler_section(None, "render_vrm_spring_pose_cache"):
        live_cache = capture_tick_keyframe_bases(
            scene,
            settings,
            frame,
            include_breathing=can_run_breathing,
            include_micro_motion=can_run_micro,
        )
    apply_kw = dict(base_cache=live_cache, frame=frame, track_layer_state=False)
    time_sec = scene_time_at_frame(scene, frame)

    if can_run_breathing:
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
                apply_breathing_mapping(scene, phase, mapping, pose_only=True, **apply_kw)

    if can_run_micro:
        micro_mappings = [
            m for m in settings.micro_motion_mappings if micro_motion_mapping_is_configured(m)
        ]
        if micro_mappings:
            dt = 1.0 / _scene_fps(scene)
            if _LAST_FRAME is not None:
                dt = abs(frame - _LAST_FRAME) / _scene_fps(scene)
                dt = min(dt, 2.0 / _scene_fps(scene))
                dt = max(dt, 1.0 / 120.0)
            for mapping in micro_mappings:
                state = compute_micro_motion_state(
                    time_sec, mapping, scene, settings, dt=dt,
                )
                apply_micro_motion_mapping(scene, state, mapping, pose_only=True, **apply_kw)


def _tick_render_scene(scene: bpy.types.Scene, *, post_eval: bool = False) -> None:
    """Apply blipsync for the current render frame.

    post_eval=True from frame_change_post (after depsgraph). render_pre runs before
    evaluation and must not apply motion — it only warms the render session.

    render_apply_mode=OVERLAY uses DNA-silent shape writes; RNA restores legacy path.
    """
    settings = scene.blipsync
    if not settings.realtime_during_render:
        return
    if not _WAS_RENDERING:
        _begin_render_session(scene)
    if not post_eval:
        return
    _tick_scene(
        scene,
        playing=True,
        rendering=True,
        apply_context=resolve_apply_context(settings, rendering=True),
    )


def _begin_render_session(scene: bpy.types.Scene) -> None:
    global _WAS_RENDERING, _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES, _RENDER_OVERLAY_ACTIVE
    if _WAS_RENDERING:
        return
    _reset_tick_state(scene)
    _WAS_RENDERING = True
    _RENDER_PROFILE_LOG = None
    _RENDER_PROFILE_FRAMES = 0
    settings = scene.blipsync
    _RENDER_OVERLAY_ACTIVE = uses_overlay_render(settings)
    if _RENDER_OVERLAY_ACTIVE:
        begin_overlay_render_session(scene)


def _end_render_session(scene: bpy.types.Scene) -> None:
    global _WAS_RENDERING, _LAST_FRAME, _RENDER_PROFILE_LOG, _RENDER_PROFILE_FRAMES
    global _RENDER_OVERLAY_ACTIVE
    if not _WAS_RENDERING:
        return
    if _RENDER_OVERLAY_ACTIVE:
        end_overlay_render_session(scene)
        from .dna_apply import clear_touched_shape_keys

        clear_touched_shape_keys()
    _RENDER_OVERLAY_ACTIVE = False
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
    _clear_depsgraph_ensure_for_scene(stop_scene_key)
    _schedule_animation_refresh()


@persistent
def frame_change_pre(scene: bpy.types.Scene, _depsgraph) -> None:
    """Prepare playback/render session before depsgraph evaluates keyframes."""
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

    if _is_rendering() and settings.realtime_during_render:
        _HANDLER_TICK_DEPTH += 1
        try:
            _begin_render_session(scene)
            if _vrm_spring_bone_handler_present():
                _tick_render_vrm_spring_pose_prepass(scene)
        finally:
            _HANDLER_TICK_DEPTH -= 1

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
        _ensure_frame_change_pre_before_vrm_spring()
        _begin_render_session(_scene)


@persistent
def render_pre(scene: bpy.types.Scene) -> None:
    """Ensure render session is open; motion is applied in frame_change_post only."""
    if bake_in_progress():
        return
    if not getattr(scene, "blipsync", None):
        return
    settings = scene.blipsync
    if not _blipsync_scene_wants_handlers(settings):
        return
    if not settings.realtime_during_render:
        return
    _ensure_frame_change_pre_before_vrm_spring()
    if not _WAS_RENDERING:
        _begin_render_session(scene)


@persistent
def render_complete(scene: bpy.types.Scene) -> None:
    _end_render_session(scene)


@persistent
def render_cancel(scene: bpy.types.Scene) -> None:
    _end_render_session(scene)


@persistent
def depsgraph_update_post(scene: bpy.types.Scene, _depsgraph) -> None:
    """Safety net: re-apply if depsgraph reset procedural values after our tick."""
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

    rendering = _is_rendering()
    if not _is_playing() and not (rendering and settings.realtime_during_render):
        return

    _HANDLER_TICK_DEPTH += 1
    try:
        _ensure_procedural_after_depsgraph(scene, rendering=rendering)
    finally:
        _HANDLER_TICK_DEPTH -= 1


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
    playing = _is_playing()
    _HANDLER_TICK_DEPTH += 1
    try:
        if rendering:
            _tick_render_scene(scene, post_eval=True)
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
                _clear_depsgraph_ensure_for_scene(stop_scene_key)
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

    _ensure_frame_change_pre_before_vrm_spring()
    if frame_change_post not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(frame_change_post)
    if depsgraph_update_post not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_post)
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
    if depsgraph_update_post in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(depsgraph_update_post)
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
