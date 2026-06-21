"""Scene setup helpers."""

from __future__ import annotations

import bpy

from .properties import EMOTION_LABELS, PHONEME_LABELS
from .sequencer import channel_label, collect_channels_with_sound, collect_sound_strips


def _copy_morph_bind(src, dst) -> None:
    dst.mesh = src.mesh
    dst.shape_key = src.shape_key
    dst.weight_value = src.weight_value


def _copy_pose_bind(src, dst) -> None:
    dst.armature = src.armature
    dst.pose_bone = src.pose_bone
    dst.pose_axis = src.pose_axis
    dst.weight = src.weight
    dst.motion_amount = src.motion_amount


def _copy_phoneme_expr(src, dst) -> None:
    dst.label = src.label
    dst.binds.clear()
    for bind in src.binds:
        _copy_morph_bind(bind, dst.binds.add())
    dst.pose_binds.clear()
    for pose_bind in src.pose_binds:
        _copy_pose_bind(pose_bind, dst.pose_binds.add())


def ensure_phoneme_exprs_on(mapping) -> None:
    existing = {expr.label for expr in mapping.phoneme_exprs}
    for label in PHONEME_LABELS:
        if label in existing:
            continue
        expr = mapping.phoneme_exprs.add()
        expr.label = label
        if len(expr.binds) == 0:
            expr.binds.add()


def ensure_emotion_exprs_on(mapping) -> None:
    for expr in mapping.emotion_exprs:
        if expr.label == "Default":
            expr.label = "Neutral"
    existing = {expr.label for expr in mapping.emotion_exprs}
    for label in EMOTION_LABELS:
        if label in existing:
            continue
        expr = mapping.emotion_exprs.add()
        expr.label = label
        if len(expr.binds) == 0:
            expr.binds.add()


def ensure_phoneme_mappings(settings) -> None:
    if settings.phoneme_mappings:
        for mapping in settings.phoneme_mappings:
            ensure_phoneme_exprs_on(mapping)
        return

    mapping = settings.phoneme_mappings.add()
    mapping.name = "デフォルト"

    if settings.phoneme_exprs:
        for old_expr in settings.phoneme_exprs:
            _copy_phoneme_expr(old_expr, mapping.phoneme_exprs.add())
    else:
        ensure_phoneme_exprs_on(mapping)


def ensure_emotion_mappings(settings) -> None:
    if settings.emotion_mappings:
        for mapping in settings.emotion_mappings:
            ensure_emotion_exprs_on(mapping)
        return

    mapping = settings.emotion_mappings.add()
    mapping.name = "デフォルト"
    ensure_emotion_exprs_on(mapping)


def _migrate_legacy_blink_eye(legacy_eye, eye_slot) -> None:
    if not legacy_eye.mesh or not legacy_eye.shape_key:
        return
    for bind in eye_slot.binds:
        if bind.mesh == legacy_eye.mesh and bind.shape_key == legacy_eye.shape_key:
            return
    bind = eye_slot.binds.add()
    bind.mesh = legacy_eye.mesh
    bind.shape_key = legacy_eye.shape_key
    bind.weight_value = legacy_eye.weight_value


def ensure_blink_eye_slot(eye_slot) -> None:
    if len(eye_slot.binds) == 0:
        eye_slot.binds.add()


def ensure_blink_mappings(settings) -> None:
    if settings.blink_mappings:
        for mapping in settings.blink_mappings:
            ensure_blink_eye_slot(mapping.left_eye)
            ensure_blink_eye_slot(mapping.right_eye)
        return

    mapping = settings.blink_mappings.add()
    mapping.name = "デフォルト"
    ensure_blink_eye_slot(mapping.left_eye)
    ensure_blink_eye_slot(mapping.right_eye)
    _migrate_legacy_blink_eye(settings.blink_left_eye, mapping.left_eye)
    _migrate_legacy_blink_eye(settings.blink_right_eye, mapping.right_eye)


