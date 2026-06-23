"""Blender operators."""

from __future__ import annotations

import bpy
from bpy.types import Menu, Operator

from .applicator import apply_weights
from .audio import clear_sound_cache
from .defaults import (
    check_emotion_configured,
    check_scene_configured,
    ensure_scene_defaults,
    get_channel_emotion_mapping,
    get_channel_mapping,
    resolve_enabled_channel_targets,
    sync_channels_from_sequencer,
)
from .bake_keyframes import BakeKeyframeTracker
from .bake_base_cache import capture_additive_bake_bases
from .handlers import suspend_realtime_handlers
from .blink_applicator import apply_blink_mapping
from .blink_engine import (
    blink_seed,
    build_blink_schedule,
    compute_blink_amount_from_schedule,
    compute_eyelid_jitter,
    eyelid_jitter_eye_phases,
    scene_time_at_frame,
)
from .defaults import (
    blink_is_configured,
    blink_mapping_is_configured,
    breathing_is_configured,
    breathing_mapping_is_configured,
    micro_motion_is_configured,
    micro_motion_mapping_is_configured,
)
from .breathing_engine import compute_breath_phase
from .micro_motion_engine import compute_micro_motion_state
from .motion_applicator import apply_breathing_mapping, apply_micro_motion_mapping
from .emotion_applicator import apply_emotion_weights
from .emotion_engine import clear_classifier_cache, get_emotion_engine
from .engine import get_engine
from .profile import clear_profile_cache
from .sequencer import channel_label, collect_channels_with_sound


class BLIpsync_OT_init_scene(Operator):
    bl_idname = "blipsync.init_scene"
    bl_label = "Initialize BlipSync Scene"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ensure_scene_defaults(context.scene)
        self.report({"INFO"}, "BlipSync 設定を初期化しました")
        return {"FINISHED"}


class BLIpsync_OT_sync_channels(Operator):
    bl_idname = "blipsync.sync_channels"
    bl_label = "Detect VSE Channels"
    bl_options = {"REGISTER", "UNDO"}

    replace: bpy.props.BoolProperty(name="既存を置換", default=False)

    def execute(self, context):
        added = sync_channels_from_sequencer(context.scene, replace=True)
        if added == 0 and not context.scene.blipsync.channel_targets:
            self.report({"WARNING"}, "SOUND があるチャンネルがありません")
        else:
            self.report({"INFO"}, f"チャンネル一覧を更新（追加 {added}）")
        return {"FINISHED"}


class BLIpsync_OT_add_channel(Operator):
    bl_idname = "blipsync.add_channel"
    bl_label = "Add Channel"
    bl_options = {"REGISTER", "UNDO"}

    channel: bpy.props.IntProperty(min=1, max=128, default=1)

    def execute(self, context):
        scene = context.scene
        settings = scene.blipsync
        channel_map = collect_channels_with_sound(scene)
        for item in settings.channel_targets:
            if item.channel == self.channel:
                self.report({"WARNING"}, f"Channel {self.channel} は既に登録済みです")
                return {"CANCELLED"}
        item = settings.channel_targets.add()
        item.channel = self.channel
        item.label = channel_label(self.channel, channel_map.get(self.channel))
        item.enabled = True
        item.profile_source = "MALE"
        item.mapping_index = 0
        item.emotion_mapping_index = 0
        return {"FINISHED"}


class BLIpsync_MT_channels_add(Menu):
    bl_label = "チャンネルを追加"
    bl_idname = "BLIPSYNC_MT_channels_add"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        channel_map = collect_channels_with_sound(scene)
        used = {t.channel for t in scene.blipsync.channel_targets}
        if not channel_map:
            layout.label(text="SOUND があるチャンネルなし")
            return
        for ch, strips in sorted(channel_map.items()):
            if ch in used:
                continue
            op = layout.operator("blipsync.add_channel", text=channel_label(ch, strips))
            op.channel = ch


class BLIpsync_MT_channel_mapping(Menu):
    bl_label = "音素マッピング"
    bl_idname = "BLIPSYNC_MT_channel_mapping"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blipsync
        channel_index = settings.channel_targets_index
        for i, mapping in enumerate(settings.phoneme_mappings):
            label = mapping.name or f"Mapping {i + 1}"
            op = layout.operator("blipsync.set_channel_mapping", text=label)
            op.channel_index = channel_index
            op.mapping_index = i


class BLIpsync_OT_set_channel_mapping(Operator):
    bl_idname = "blipsync.set_channel_mapping"
    bl_label = "Set Channel Mapping"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: bpy.props.IntProperty(default=-1)
    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        ch_idx = self.channel_index
        if ch_idx < 0:
            ch_idx = settings.channel_targets_index
        if ch_idx < 0 or ch_idx >= len(settings.channel_targets):
            return {"CANCELLED"}
        if self.mapping_index < 0 or self.mapping_index >= len(settings.phoneme_mappings):
            return {"CANCELLED"}
        settings.channel_targets[ch_idx].mapping_index = self.mapping_index
        return {"FINISHED"}


