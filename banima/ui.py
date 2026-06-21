"""bAnima stacked sidebar panels."""

from __future__ import annotations

import bpy
from bpy.types import Panel

try:
    from blipsync.ui import (
        _draw_advanced,
        _draw_basic,
        _draw_bake,
        _draw_blink_advanced,
        _draw_blink_basic,
        _draw_blink_bake,
        _draw_blink_mapping,
        _draw_breathing_basic,
        _draw_breathing_bake,
        _draw_breathing_mapping,
        _draw_breathing_params,
        _draw_emotion_mapping,
        _draw_micro_motion_mapping,
        _draw_micro_motion_params,
        _draw_phoneme_mapping,
        _panel_poll,
        _settings_or_init,
    )
    from blipsync.registration import register_classes, unregister_classes
except ImportError:
    from .blipsync.ui import (
        _draw_advanced,
        _draw_basic,
        _draw_bake,
        _draw_blink_advanced,
        _draw_blink_basic,
        _draw_blink_bake,
        _draw_blink_mapping,
        _draw_breathing_basic,
        _draw_breathing_bake,
        _draw_breathing_mapping,
        _draw_breathing_params,
        _draw_emotion_mapping,
        _draw_micro_motion_mapping,
        _draw_micro_motion_params,
        _draw_phoneme_mapping,
        _panel_poll,
        _settings_or_init,
    )
    from .blipsync.registration import register_classes, unregister_classes

_PANEL_ID_PREFIX = "BANIMA_PT_"


class BAnima_PT_lip_emotion(Panel):
    bl_label = "Lip & Emotion Sync"
    bl_idname = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="SPEAKER")

    def draw(self, _context):
        self.layout.label(text="VSE 音声からリップシンクと感情を同期", icon="BLANK1")