def peek_channel_mapping(settings, channel_target):
    if not settings.phoneme_mappings:
        return None
    index = channel_target.mapping_index
    if index < 0 or index >= len(settings.phoneme_mappings):
        return None
    return settings.phoneme_mappings[index]


def get_channel_mapping(settings, channel_target):
    if not settings.phoneme_mappings:
        return None
    index = max(0, min(channel_target.mapping_index, len(settings.phoneme_mappings) - 1))
    channel_target.mapping_index = index
    return settings.phoneme_mappings[index]


def peek_channel_emotion_mapping(settings, channel_target):
    if not settings.emotion_mappings:
        return None
    index = channel_target.emotion_mapping_index
    if index < 0 or index >= len(settings.emotion_mappings):
        return None
    return settings.emotion_mappings[index]


def get_channel_emotion_mapping(settings, channel_target):
    if not settings.emotion_mappings:
        return None
    index = max(0, min(channel_target.emotion_mapping_index, len(settings.emotion_mappings) - 1))
    channel_target.emotion_mapping_index = index
    return settings.emotion_mappings[index]


def refresh_channel_labels(scene: bpy.types.Scene) -> None:
    """Update channel display labels. Operators/handlers only."""
    channel_map = collect_channels_with_sound(scene)
    for target in scene.blipsync.channel_targets:
        strips = channel_map.get(target.channel, [])
        target.label = channel_label(target.channel, strips)


def sync_channels_from_sequencer(scene: bpy.types.Scene, *, replace: bool = False) -> int:
    channel_map = collect_channels_with_sound(scene)
    if not channel_map:
        return 0

    settings = scene.blipsync
    if replace:
        settings.channel_targets.clear()

    existing = {t.channel for t in settings.channel_targets}
    added = 0
    for ch, strips in sorted(channel_map.items()):
        if ch in existing:
            continue
        item = settings.channel_targets.add()
        item.channel = ch
        item.label = channel_label(ch, strips)
        item.enabled = True
        item.profile_source = "MALE"
        item.mapping_index = 0
        item.emotion_mapping_index = 0
        added += 1

    refresh_channel_labels(scene)
    return added


def ensure_bind_slot(bind_slot) -> None:
    if len(bind_slot.binds) == 0:
        bind_slot.binds.add()


def ensure_breathing_mappings(settings) -> None:
    if settings.breathing_mappings:
        for mapping in settings.breathing_mappings:
            ensure_bind_slot(mapping.targets)
        return

    mapping = settings.breathing_mappings.add()
    mapping.name = "デフォルト"
    ensure_bind_slot(mapping.targets)


def ensure_micro_motion_mappings(settings) -> None:
    from .properties import MICRO_MOTION_ALL_SLOT_ATTRS

    if settings.micro_motion_mappings:
        for mapping in settings.micro_motion_mappings:
            for attr in MICRO_MOTION_ALL_SLOT_ATTRS:
                ensure_bind_slot(getattr(mapping, attr))
        return

    mapping = settings.micro_motion_mappings.add()
    mapping.name = "デフォルト"
    for attr in MICRO_MOTION_ALL_SLOT_ATTRS:
        ensure_bind_slot(getattr(mapping, attr))


def bind_slot_is_configured(bind_slot) -> bool:
    for bind in bind_slot.binds:
        if bind.mesh and bind.shape_key:
            return True
    for pose_bind in bind_slot.pose_binds:
        if pose_bind.armature and pose_bind.pose_bone:
            return True
    return False


def breathing_mapping_is_configured(mapping) -> bool:
    return bind_slot_is_configured(mapping.targets)


def breathing_is_configured(settings) -> bool:
    return any(breathing_mapping_is_configured(m) for m in settings.breathing_mappings)


def morph_slot_is_configured(bind_slot) -> bool:
    for bind in bind_slot.binds:
        if bind.mesh and bind.shape_key:
            return True
    return False