class BLIpsync_MT_channel_emotion_mapping(Menu):
    bl_label = "感情マッピング"
    bl_idname = "BLIPSYNC_MT_channel_emotion_mapping"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.blipsync
        channel_index = settings.channel_targets_index
        for i, mapping in enumerate(settings.emotion_mappings):
            label = mapping.name or f"Emotion {i + 1}"
            op = layout.operator("blipsync.set_channel_emotion_mapping", text=label)
            op.channel_index = channel_index
            op.mapping_index = i


class BLIpsync_OT_set_channel_emotion_mapping(Operator):
    bl_idname = "blipsync.set_channel_emotion_mapping"
    bl_label = "Set Channel Emotion Mapping"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: bpy.props.IntProperty(default=-1)
    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        ch_idx = self.channel_index
        if ch_idx < 0:
            ch_idx = settings.channel_targets_index
        if ch_idx < 0 or ch_idx >= len(settings.channel_targets):
            return {"CANCELLED"}
        if self.mapping_index < 0 or self.mapping_index >= len(settings.emotion_mappings):
            return {"CANCELLED"}
        settings.channel_targets[ch_idx].emotion_mapping_index = self.mapping_index
        return {"FINISHED"}


class BLIpsync_OT_remove_channel(Operator):
    bl_idname = "blipsync.remove_channel"
    bl_label = "Remove Channel"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        settings.channel_targets.remove(settings.channel_targets_index)
        settings.channel_targets_index = max(0, settings.channel_targets_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_phoneme_mapping(Operator):
    bl_idname = "blipsync.add_phoneme_mapping"
    bl_label = "Add Phoneme Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .defaults import ensure_phoneme_exprs_on

        settings = context.scene.blipsync
        mapping = settings.phoneme_mappings.add()
        mapping.name = f"Mapping {len(settings.phoneme_mappings)}"
        ensure_phoneme_exprs_on(mapping)
        settings.phoneme_mappings_index = len(settings.phoneme_mappings) - 1
        return {"FINISHED"}


class BLIpsync_OT_remove_phoneme_mapping(Operator):
    bl_idname = "blipsync.remove_phoneme_mapping"
    bl_label = "Remove Phoneme Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        if len(settings.phoneme_mappings) <= 1:
            self.report({"WARNING"}, "最低 1 つの音素マッピングが必要です")
            return {"CANCELLED"}
        settings.phoneme_mappings.remove(settings.phoneme_mappings_index)
        settings.phoneme_mappings_index = max(0, settings.phoneme_mappings_index - 1)
        for target in settings.channel_targets:
            target.mapping_index = min(target.mapping_index, len(settings.phoneme_mappings) - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_morph_bind(Operator):
    bl_idname = "blipsync.add_morph_bind"
    bl_label = "Add Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    phoneme_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.phoneme_mappings):
            return {"CANCELLED"}
        mapping = settings.phoneme_mappings[self.mapping_index]
        if self.phoneme_index < 0 or self.phoneme_index >= len(mapping.phoneme_exprs):
            return {"CANCELLED"}
        bind = mapping.phoneme_exprs[self.phoneme_index].binds.add()
        from .shape_key_utils import sync_morph_weight_ui

        sync_morph_weight_ui(bind)
        return {"FINISHED"}


class BLIpsync_OT_remove_morph_bind(Operator):
    bl_idname = "blipsync.remove_morph_bind"
    bl_label = "Remove Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    phoneme_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        expr = settings.phoneme_mappings[self.mapping_index].phoneme_exprs[self.phoneme_index]
        expr.binds.remove(expr.binds_index)
        expr.binds_index = max(0, expr.binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_pose_bind(Operator):
    bl_idname = "blipsync.add_pose_bind"
    bl_label = "Add Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    phoneme_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.phoneme_mappings):
            return {"CANCELLED"}
        mapping = settings.phoneme_mappings[self.mapping_index]
        if self.phoneme_index < 0 or self.phoneme_index >= len(mapping.phoneme_exprs):
            return {"CANCELLED"}
        mapping.phoneme_exprs[self.phoneme_index].pose_binds.add()
        bind = mapping.phoneme_exprs[self.phoneme_index].pose_binds[-1]
        from .pose_motion import default_motion_amount

        bind.motion_amount = default_motion_amount(bind.pose_axis)
        return {"FINISHED"}


class BLIpsync_OT_remove_pose_bind(Operator):
    bl_idname = "blipsync.remove_pose_bind"
    bl_label = "Remove Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    phoneme_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        expr = settings.phoneme_mappings[self.mapping_index].phoneme_exprs[self.phoneme_index]
        expr.pose_binds.remove(expr.pose_binds_index)
        expr.pose_binds_index = max(0, expr.pose_binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_emotion_mapping(Operator):
    bl_idname = "blipsync.add_emotion_mapping"
    bl_label = "Add Emotion Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .defaults import ensure_emotion_exprs_on

        settings = context.scene.blipsync
        mapping = settings.emotion_mappings.add()
        mapping.name = f"Emotion {len(settings.emotion_mappings)}"
        ensure_emotion_exprs_on(mapping)
        settings.emotion_mappings_index = len(settings.emotion_mappings) - 1
        return {"FINISHED"}


class BLIpsync_OT_remove_emotion_mapping(Operator):
    bl_idname = "blipsync.remove_emotion_mapping"
    bl_label = "Remove Emotion Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        if len(settings.emotion_mappings) <= 1:
            self.report({"WARNING"}, "最低 1 つの感情マッピングが必要です")
            return {"CANCELLED"}
        settings.emotion_mappings.remove(settings.emotion_mappings_index)
        settings.emotion_mappings_index = max(0, settings.emotion_mappings_index - 1)
        for target in settings.channel_targets:
            target.emotion_mapping_index = min(
                target.emotion_mapping_index,
                len(settings.emotion_mappings) - 1,
            )
        return {"FINISHED"}


class BLIpsync_OT_add_emotion_morph_bind(Operator):
    bl_idname = "blipsync.add_emotion_morph_bind"
    bl_label = "Add Emotion Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    emotion_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.emotion_mappings):
            return {"CANCELLED"}
        mapping = settings.emotion_mappings[self.mapping_index]
        if self.emotion_index < 0 or self.emotion_index >= len(mapping.emotion_exprs):
            return {"CANCELLED"}
        bind = mapping.emotion_exprs[self.emotion_index].binds.add()
        from .shape_key_utils import sync_morph_weight_ui

        sync_morph_weight_ui(bind)
        return {"FINISHED"}


class BLIpsync_OT_remove_emotion_morph_bind(Operator):
    bl_idname = "blipsync.remove_emotion_morph_bind"
    bl_label = "Remove Emotion Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    emotion_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        expr = settings.emotion_mappings[self.mapping_index].emotion_exprs[self.emotion_index]
        expr.binds.remove(expr.binds_index)
        expr.binds_index = max(0, expr.binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_emotion_pose_bind(Operator):
    bl_idname = "blipsync.add_emotion_pose_bind"
    bl_label = "Add Emotion Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    emotion_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.emotion_mappings):
            return {"CANCELLED"}
        mapping = settings.emotion_mappings[self.mapping_index]
        if self.emotion_index < 0 or self.emotion_index >= len(mapping.emotion_exprs):
            return {"CANCELLED"}
        mapping.emotion_exprs[self.emotion_index].pose_binds.add()
        bind = mapping.emotion_exprs[self.emotion_index].pose_binds[-1]
        from .pose_motion import default_motion_amount

        bind.motion_amount = default_motion_amount(bind.pose_axis)
        return {"FINISHED"}


class BLIpsync_OT_remove_emotion_pose_bind(Operator):
    bl_idname = "blipsync.remove_emotion_pose_bind"
    bl_label = "Remove Emotion Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    emotion_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        expr = settings.emotion_mappings[self.mapping_index].emotion_exprs[self.emotion_index]
        expr.pose_binds.remove(expr.pose_binds_index)
        expr.pose_binds_index = max(0, expr.pose_binds_index - 1)
        return {"FINISHED"}


def _blink_eye_slot(settings, mapping_index: int, eye_index: int):
    mapping = settings.blink_mappings[mapping_index]
    return mapping.left_eye if eye_index == 0 else mapping.right_eye


class BLIpsync_OT_add_blink_mapping(Operator):
    bl_idname = "blipsync.add_blink_mapping"
    bl_label = "Add Blink Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .defaults import ensure_blink_eye_slot

        settings = context.scene.blipsync
        mapping = settings.blink_mappings.add()
        mapping.name = f"Blink {len(settings.blink_mappings)}"
        ensure_blink_eye_slot(mapping.left_eye)
        ensure_blink_eye_slot(mapping.right_eye)
        settings.blink_mappings_index = len(settings.blink_mappings) - 1
        return {"FINISHED"}


class BLIpsync_OT_remove_blink_mapping(Operator):
    bl_idname = "blipsync.remove_blink_mapping"
    bl_label = "Remove Blink Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        if len(settings.blink_mappings) <= 1:
            self.report({"WARNING"}, "最低 1 つの瞬きマッピングが必要です")
            return {"CANCELLED"}
        settings.blink_mappings.remove(settings.blink_mappings_index)
        settings.blink_mappings_index = max(0, settings.blink_mappings_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_blink_morph_bind(Operator):
    bl_idname = "blipsync.add_blink_morph_bind"
    bl_label = "Add Blink Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    eye_index: bpy.props.IntProperty(default=0, min=0, max=1)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.blink_mappings):
            return {"CANCELLED"}
        eye_slot = _blink_eye_slot(settings, self.mapping_index, self.eye_index)
        bind = eye_slot.binds.add()
        from .shape_key_utils import sync_morph_weight_ui

        sync_morph_weight_ui(bind)
        return {"FINISHED"}


class BLIpsync_OT_remove_blink_morph_bind(Operator):
    bl_idname = "blipsync.remove_blink_morph_bind"
    bl_label = "Remove Blink Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    eye_index: bpy.props.IntProperty(default=0, min=0, max=1)

    def execute(self, context):
        settings = context.scene.blipsync
        eye_slot = _blink_eye_slot(settings, self.mapping_index, self.eye_index)
        eye_slot.binds.remove(eye_slot.binds_index)
        eye_slot.binds_index = max(0, eye_slot.binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_blink_pose_bind(Operator):
    bl_idname = "blipsync.add_blink_pose_bind"
    bl_label = "Add Blink Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    eye_index: bpy.props.IntProperty(default=0, min=0, max=1)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.blink_mappings):
            return {"CANCELLED"}
        eye_slot = _blink_eye_slot(settings, self.mapping_index, self.eye_index)
        eye_slot.pose_binds.add()
        bind = eye_slot.pose_binds[-1]
        from .pose_motion import default_motion_amount

        bind.motion_amount = default_motion_amount(bind.pose_axis)
        return {"FINISHED"}


class BLIpsync_OT_remove_blink_pose_bind(Operator):
    bl_idname = "blipsync.remove_blink_pose_bind"
    bl_label = "Remove Blink Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    eye_index: bpy.props.IntProperty(default=0, min=0, max=1)

    def execute(self, context):
        settings = context.scene.blipsync
        eye_slot = _blink_eye_slot(settings, self.mapping_index, self.eye_index)
        eye_slot.pose_binds.remove(eye_slot.pose_binds_index)
        eye_slot.pose_binds_index = max(0, eye_slot.pose_binds_index - 1)
        return {"FINISHED"}


MICRO_MOTION_SLOT_ATTRS = (
    "head",
    "left_eye",
    "right_eye",
    "look_up",
    "look_down",
    "look_left",
    "look_right",
    "eyebrows",
    "mouth_open",
)


def _micro_motion_slot(settings, mapping_index: int, slot_attr: str):
    mapping = settings.micro_motion_mappings[mapping_index]
    if slot_attr not in MICRO_MOTION_SLOT_ATTRS:
        raise ValueError(f"Unknown micro motion slot: {slot_attr}")
    return getattr(mapping, slot_attr)


class BLIpsync_OT_add_breathing_mapping(Operator):
    bl_idname = "blipsync.add_breathing_mapping"
    bl_label = "Add Breathing Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .defaults import ensure_bind_slot

        settings = context.scene.blipsync
        mapping = settings.breathing_mappings.add()
        mapping.name = f"Breathing {len(settings.breathing_mappings)}"
        ensure_bind_slot(mapping.targets)
        settings.breathing_mappings_index = len(settings.breathing_mappings) - 1
        return {"FINISHED"}


class BLIpsync_OT_remove_breathing_mapping(Operator):
    bl_idname = "blipsync.remove_breathing_mapping"
    bl_label = "Remove Breathing Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        if len(settings.breathing_mappings) <= 1:
            self.report({"WARNING"}, "最低 1 つの呼吸マッピングが必要です")
            return {"CANCELLED"}
        settings.breathing_mappings.remove(settings.breathing_mappings_index)
        settings.breathing_mappings_index = max(0, settings.breathing_mappings_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_breathing_morph_bind(Operator):
    bl_idname = "blipsync.add_breathing_morph_bind"
    bl_label = "Add Breathing Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.breathing_mappings):
            return {"CANCELLED"}
        bind = settings.breathing_mappings[self.mapping_index].targets.binds.add()
        from .shape_key_utils import sync_morph_weight_ui

        sync_morph_weight_ui(bind)
        return {"FINISHED"}


class BLIpsync_OT_remove_breathing_morph_bind(Operator):
    bl_idname = "blipsync.remove_breathing_morph_bind"
    bl_label = "Remove Breathing Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        slot = settings.breathing_mappings[self.mapping_index].targets
        slot.binds.remove(slot.binds_index)
        slot.binds_index = max(0, slot.binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_breathing_pose_bind(Operator):
    bl_idname = "blipsync.add_breathing_pose_bind"
    bl_label = "Add Breathing Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.breathing_mappings):
            return {"CANCELLED"}
        settings.breathing_mappings[self.mapping_index].targets.pose_binds.add()
        bind = settings.breathing_mappings[self.mapping_index].targets.pose_binds[-1]
        from .pose_motion import default_motion_amount

        bind.motion_amount = default_motion_amount(bind.pose_axis)
        return {"FINISHED"}


class BLIpsync_OT_remove_breathing_pose_bind(Operator):
    bl_idname = "blipsync.remove_breathing_pose_bind"
    bl_label = "Remove Breathing Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.blipsync
        slot = settings.breathing_mappings[self.mapping_index].targets
        slot.pose_binds.remove(slot.pose_binds_index)
        slot.pose_binds_index = max(0, slot.pose_binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_micro_motion_mapping(Operator):
    bl_idname = "blipsync.add_micro_motion_mapping"
    bl_label = "Add Micro Motion Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .defaults import ensure_bind_slot

        settings = context.scene.blipsync
        mapping = settings.micro_motion_mappings.add()
        mapping.name = f"Micro Motion {len(settings.micro_motion_mappings)}"
        for attr in MICRO_MOTION_SLOT_ATTRS:
            ensure_bind_slot(getattr(mapping, attr))
        settings.micro_motion_mappings_index = len(settings.micro_motion_mappings) - 1
        return {"FINISHED"}


class BLIpsync_OT_remove_micro_motion_mapping(Operator):
    bl_idname = "blipsync.remove_micro_motion_mapping"
    bl_label = "Remove Micro Motion Mapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.blipsync
        if len(settings.micro_motion_mappings) <= 1:
            self.report({"WARNING"}, "最低 1 つのマイクロモーションマッピングが必要です")
            return {"CANCELLED"}
        settings.micro_motion_mappings.remove(settings.micro_motion_mappings_index)
        settings.micro_motion_mappings_index = max(0, settings.micro_motion_mappings_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_micro_motion_morph_bind(Operator):
    bl_idname = "blipsync.add_micro_motion_morph_bind"
    bl_label = "Add Micro Motion Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    slot_attr: bpy.props.StringProperty(default="head")

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.micro_motion_mappings):
            return {"CANCELLED"}
        slot = _micro_motion_slot(settings, self.mapping_index, self.slot_attr)
        bind = slot.binds.add()
        from .shape_key_utils import sync_morph_weight_ui

        sync_morph_weight_ui(bind)
        return {"FINISHED"}


class BLIpsync_OT_remove_micro_motion_morph_bind(Operator):
    bl_idname = "blipsync.remove_micro_motion_morph_bind"
    bl_label = "Remove Micro Motion Morph Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    slot_attr: bpy.props.StringProperty(default="head")

    def execute(self, context):
        settings = context.scene.blipsync
        slot = _micro_motion_slot(settings, self.mapping_index, self.slot_attr)
        slot.binds.remove(slot.binds_index)
        slot.binds_index = max(0, slot.binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_add_micro_motion_pose_bind(Operator):
    bl_idname = "blipsync.add_micro_motion_pose_bind"
    bl_label = "Add Micro Motion Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    slot_attr: bpy.props.StringProperty(default="head")

    def execute(self, context):
        settings = context.scene.blipsync
        if self.mapping_index < 0 or self.mapping_index >= len(settings.micro_motion_mappings):
            return {"CANCELLED"}
        _micro_motion_slot(settings, self.mapping_index, self.slot_attr).pose_binds.add()
        bind = _micro_motion_slot(settings, self.mapping_index, self.slot_attr).pose_binds[-1]
        from .pose_motion import default_motion_amount

        bind.motion_amount = default_motion_amount(bind.pose_axis)
        return {"FINISHED"}


class BLIpsync_OT_remove_micro_motion_pose_bind(Operator):
    bl_idname = "blipsync.remove_micro_motion_pose_bind"
    bl_label = "Remove Micro Motion Pose Bind"
    bl_options = {"REGISTER", "UNDO"}

    mapping_index: bpy.props.IntProperty(default=0)
    slot_attr: bpy.props.StringProperty(default="head")

    def execute(self, context):
        settings = context.scene.blipsync
        slot = _micro_motion_slot(settings, self.mapping_index, self.slot_attr)
        slot.pose_binds.remove(slot.pose_binds_index)
        slot.pose_binds_index = max(0, slot.pose_binds_index - 1)
        return {"FINISHED"}


class BLIpsync_OT_bake(Operator):
    bl_idname = "blipsync.bake"
    bl_label = "Bake Lip Sync"
    bl_options = {"REGISTER", "UNDO"}

    bake_lip: bpy.props.BoolProperty(name="リップ", default=True)
    bake_emotion: bpy.props.BoolProperty(name="感情", default=True)

    def execute(self, context):
        scene = context.scene
        settings = scene.blipsync
        ensure_scene_defaults(scene)
        bake_lip = self.bake_lip
        bake_emotion = self.bake_emotion
        if not bake_lip and not bake_emotion:
            self.report({"WARNING"}, "ベイク対象を選択してください")
            return {"CANCELLED"}
        if bake_lip:
            ok, msg = check_scene_configured(scene)
            if not ok:
                self.report({"WARNING"}, msg)
                return {"CANCELLED"}
        if bake_emotion:
            ok, msg = check_emotion_configured(scene)
            if not ok:
                self.report({"WARNING"}, msg)
                return {"CANCELLED"}

        lip_engine = get_engine()
        emotion_engine = get_emotion_engine()
        if bake_lip:
            lip_engine.reset_smoothing()
            clear_sound_cache()
            clear_profile_cache()
        if bake_emotion:
            emotion_engine.reset_smoothing()
            clear_classifier_cache()

        targets = resolve_enabled_channel_targets(settings)
        if settings.bake_use_range:
            start = settings.bake_frame_start
            end = settings.bake_frame_end
        else:
            start = scene.frame_start
            end = scene.frame_end
        step = max(1, settings.bake_step)
        fps = scene.render.fps / scene.render.fps_base
        frames = list(range(start, end + 1, step))
        total = max(1, len(frames))
        keyframe_tracker = BakeKeyframeTracker(step=step, start_frame=start)

        phoneme_mappings = []
        emotion_mappings = []
        seen_phoneme: set[int] = set()
        seen_emotion: set[int] = set()
        for target in targets:
            if bake_lip:
                mapping = get_channel_mapping(settings, target)
                if mapping is not None:
                    key = id(mapping)
                    if key not in seen_phoneme:
                        seen_phoneme.add(key)
                        phoneme_mappings.append(mapping)
            if bake_emotion:
                emotion_mapping = get_channel_emotion_mapping(settings, target)
                if emotion_mapping is not None:
                    key = id(emotion_mapping)
                    if key not in seen_emotion:
                        seen_emotion.add(key)
                        emotion_mappings.append(emotion_mapping)

        base_cache = capture_additive_bake_bases(
            scene,
            frames,
            phoneme_mappings=phoneme_mappings if bake_lip else None,
            emotion_mappings=emotion_mappings if bake_emotion else None,
        )

        wm = context.window_manager
        wm.progress_begin(0, total)
        original_frame = scene.frame_current
        try:
            with suspend_realtime_handlers():
                for idx, frame in enumerate(frames):
                    scene.frame_set(frame)
                    for target in targets:
                        if bake_lip:
                            mapping = get_channel_mapping(settings, target)
                            if mapping is None:
                                continue
                            result = lip_engine.analyze_channel(scene, frame, target)
                            weights = lip_engine.update_smoothed_weights(
                                scene, result, step / fps, target.channel, mapping,
                            )
                            apply_weights(
                                scene,
                                weights,
                                mapping,
                                insert_keyframes=True,
                                frame=frame,
                                keyframe_tracker=keyframe_tracker,
                                base_cache=base_cache,
                            )
                        if bake_emotion:
                            emotion_mapping = get_channel_emotion_mapping(settings, target)
                            if emotion_mapping is None:
                                continue
                            emotion_result = emotion_engine.analyze_channel(scene, frame, target)
                            emotion_weights = emotion_engine.update_smoothed_weights(
                                scene, emotion_result, step / fps, target.channel, emotion_mapping,
                            )
                            apply_emotion_weights(
                                scene,
                                emotion_weights,
                                emotion_mapping,
                                insert_keyframes=True,
                                frame=frame,
                                keyframe_tracker=keyframe_tracker,
                                base_cache=base_cache,
                            )
                    if idx % 10 == 0:
                        wm.progress_update(idx)
        finally:
            scene.frame_set(original_frame)
            wm.progress_end()

        if bake_lip and bake_emotion:
            label = "リップ + 感情"
            settings.enabled = False
            settings.emotion_enabled = False
        elif bake_lip:
            label = "リップ"
            settings.enabled = False
        else:
            label = "感情"
            settings.emotion_enabled = False
        self.report({"INFO"}, f"{label} ベイク完了: {total} frames（リアルタイム同期を OFF）")
        return {"FINISHED"}

    def invoke(self, context, event):
        settings = context.scene.blipsync
        scene = context.scene
        if settings.bake_frame_end < settings.bake_frame_start:
            settings.bake_frame_end = scene.frame_end
            settings.bake_frame_start = scene.frame_start
        return self.execute(context)


class BLIpsync_OT_bake_blink(Operator):
    bl_idname = "blipsync.bake_blink"
    bl_label = "瞬きをベイク"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        settings = scene.blipsync
        if not settings.blink_enabled:
            self.report({"WARNING"}, "Auto Blink が無効です")
            return {"CANCELLED"}
        if not blink_is_configured(settings):
            self.report({"WARNING"}, "瞬きマッピングが未設定です")
            return {"CANCELLED"}

        blink_mappings = [
            mapping for mapping in settings.blink_mappings if blink_mapping_is_configured(mapping)
        ]
        if not blink_mappings:
            self.report({"WARNING"}, "瞬きマッピングが未設定です")
            return {"CANCELLED"}

        if settings.blink_bake_use_range:
            start = settings.blink_bake_frame_start
            end = settings.blink_bake_frame_end
        else:
            start = scene.frame_start
            end = scene.frame_end
        step = max(1, settings.blink_bake_step)
        frames = list(range(start, end + 1, step))
        total = max(1, len(frames))
        fps = scene.render.fps / scene.render.fps_base
        end_time_sec = scene_time_at_frame(scene, end)
        keyframe_tracker = BakeKeyframeTracker(step=step, start_frame=start)
        base_cache = capture_additive_bake_bases(
            scene, frames, blink_mappings=blink_mappings,
        )

        blink_plans = []
        for mapping in blink_mappings:
            seed = blink_seed(mapping, scene)
            schedule, close_d, open_d = build_blink_schedule(settings, seed, end_time_sec)
            phase_left, phase_right = eyelid_jitter_eye_phases(seed)
            blink_plans.append({
                "mapping": mapping,
                "schedule": schedule,
                "close_d": close_d,
                "open_d": open_d,
                "seed": seed,
                "phase_left": phase_left,
                "phase_right": phase_right,
            })

        wm = context.window_manager
        wm.progress_begin(0, total)
        original_frame = scene.frame_current
        try:
            with suspend_realtime_handlers():
                for idx, frame in enumerate(frames):
                    scene.frame_set(frame)
                    time_sec = frame / max(fps, 1e-8)
                    for plan in blink_plans:
                        mapping = plan["mapping"]
                        amount = compute_blink_amount_from_schedule(
                            time_sec, plan["schedule"], plan["close_d"], plan["open_d"],
                        )
                        jitter_left, jitter_right = 0.0, 0.0
                        jitter_amount = float(mapping.fac_jitter_amount)
                        jitter_speed = float(settings.blink_eyelid_jitter_speed)
                        if jitter_amount > 1e-8 and jitter_speed > 1e-8:
                            jitter_left = compute_eyelid_jitter(
                                time_sec, plan["seed"], jitter_speed, eye_phase=plan["phase_left"],
                            )
                            jitter_right = compute_eyelid_jitter(
                                time_sec, plan["seed"], jitter_speed, eye_phase=plan["phase_right"],
                            )
                        apply_blink_mapping(
                            scene,
                            amount,
                            mapping,
                            fac_jitter_left=jitter_left,
                            fac_jitter_right=jitter_right,
                            insert_keyframes=True,
                            frame=frame,
                            keyframe_tracker=keyframe_tracker,
                            base_cache=base_cache,
                        )
                    if idx % 10 == 0:
                        wm.progress_update(idx)
        finally:
            scene.frame_set(original_frame)
            wm.progress_end()

        settings.blink_enabled = False
        self.report({"INFO"}, f"瞬きベイク完了: {total} frames（Auto Blink を OFF）")
        return {"FINISHED"}


class BLIpsync_OT_bake_motion(Operator):
    bl_idname = "blipsync.bake_motion"
    bl_label = "Bake Motion"
    bl_options = {"REGISTER", "UNDO"}

    bake_breathing: bpy.props.BoolProperty(name="呼吸", default=True)
    bake_micro_motion: bpy.props.BoolProperty(name="マイクロモーション", default=True)

    def execute(self, context):
        scene = context.scene
        settings = scene.blipsync
        bake_breathing = self.bake_breathing
        bake_micro_motion = self.bake_micro_motion
        if not bake_breathing and not bake_micro_motion:
            self.report({"WARNING"}, "ベイク対象を選択してください")
            return {"CANCELLED"}

        breathing_mappings = []
        micro_mappings = []
        if bake_breathing:
            if not settings.breathing_enabled:
                self.report({"WARNING"}, "Breathing が無効です")
                return {"CANCELLED"}
            if not breathing_is_configured(settings):
                self.report({"WARNING"}, "呼吸マッピングが未設定です")
                return {"CANCELLED"}
            breathing_mappings = [
                m for m in settings.breathing_mappings if breathing_mapping_is_configured(m)
            ]
            if not breathing_mappings:
                self.report({"WARNING"}, "呼吸マッピングが未設定です")
                return {"CANCELLED"}

        if bake_micro_motion:
            if not settings.micro_motion_enabled:
                self.report({"WARNING"}, "Micro Motion が無効です")
                return {"CANCELLED"}
            if not micro_motion_is_configured(settings):
                self.report({"WARNING"}, "マイクロモーションマッピングが未設定です")
                return {"CANCELLED"}
            micro_mappings = [
                m for m in settings.micro_motion_mappings if micro_motion_mapping_is_configured(m)
            ]
            if not micro_mappings:
                self.report({"WARNING"}, "マイクロモーションマッピングが未設定です")
                return {"CANCELLED"}

        if settings.motion_bake_use_range:
            start = settings.motion_bake_frame_start
            end = settings.motion_bake_frame_end
        else:
            start = scene.frame_start
            end = scene.frame_end
        step = max(1, settings.motion_bake_step)
        frames = list(range(start, end + 1, step))
        total = max(1, len(frames))
        fps = scene.render.fps / scene.render.fps_base
        keyframe_tracker = BakeKeyframeTracker(step=step, start_frame=start)

        if bake_micro_motion:
            from .micro_pose_base import reset_micro_pose_bases

            reset_micro_pose_bases()
        base_cache = capture_additive_bake_bases(
            scene,
            frames,
            breathing_mappings=breathing_mappings or None,
            micro_motion_mappings=micro_mappings or None,
        )

        wm = context.window_manager
        wm.progress_begin(0, total)
        original_frame = scene.frame_current
        try:
            with suspend_realtime_handlers():
                for idx, frame in enumerate(frames):
                    scene.frame_set(frame)
                    time_sec = frame / max(fps, 1e-8)
                    if bake_breathing:
                        phase = compute_breath_phase(
                            time_sec,
                            settings.breathing_bpm,
                            settings.breathing_exhale_ratio,
                        )
                        for mapping in breathing_mappings:
                            apply_breathing_mapping(
                                scene,
                                phase,
                                mapping,
                                insert_keyframes=True,
                                frame=frame,
                                keyframe_tracker=keyframe_tracker,
                                base_cache=base_cache,
                            )
                    if bake_micro_motion:
                        for mapping in micro_mappings:
                            state = compute_micro_motion_state(time_sec, mapping, scene, settings)
                            apply_micro_motion_mapping(
                                scene,
                                state,
                                mapping,
                                insert_keyframes=True,
                                frame=frame,
                                keyframe_tracker=keyframe_tracker,
                                base_cache=base_cache,
                            )
                    if idx % 10 == 0:
                        wm.progress_update(idx)
        finally:
            scene.frame_set(original_frame)
            wm.progress_end()

        if bake_breathing and bake_micro_motion:
            label = "呼吸 + マイクロモーション"
            settings.breathing_enabled = False
            settings.micro_motion_enabled = False
        elif bake_breathing:
            label = "呼吸"
            settings.breathing_enabled = False
        else:
            label = "マイクロモーション"
            settings.micro_motion_enabled = False
        self.report({"INFO"}, f"{label} ベイク完了: {total} frames（リアルタイム同期を OFF）")
        return {"FINISHED"}

    def invoke(self, context, event):
        settings = context.scene.blipsync
        scene = context.scene
        if settings.motion_bake_frame_end < settings.motion_bake_frame_start:
            settings.motion_bake_frame_end = scene.frame_end
            settings.motion_bake_frame_start = scene.frame_start
        return self.execute(context)


class BLIpsync_OT_refresh_emotion_deps(Operator):
    bl_idname = "blipsync.refresh_emotion_deps"
    bl_label = "Re-detect Emotion Dependencies"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from .deps_installer import verify_emotion_deps

        ok, msg = verify_emotion_deps()
        if ok:
            self.report({"INFO"}, "Emotion libraries ready")
        else:
            self.report({"WARNING"}, msg[:240])
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class BLIpsync_OT_install_emotion_deps(Operator):
    bl_idname = "blipsync.install_emotion_deps"
    bl_label = "Install Emotion Dependencies"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from .deps_installer import get_install_status, start_install

        status = start_install(force=True)
        if status == "installing":
            self.report({"INFO"}, "onnxruntime をインストール中（bAnima パネルで進捗を確認）")
        elif status == "ok":
            self.report({"INFO"}, "Libraries already installed")
        elif status == "failed":
            from .deps_installer import get_install_error
            self.report({"ERROR"}, get_install_error() or "Install failed")
        return {"FINISHED"}


class BLIpsync_OT_reload_profile(Operator):
    bl_idname = "blipsync.reload_profile"
    bl_label = "Reload Profile"
    bl_options = {"REGISTER"}

    def execute(self, context):
        clear_profile_cache()
        get_engine().reset_smoothing()
        get_emotion_engine().reset_smoothing()
        clear_classifier_cache()
        clear_sound_cache()
        self.report({"INFO"}, "Profile cache cleared")
        return {"FINISHED"}


class BLIpsync_OT_profile_tick(Operator):
    bl_idname = "blipsync.profile_tick"
    bl_label = "Profile Current Frame"
    bl_options = {"REGISTER"}

    def execute(self, context):
        from .handlers import profile_tick_at_frame

        scene = context.scene
        if not getattr(scene, "blipsync", None):
            self.report({"WARNING"}, "blipsync が未初期化です")
            return {"CANCELLED"}
        report, path = profile_tick_at_frame(scene, scene.frame_current)
        print(report)
        total_line = next((line for line in report.splitlines() if "TOTAL:" in line), "")
        self.report(
            {"INFO"},
            f"計測完了 {total_line.strip()} — ログ: {path}",
        )
        return {"FINISHED"}


classes = (
    BLIpsync_OT_init_scene,
    BLIpsync_OT_sync_channels,
    BLIpsync_OT_add_channel,
    BLIpsync_MT_channels_add,
    BLIpsync_MT_channel_mapping,
    BLIpsync_OT_set_channel_mapping,
    BLIpsync_MT_channel_emotion_mapping,
    BLIpsync_OT_set_channel_emotion_mapping,
    BLIpsync_OT_remove_channel,
    BLIpsync_OT_add_phoneme_mapping,
    BLIpsync_OT_remove_phoneme_mapping,
    BLIpsync_OT_add_emotion_mapping,
    BLIpsync_OT_remove_emotion_mapping,
    BLIpsync_OT_add_morph_bind,
    BLIpsync_OT_remove_morph_bind,
    BLIpsync_OT_add_pose_bind,
    BLIpsync_OT_remove_pose_bind,
    BLIpsync_OT_add_emotion_morph_bind,
    BLIpsync_OT_remove_emotion_morph_bind,
    BLIpsync_OT_add_emotion_pose_bind,
    BLIpsync_OT_remove_emotion_pose_bind,
    BLIpsync_OT_add_blink_mapping,
    BLIpsync_OT_remove_blink_mapping,
    BLIpsync_OT_add_blink_morph_bind,
    BLIpsync_OT_remove_blink_morph_bind,
    BLIpsync_OT_add_blink_pose_bind,
    BLIpsync_OT_remove_blink_pose_bind,
    BLIpsync_OT_add_breathing_mapping,
    BLIpsync_OT_remove_breathing_mapping,
    BLIpsync_OT_add_breathing_morph_bind,
    BLIpsync_OT_remove_breathing_morph_bind,
    BLIpsync_OT_add_breathing_pose_bind,
    BLIpsync_OT_remove_breathing_pose_bind,
    BLIpsync_OT_add_micro_motion_mapping,
    BLIpsync_OT_remove_micro_motion_mapping,
    BLIpsync_OT_add_micro_motion_morph_bind,
    BLIpsync_OT_remove_micro_motion_morph_bind,
    BLIpsync_OT_add_micro_motion_pose_bind,
    BLIpsync_OT_remove_micro_motion_pose_bind,
    BLIpsync_OT_bake,
    BLIpsync_OT_bake_blink,
    BLIpsync_OT_bake_motion,
    BLIpsync_OT_install_emotion_deps,
    BLIpsync_OT_refresh_emotion_deps,
    BLIpsync_OT_reload_profile,
    BLIpsync_OT_profile_tick,
)


def register():
    from .registration import register_classes
    register_classes(classes)


def unregister():
    from .registration import unregister_classes
    unregister_classes(classes)