class BAnima_PT_lip_basic(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_lip_basic"
    bl_parent_id = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_basic(self.layout, scene, settings)


class BAnima_PT_phoneme(Panel):
    bl_label = "音素マッピング A / I / U / E / O / -"
    bl_idname = "BANIMA_PT_phoneme"
    bl_parent_id = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_phoneme_mapping(self.layout, settings)


class BAnima_PT_emotion(Panel):
    bl_label = "感情マッピング Happy / Sad / Angry / Neutral"
    bl_idname = "BANIMA_PT_emotion"
    bl_parent_id = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_emotion_mapping(self.layout, settings)


class BAnima_PT_advanced(Panel):
    bl_label = "詳細設定"
    bl_idname = "BANIMA_PT_advanced"
    bl_parent_id = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_advanced(self.layout, settings)


class BAnima_PT_bake(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_bake"
    bl_parent_id = "BANIMA_PT_lip_emotion"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_bake(self.layout, scene, settings)


class BAnima_PT_auto_blink(Panel):
    bl_label = "Auto Blink"
    bl_idname = "BANIMA_PT_auto_blink"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="HIDE_OFF")

    def draw(self, _context):
        self.layout.label(text="自動瞬きと瞼の微細揺らぎ", icon="BLANK1")


class BAnima_PT_blink_basic(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_blink_basic"
    bl_parent_id = "BANIMA_PT_auto_blink"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_basic(self.layout, settings)


class BAnima_PT_blink_mapping(Panel):
    bl_label = "瞬きマッピング"
    bl_idname = "BANIMA_PT_blink_mapping"
    bl_parent_id = "BANIMA_PT_auto_blink"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_mapping(self.layout, settings)


class BAnima_PT_blink_advanced(Panel):
    bl_label = "詳細設定"
    bl_idname = "BANIMA_PT_blink_advanced"
    bl_parent_id = "BANIMA_PT_auto_blink"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_advanced(self.layout, settings)


class BAnima_PT_blink_bake(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_blink_bake"
    bl_parent_id = "BANIMA_PT_auto_blink"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_blink_bake(self.layout, scene, settings)


class BAnima_PT_breathing(Panel):
    bl_label = "Breathing & Micro Motion"
    bl_idname = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="FORCE_TURBULENCE")

    def draw(self, _context):
        self.layout.label(text="呼吸・頭部揺れ・視線サッカード・顔の微細動作", icon="BLANK1")


class BAnima_PT_breathing_basic(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_breathing_basic"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_basic(self.layout, settings)


class BAnima_PT_breathing_mapping(Panel):
    bl_label = "呼吸マッピング"
    bl_idname = "BANIMA_PT_breathing_mapping"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_mapping(self.layout, settings)


class BAnima_PT_micro_motion_mapping(Panel):
    bl_label = "マイクロモーションマッピング"
    bl_idname = "BANIMA_PT_micro_motion_mapping"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_micro_motion_mapping(self.layout, settings)


class BAnima_PT_breathing_params(Panel):
    bl_label = "呼吸設定"
    bl_idname = "BANIMA_PT_breathing_params"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_params(self.layout, settings)


class BAnima_PT_micro_motion_params(Panel):
    bl_label = "マイクロモーション設定"
    bl_idname = "BANIMA_PT_micro_motion_params"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_micro_motion_params(self.layout, settings)


class BAnima_PT_breathing_bake(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_breathing_bake"
    bl_parent_id = "BANIMA_PT_breathing"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_breathing_bake(self.layout, scene, settings)


class BAnima_PT_lip_emotion_seq(Panel):
    bl_label = "Lip & Emotion Sync"
    bl_idname = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="SPEAKER")

    def draw(self, _context):
        self.layout.label(text="VSE 音声からリップシンクと感情を同期", icon="BLANK1")


class BAnima_PT_lip_basic_seq(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_lip_basic_seq"
    bl_parent_id = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_basic(self.layout, scene, settings)


class BAnima_PT_phoneme_seq(Panel):
    bl_label = "音素マッピング A / I / U / E / O / -"
    bl_idname = "BANIMA_PT_phoneme_seq"
    bl_parent_id = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_phoneme_mapping(self.layout, settings)


class BAnima_PT_emotion_seq(Panel):
    bl_label = "感情マッピング Happy / Sad / Angry / Neutral"
    bl_idname = "BANIMA_PT_emotion_seq"
    bl_parent_id = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_emotion_mapping(self.layout, settings)


class BAnima_PT_advanced_seq(Panel):
    bl_label = "詳細設定"
    bl_idname = "BANIMA_PT_advanced_seq"
    bl_parent_id = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_advanced(self.layout, settings)


class BAnima_PT_bake_seq(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_bake_seq"
    bl_parent_id = "BANIMA_PT_lip_emotion_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_bake(self.layout, scene, settings)


class BAnima_PT_auto_blink_seq(Panel):
    bl_label = "Auto Blink"
    bl_idname = "BANIMA_PT_auto_blink_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="HIDE_OFF")

    def draw(self, _context):
        self.layout.label(text="自動瞬きと瞼の微細揺らぎ", icon="BLANK1")


class BAnima_PT_blink_basic_seq(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_blink_basic_seq"
    bl_parent_id = "BANIMA_PT_auto_blink_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_basic(self.layout, settings)


class BAnima_PT_blink_mapping_seq(Panel):
    bl_label = "瞬きマッピング"
    bl_idname = "BANIMA_PT_blink_mapping_seq"
    bl_parent_id = "BANIMA_PT_auto_blink_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_mapping(self.layout, settings)


class BAnima_PT_blink_advanced_seq(Panel):
    bl_label = "詳細設定"
    bl_idname = "BANIMA_PT_blink_advanced_seq"
    bl_parent_id = "BANIMA_PT_auto_blink_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_blink_advanced(self.layout, settings)


class BAnima_PT_blink_bake_seq(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_blink_bake_seq"
    bl_parent_id = "BANIMA_PT_auto_blink_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_blink_bake(self.layout, scene, settings)


class BAnima_PT_breathing_seq(Panel):
    bl_label = "Breathing & Micro Motion"
    bl_idname = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="FORCE_TURBULENCE")

    def draw(self, _context):
        self.layout.label(text="呼吸・頭部揺れ・視線サッカード・顔の微細動作", icon="BLANK1")


class BAnima_PT_breathing_basic_seq(Panel):
    bl_label = "基礎設定"
    bl_idname = "BANIMA_PT_breathing_basic_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_basic(self.layout, settings)


class BAnima_PT_breathing_mapping_seq(Panel):
    bl_label = "呼吸マッピング"
    bl_idname = "BANIMA_PT_breathing_mapping_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_mapping(self.layout, settings)


class BAnima_PT_micro_motion_mapping_seq(Panel):
    bl_label = "マイクロモーションマッピング"
    bl_idname = "BANIMA_PT_micro_motion_mapping_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_micro_motion_mapping(self.layout, settings)


class BAnima_PT_breathing_params_seq(Panel):
    bl_label = "呼吸設定"
    bl_idname = "BANIMA_PT_breathing_params_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_breathing_params(self.layout, settings)


class BAnima_PT_micro_motion_params_seq(Panel):
    bl_label = "マイクロモーション設定"
    bl_idname = "BANIMA_PT_micro_motion_params_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_micro_motion_params(self.layout, settings)


class BAnima_PT_breathing_bake_seq(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BANIMA_PT_breathing_bake_seq"
    bl_parent_id = "BANIMA_PT_breathing_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "bAnima"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_breathing_bake(self.layout, scene, settings)


classes = (
    BAnima_PT_lip_emotion,
    BAnima_PT_lip_basic,
    BAnima_PT_phoneme,
    BAnima_PT_emotion,
    BAnima_PT_advanced,
    BAnima_PT_bake,
    BAnima_PT_auto_blink,
    BAnima_PT_blink_basic,
    BAnima_PT_blink_mapping,
    BAnima_PT_blink_advanced,
    BAnima_PT_blink_bake,
    BAnima_PT_breathing,
    BAnima_PT_breathing_basic,
    BAnima_PT_breathing_mapping,
    BAnima_PT_micro_motion_mapping,
    BAnima_PT_breathing_params,
    BAnima_PT_micro_motion_params,
    BAnima_PT_breathing_bake,
    BAnima_PT_lip_emotion_seq,
    BAnima_PT_lip_basic_seq,
    BAnima_PT_phoneme_seq,
    BAnima_PT_emotion_seq,
    BAnima_PT_advanced_seq,
    BAnima_PT_bake_seq,
    BAnima_PT_auto_blink_seq,
    BAnima_PT_blink_basic_seq,
    BAnima_PT_blink_mapping_seq,
    BAnima_PT_blink_advanced_seq,
    BAnima_PT_blink_bake_seq,
    BAnima_PT_breathing_seq,
    BAnima_PT_breathing_basic_seq,
    BAnima_PT_breathing_mapping_seq,
    BAnima_PT_micro_motion_mapping_seq,
    BAnima_PT_breathing_params_seq,
    BAnima_PT_micro_motion_params_seq,
    BAnima_PT_breathing_bake_seq,
)


def _cleanup_stale_panels() -> None:
    stale = []
    for cls in Panel.__subclasses__():
        bl_idname = getattr(cls, "bl_idname", "")
        if bl_idname.startswith(_PANEL_ID_PREFIX) or getattr(cls, "bl_category", "") == "bAnima":
            stale.append(cls)
    for cls in reversed(stale):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def register():
    _cleanup_stale_panels()
    register_classes(classes)


def unregister():
    unregister_classes(classes)
    _cleanup_stale_panels()