def pose_slot_is_configured(bind_slot) -> bool:
    for pose_bind in bind_slot.pose_binds:
        if pose_bind.armature and pose_bind.pose_bone:
            return True
    return False


def micro_motion_mapping_is_configured(mapping) -> bool:
    if pose_slot_is_configured(mapping.head):
        return True
    if morph_slot_is_configured(mapping.eyebrows) or morph_slot_is_configured(mapping.mouth_open):
        return True
    if mapping.gaze_control == "BONE":
        if pose_slot_is_configured(mapping.left_eye) or pose_slot_is_configured(mapping.right_eye):
            return True
    else:
        for attr in ("look_up", "look_down", "look_left", "look_right"):
            if morph_slot_is_configured(getattr(mapping, attr)):
                return True
    return False


def micro_motion_is_configured(settings) -> bool:
    return any(micro_motion_mapping_is_configured(m) for m in settings.micro_motion_mappings)


def ensure_morph_weight_ui(settings) -> None:
    from .shape_key_utils import sync_morph_weight_ui

    for mapping in settings.phoneme_mappings:
        for expr in mapping.phoneme_exprs:
            for bind in expr.binds:
                try:
                    sync_morph_weight_ui(bind)
                except Exception:
                    pass
    for mapping in settings.emotion_mappings:
        for expr in mapping.emotion_exprs:
            for bind in expr.binds:
                try:
                    sync_morph_weight_ui(bind)
                except Exception:
                    pass
    for mapping in settings.blink_mappings:
        for eye_slot in (mapping.left_eye, mapping.right_eye):
            for bind in eye_slot.binds:
                try:
                    sync_morph_weight_ui(bind)
                except Exception:
                    pass
    for mapping in settings.breathing_mappings:
        for bind in mapping.targets.binds:
            try:
                sync_morph_weight_ui(bind)
            except Exception:
                pass
    for mapping in settings.micro_motion_mappings:
        for attr in (
            "head", "left_eye", "right_eye",
            "look_up", "look_down", "look_left", "look_right",
            "eyebrows", "mouth_open",
        ):
            slot = getattr(mapping, attr)
            for bind in slot.binds:
                try:
                    sync_morph_weight_ui(bind)
                except Exception:
                    pass


def ensure_scene_defaults(scene: bpy.types.Scene) -> None:
    from .properties import BLIpsyncSceneSettings
    from .registration import add_scene_pointer_deferred, ensure_scene_pointer

    if not hasattr(scene, "blipsync"):
        if not ensure_scene_pointer("blipsync", BLIpsyncSceneSettings):
            add_scene_pointer_deferred("blipsync", BLIpsyncSceneSettings)
            return
    settings = scene.blipsync
    if settings.__class__.__name__ == "_PropertyDeferred":
        return
    ensure_phoneme_mappings(settings)
    ensure_emotion_mappings(settings)
    ensure_blink_mappings(settings)
    ensure_breathing_mappings(settings)
    ensure_micro_motion_mappings(settings)
    ensure_morph_weight_ui(settings)
    if not settings.channel_targets:
        sync_channels_from_sequencer(scene)


def resolve_enabled_channel_targets(settings):
    return [t for t in settings.channel_targets if t.enabled and t.channel > 0]


def resolve_enabled_channels(settings) -> set[int]:
    return {t.channel for t in resolve_enabled_channel_targets(settings)}


def channels_have_sound(scene: bpy.types.Scene, channels: set[int]) -> bool:
    if not channels:
        return False
    for strip in collect_sound_strips(scene):
        if int(getattr(strip, "channel", 0)) in channels:
            return True
    return False


def mapping_is_configured(phoneme_mapping) -> bool:
    for expr in phoneme_mapping.phoneme_exprs:
        for bind in expr.binds:
            if bind.mesh and bind.shape_key:
                return True
        for pose_bind in expr.pose_binds:
            if pose_bind.armature and pose_bind.pose_bone:
                return True
    return False


def emotion_expr_is_configured(expr) -> bool:
    for bind in expr.binds:
        if bind.mesh and bind.shape_key:
            return True
    for pose_bind in expr.pose_binds:
        if pose_bind.armature and pose_bind.pose_bone:
            return True
    return False


EMOTION_HIGH_NORMAL_PAIRS = (
    ("Happy_High", "Happy"),
    ("Sad_High", "Sad"),
    ("Angry_High", "Angry"),
)


def merge_unconfigured_high_emotion_weights(
    weights: dict[str, float],
    emotion_mapping,
) -> dict[str, float]:
    """Fold *_High slot weights into normal slots when High has no binds."""
    merged = dict(weights)
    expr_by_label = {expr.label: expr for expr in emotion_mapping.emotion_exprs}
    for high_label, normal_label in EMOTION_HIGH_NORMAL_PAIRS:
        expr = expr_by_label.get(high_label)
        if expr is None or emotion_expr_is_configured(expr):
            continue
        merged[normal_label] = merged.get(normal_label, 0.0) + merged.get(high_label, 0.0)
        merged[high_label] = 0.0
    return merged


def emotion_mapping_is_configured(emotion_mapping) -> bool:
    for expr in emotion_mapping.emotion_exprs:
        if emotion_expr_is_configured(expr):
            return True
    return False


def blink_eye_slot_is_configured(eye_slot) -> bool:
    for bind in eye_slot.binds:
        if bind.mesh and bind.shape_key:
            return True
    for pose_bind in eye_slot.pose_binds:
        if pose_bind.armature and pose_bind.pose_bone:
            return True
    return False


def blink_mapping_is_configured(blink_mapping) -> bool:
    return blink_eye_slot_is_configured(blink_mapping.left_eye) or blink_eye_slot_is_configured(
        blink_mapping.right_eye
    )


def blink_is_configured(settings) -> bool:
    return any(blink_mapping_is_configured(mapping) for mapping in settings.blink_mappings)


def check_emotion_configured(scene: bpy.types.Scene) -> tuple[bool, str]:
    if not getattr(scene, "blipsync", None):
        return False, "BlipSync 未初期化。アドオンを再有効化してください。"

    settings = scene.blipsync
    if not settings.emotion_enabled:
        return True, ""

    targets = resolve_enabled_channel_targets(settings)
    if not targets:
        if not collect_channels_with_sound(scene):
            return False, "VSE に SOUND ストリップがありません"
        return False, "対象チャンネルを選択してください"

    channels = {t.channel for t in targets}
    if not channels_have_sound(scene, channels):
        return False, "選択チャンネルに SOUND ストリップがありません"

    if not settings.emotion_mappings:
        return False, "感情マッピングがありません"

    configured = 0
    for target in targets:
        mapping = peek_channel_emotion_mapping(settings, target)
        if mapping and emotion_mapping_is_configured(mapping):
            configured += 1

    if configured == 0:
        return False, "有効チャンネルの感情マッピング未設定"

    return True, ""


def check_scene_configured(scene: bpy.types.Scene) -> tuple[bool, str]:
    """Read-only. Safe to call from Panel.draw."""
    if not getattr(scene, "blipsync", None):
        return False, "BlipSync 未初期化。アドオンを再有効化してください。"

    settings = scene.blipsync
    targets = resolve_enabled_channel_targets(settings)
    if not targets:
        if not collect_channels_with_sound(scene):
            return False, "VSE に SOUND ストリップがありません"
        return False, "対象チャンネルを選択してください"

    channels = {t.channel for t in targets}
    if not channels_have_sound(scene, channels):
        return False, "選択チャンネルに SOUND ストリップがありません"

    if not settings.phoneme_mappings:
        return False, "音素マッピングがありません"

    configured = 0
    for target in targets:
        mapping = peek_channel_mapping(settings, target)
        if mapping and mapping_is_configured(mapping):
            configured += 1

    if configured == 0:
        return False, "有効チャンネルの音素マッピング未設定"

    return True, ""
