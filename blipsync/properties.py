"""Blender property definitions."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup

PHONEME_LABELS = ("A", "I", "U", "E", "O", "-")

EMOTION_LABELS = (
    "Happy",
    "Happy_High",
    "Sad",
    "Sad_High",
    "Angry",
    "Angry_High",
    "Neutral",
)

PROFILE_SOURCE_ITEMS = [
    ("MALE", "男性 (同梱)", "同梱の男性用 Profile JSON"),
    ("FEMALE", "女性 (同梱)", "同梱の女性用 Profile JSON"),
    ("CUSTOM", "手動 (JSON)", "Profile JSON ファイルを指定"),
]

POSE_AXIS_ITEMS = [
    ("LOC_X", "Location X", ""),
    ("LOC_Y", "Location Y", ""),
    ("LOC_Z", "Location Z", ""),
    ("ROT_X", "Rotation X", ""),
    ("ROT_Y", "Rotation Y", ""),
    ("ROT_Z", "Rotation Z", ""),
    ("SCALE_X", "Scale X", ""),
    ("SCALE_Y", "Scale Y", ""),
    ("SCALE_Z", "Scale Z", ""),
]


def _mesh_object_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


def _armature_object_poll(_self, obj):
    return obj is not None and obj.type == "ARMATURE"


def _morph_bind_target_updated(bind, _context) -> None:
    from .shape_key_utils import sync_morph_weight_ui

    sync_morph_weight_ui(bind)


def _morph_weight_ui_get(bind) -> float:
    return float(bind.weight_value)


def _morph_weight_ui_set(bind, value: float) -> None:
    from .shape_key_utils import clamp_weight_value

    bind.weight_value = clamp_weight_value(bind, float(value))


def _preview_amount_updated(_owner, context) -> None:
    from .preview import on_preview_amount_changed

    on_preview_amount_changed(context)


PREVIEW_AMOUNT_PROP = dict(
    name="プレビュー",
    description="編集時にこの項目だけを一時適用（再生中は無視）",
    min=0.0,
    max=1.0,
    default=0.0,
    subtype="FACTOR",
    precision=3,
    update=_preview_amount_updated,
)


class BLIpsyncMorphBind(PropertyGroup):
    bl_idname = "BLIpsyncMorphBind"

    mesh: PointerProperty(
        name="メッシュ",
        type=bpy.types.Object,
        poll=_mesh_object_poll,
        update=_morph_bind_target_updated,
    )
    shape_key: StringProperty(
        name="シェイプキー",
        default="",
        update=_morph_bind_target_updated,
    )
    weight_value: FloatProperty(
        name="weight_value",
        description="音素が最大のときのシェイプキー値（対象キーの slider 範囲内）",
        default=1.0,
        precision=3,
        update=_morph_bind_target_updated,
    )
    weight: FloatProperty(
        name="weight",
        description="音素が最大のときのシェイプキー値（対象キーの slider 範囲内）",
        get=_morph_weight_ui_get,
        set=_morph_weight_ui_set,
        min=0.0,
        max=1.0,
        soft_min=0.0,
        soft_max=1.0,
        precision=3,
    )


def _pose_bind_axis_updated(pose_bind, _context) -> None:
    from .pose_motion import clamp_motion_amount, default_motion_amount

    pose_bind.motion_amount = default_motion_amount(pose_bind.pose_axis)
    clamp_motion_amount(pose_bind)


def _pose_bind_motion_amount_updated(pose_bind, _context) -> None:
    from .pose_motion import clamp_motion_amount

    clamp_motion_amount(pose_bind)


class BLIpsyncPoseBind(PropertyGroup):
    bl_idname = "BLIpsyncPoseBind"

    armature: PointerProperty(name="アーマチュア", type=bpy.types.Object, poll=_armature_object_poll)
    pose_bone: StringProperty(name="ボーン", default="")
    pose_axis: EnumProperty(
        name="軸",
        items=POSE_AXIS_ITEMS,
        default="ROT_X",
        update=_pose_bind_axis_updated,
    )
    weight: FloatProperty(
        name="weight",
        description="マイクロモーション（頭部揺れ・視線）用のスケール係数（0〜1）",
        default=1.0,
        min=0.0,
        max=1.0,
        soft_min=0.0,
        soft_max=1.0,
        subtype="FACTOR",
        precision=3,
    )
    motion_amount: FloatProperty(
        name="motion_amount",
        description="呼吸・マイクロモーション用の変形量（軸種別で単位が変わる）",
        default=5.0,
        min=-180.0,
        max=180.0,
        precision=3,
        update=_pose_bind_motion_amount_updated,
    )


class BLIpsyncBindSlot(PropertyGroup):
    """Generic morph + pose bind group (breathing, micro motion, etc.)."""

    bl_idname = "BLIpsyncBindSlot"

    ui_expanded: BoolProperty(name="展開", default=False)
    preview_amount: FloatProperty(**PREVIEW_AMOUNT_PROP)
    binds: CollectionProperty(type=BLIpsyncMorphBind)
    binds_index: IntProperty(default=0)
    pose_binds: CollectionProperty(type=BLIpsyncPoseBind)
    pose_binds_index: IntProperty(default=0)


class BLIpsyncBlinkEyeSlot(PropertyGroup):
    """Left or right eye bind group (morph + pose targets)."""

    bl_idname = "BLIpsyncBlinkEyeSlot"

    ui_expanded: BoolProperty(name="展開", default=False)
    preview_amount: FloatProperty(**PREVIEW_AMOUNT_PROP)
    binds: CollectionProperty(type=BLIpsyncMorphBind)
    binds_index: IntProperty(default=0)
    pose_binds: CollectionProperty(type=BLIpsyncPoseBind)
    pose_binds_index: IntProperty(default=0)


class BLIpsyncBlinkMapping(PropertyGroup):
    bl_idname = "BLIpsyncBlinkMapping"

    name: StringProperty(name="名前", default="Blink Mapping")
    random_seed: IntProperty(
        name="ランダムシード",
        description="瞬き間隔・瞼揺らぎのランダム化用。0 = マッピング名から自動生成",
        default=0,
        min=0,
    )
    fac_jitter_amount: FloatProperty(
        name="瞼揺らぎ幅",
        description="瞬きとは別の微弱な瞼揺らぎ。Morph Target の最大ブレンド量（0〜1）",
        default=0.15,
        min=0.0,
        max=1.0,
        soft_max=0.3,
        subtype="FACTOR",
        precision=3,
    )
    left_eye: PointerProperty(type=BLIpsyncBlinkEyeSlot)
    right_eye: PointerProperty(type=BLIpsyncBlinkEyeSlot)


class BLIpsyncBlinkEye(PropertyGroup):
    """Legacy single shape-key eye slot (migrated into blink_mappings)."""

    bl_idname = "BLIpsyncBlinkEye"

    mesh: PointerProperty(
        name="メッシュ",
        type=bpy.types.Object,
        poll=_mesh_object_poll,
        update=_morph_bind_target_updated,
    )
    shape_key: StringProperty(
        name="シェイプキー",
        default="",
        update=_morph_bind_target_updated,
    )
    weight_value: FloatProperty(
        name="weight_value",
        description="瞬き最大時のシェイプキー値",
        default=1.0,
        precision=3,
        update=_morph_bind_target_updated,
    )
    weight: FloatProperty(
        name="weight",
        description="瞬き最大時のシェイプキー値",
        get=_morph_weight_ui_get,
        set=_morph_weight_ui_set,
        min=0.0,
        max=1.0,
        soft_min=0.0,
        soft_max=1.0,
        precision=3,
    )


class BLIpsyncPhonemeExpr(PropertyGroup):
    bl_idname = "BLIpsyncPhonemeExpr"

    label: StringProperty(name="音素", default="A")
    ui_expanded: BoolProperty(name="展開", default=False)
    preview_amount: FloatProperty(**PREVIEW_AMOUNT_PROP)
    binds: CollectionProperty(type=BLIpsyncMorphBind)
    binds_index: IntProperty(default=0)
    pose_binds: CollectionProperty(type=BLIpsyncPoseBind)
    pose_binds_index: IntProperty(default=0)


class BLIpsyncPhonemeMapping(PropertyGroup):
    bl_idname = "BLIpsyncPhonemeMapping"

    name: StringProperty(name="名前", default="Mapping")
    phoneme_exprs: CollectionProperty(type=BLIpsyncPhonemeExpr)


class BLIpsyncEmotionExpr(PropertyGroup):
    bl_idname = "BLIpsyncEmotionExpr"

    label: StringProperty(name="感情", default="Happy")
    ui_expanded: BoolProperty(name="展開", default=False)
    preview_amount: FloatProperty(**PREVIEW_AMOUNT_PROP)
    binds: CollectionProperty(type=BLIpsyncMorphBind)
    binds_index: IntProperty(default=0)
    pose_binds: CollectionProperty(type=BLIpsyncPoseBind)
    pose_binds_index: IntProperty(default=0)


class BLIpsyncEmotionMapping(PropertyGroup):
    bl_idname = "BLIpsyncEmotionMapping"

    name: StringProperty(name="名前", default="Emotion Mapping")
    emotion_exprs: CollectionProperty(type=BLIpsyncEmotionExpr)


MICRO_MOTION_SLOT_LABELS = (
    ("head", "頭"),
    ("left_eye", "左目"),
    ("right_eye", "右目"),
    ("eyebrows", "眉"),
    ("mouth_open", "開口"),
)

GAZE_CONTROL_ITEMS = [
    ("BONE", "ボーン", "左右目ボーンの Pose Target Binds で視線を制御"),
    ("SHAPE_KEY", "シェイプキー", "lookUp / lookDown / lookLeft / lookRight の Morph Target Binds で制御"),
]

MICRO_MOTION_GAZE_BONE_SLOTS = (
    ("left_eye", "左目"),
    ("right_eye", "右目"),
)

MICRO_MOTION_GAZE_SHAPE_SLOTS = (
    ("look_up", "lookUp"),
    ("look_down", "lookDown"),
    ("look_left", "lookLeft"),
    ("look_right", "lookRight"),
)

MICRO_MOTION_ALL_SLOT_ATTRS = (
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


class BLIpsyncBreathingMapping(PropertyGroup):
    bl_idname = "BLIpsyncBreathingMapping"

    name: StringProperty(name="名前", default="Breathing Mapping")
    random_seed: IntProperty(
        name="ランダムシード",
        description="0 = マッピング名から自動生成",
        default=0,
        min=0,
    )
    targets: PointerProperty(type=BLIpsyncBindSlot)


class BLIpsyncMicroMotionMapping(PropertyGroup):
    bl_idname = "BLIpsyncMicroMotionMapping"

    name: StringProperty(name="名前", default="Micro Motion Mapping")
    random_seed: IntProperty(
        name="ランダムシード",
        description="0 = マッピング名から自動生成",
        default=0,
        min=0,
    )
    gaze_control: EnumProperty(
        name="視線制御",
        items=GAZE_CONTROL_ITEMS,
        default="BONE",
    )
    head: PointerProperty(type=BLIpsyncBindSlot)
    left_eye: PointerProperty(type=BLIpsyncBindSlot)
    right_eye: PointerProperty(type=BLIpsyncBindSlot)
    look_up: PointerProperty(type=BLIpsyncBindSlot)
    look_down: PointerProperty(type=BLIpsyncBindSlot)
    look_left: PointerProperty(type=BLIpsyncBindSlot)
    look_right: PointerProperty(type=BLIpsyncBindSlot)
    eyebrows: PointerProperty(type=BLIpsyncBindSlot)
    mouth_open: PointerProperty(type=BLIpsyncBindSlot)


class BLIpsyncChannelTarget(PropertyGroup):
    bl_idname = "BLIpsyncChannelTarget"

    channel: IntProperty(name="チャンネル", min=1, max=128, default=1)
    label: StringProperty(name="表示名", default="", description="VSE チャンネルの説明（自動設定）")
    enabled: BoolProperty(name="使用", default=True)
    profile_source: EnumProperty(
        name="プロファイル",
        items=PROFILE_SOURCE_ITEMS,
        default="MALE",
    )
    profile_path: StringProperty(
        name="Profile JSON",
        subtype="FILE_PATH",
        default="",
        description="profile_source が手動のときに使用する JSON",
    )
    mapping_index: IntProperty(
        name="音素マッピング",
        min=0,
        default=0,
        description="phoneme_mappings 内のインデックス",
    )
    emotion_mapping_index: IntProperty(
        name="感情マッピング",
        min=0,
        default=0,
        description="emotion_mappings 内のインデックス",
    )


class BLIpsyncSceneSettings(PropertyGroup):
    bl_idname = "BLIpsyncSceneSettings"

    enabled: BoolProperty(name="Enable Lip Sync", default=True)
    emotion_enabled: BoolProperty(name="Enable Emotion Sync", default=True)
    blink_enabled: BoolProperty(name="Enable Auto Blink", default=False)

    blink_mappings: CollectionProperty(type=BLIpsyncBlinkMapping)
    blink_mappings_index: IntProperty(default=0)

    # Legacy: migrated into blink_mappings on load.
    blink_left_eye: PointerProperty(type=BLIpsyncBlinkEye)
    blink_right_eye: PointerProperty(type=BLIpsyncBlinkEye)
    blink_interval_mean: FloatProperty(
        name="平均瞬き間隔 (秒)",
        description="瞬き間隔の平均（ガウス分布の μ）。例: 3〜6 秒なら 4.5 前後",
        min=0.5,
        max=30.0,
        default=4.5,
        precision=2,
    )
    blink_jitter: FloatProperty(
        name="ゆらぎ幅",
        description="間隔ランダム性の強さ（大きいほど σ が増える）",
        min=0.0,
        max=3.0,
        default=1.0,
        precision=2,
    )
    blink_close_duration: FloatProperty(
        name="閉じる時間 (秒)",
        min=0.01,
        max=0.5,
        default=0.10,
        precision=3,
    )
    blink_open_duration: FloatProperty(
        name="開く時間 (秒)",
        min=0.01,
        max=0.5,
        default=0.15,
        precision=3,
    )
    blink_eyelid_jitter_speed: FloatProperty(
        name="瞼揺らぎ速度",
        description="瞬きとは別の微弱な瞼揺らぎの変化速度（大きいほど速く揺れる）",
        min=0.0,
        max=10.0,
        default=1.0,
        precision=2,
    )
    blink_bake_use_range: BoolProperty(
        name="範囲を指定",
        default=False,
        description="オフ: シーンのフレーム範囲。オン: 下の開始/終了フレーム",
    )
    blink_bake_frame_start: IntProperty(name="開始フレーム", default=1)
    blink_bake_frame_end: IntProperty(name="終了フレーム", default=250)
    blink_bake_step: IntProperty(
        name="ステップ",
        min=1,
        default=1,
        description="何フレームおきにサンプルしてキーフレームを打つか（1 = 毎フレーム）",
    )

    breathing_enabled: BoolProperty(name="Enable Breathing", default=False)
    micro_motion_enabled: BoolProperty(name="Enable Micro Motion", default=False)

    breathing_mappings: CollectionProperty(type=BLIpsyncBreathingMapping)
    breathing_mappings_index: IntProperty(default=0)
    breathing_bpm: FloatProperty(
        name="呼吸数 (BPM)",
        description="安静時 12〜18 回/分を基準",
        min=12.0,
        max=18.0,
        default=15.0,
        precision=1,
    )
    breathing_exhale_ratio: FloatProperty(
        name="吸気:呼気 比率 (1:N)",
        description="呼気側の長さ倍率。生体的には 1.5〜2 程度が自然",
        min=1.5,
        max=2.0,
        default=1.75,
        precision=2,
    )
    micro_motion_mappings: CollectionProperty(type=BLIpsyncMicroMotionMapping)
    micro_motion_mappings_index: IntProperty(default=0)
    micro_head_sway_amplitude: FloatProperty(
        name="頭部揺れ 強度 (±度)",
        description="各ポーズバインドの移動量上限（±度）。バインドの weight でさらにスケール",
        min=0.0,
        max=30.0,
        default=1.5,
        precision=2,
    )
    micro_head_sway_interval_min: FloatProperty(
        name="揺れ間隔 最小 (秒)",
        min=0.1,
        max=60.0,
        default=0.5,
        precision=2,
    )
    micro_head_sway_interval_max: FloatProperty(
        name="揺れ間隔 最大 (秒)",
        min=0.1,
        max=60.0,
        default=4.0,
        precision=2,
    )
    micro_head_sway_motion_time_min: FloatProperty(
        name="行き・戻り時間 最小 (秒)",
        description="行き・戻りそれぞれの移動時間の下限",
        min=0.05,
        max=10.0,
        default=0.3,
        precision=2,
    )
    micro_head_sway_motion_time_max: FloatProperty(
        name="行き・戻り時間 最大 (秒)",
        description="行き・戻りそれぞれの移動時間の上限",
        min=0.05,
        max=10.0,
        default=0.8,
        precision=2,
    )
    micro_saccade_enabled: BoolProperty(name="視線サッカード", default=True)
    micro_saccade_interval_min: FloatProperty(
        name="サッカード間隔 最小 (秒)",
        min=0.5,
        max=3.0,
        default=0.5,
        precision=2,
    )
    micro_saccade_interval_max: FloatProperty(
        name="サッカード間隔 最大 (秒)",
        min=0.5,
        max=3.0,
        default=3.0,
        precision=2,
    )
    micro_saccade_travel_time: FloatProperty(
        name="行き時間 (秒)",
        description="新しい視線位置へ移動する時間",
        min=0.01,
        max=1.0,
        default=0.1,
        precision=3,
    )
    micro_saccade_return_time: FloatProperty(
        name="戻り時間 (秒)",
        description="視線を中立位置へ戻す時間",
        min=0.01,
        max=1.0,
        default=0.5,
        precision=3,
    )
    micro_saccade_amplitude_deg: FloatProperty(
        name="サッカード強度 (±度)",
        description="ボーン制御時の視線移動量（左右目共通）",
        min=0.0,
        max=15.0,
        default=1.0,
        precision=2,
    )
    micro_saccade_intensity: FloatProperty(
        name="サッカード強度（シェイプキー）",
        description="シェイプキー制御時の look 方向ブレンド量",
        min=0.0,
        max=1.0,
        default=0.15,
        subtype="FACTOR",
        precision=3,
    )
    micro_facial_noise_intensity: FloatProperty(
        name="眉・開口 ノイズ強度",
        description="眉・開口シェイプキーへの微細ノイズ",
        min=0.0,
        max=0.5,
        default=0.05,
        subtype="FACTOR",
        precision=3,
    )
    motion_bake_use_range: BoolProperty(
        name="範囲を指定",
        default=False,
        description="オフ: シーンのフレーム範囲全体をベイク。オン: 下の開始/終了フレームでベイク",
    )
    motion_bake_frame_start: IntProperty(name="開始フレーム", default=1)
    motion_bake_frame_end: IntProperty(name="終了フレーム", default=250)
    motion_bake_step: IntProperty(
        name="ステップ",
        min=1,
        default=1,
        description="何フレームおきにサンプルしてキーフレームを打つか（1 = 毎フレーム）",
    )

    channel_targets: CollectionProperty(type=BLIpsyncChannelTarget)
    channel_targets_index: IntProperty(default=0)

    phoneme_mappings: CollectionProperty(type=BLIpsyncPhonemeMapping)
    phoneme_mappings_index: IntProperty(default=0)

    emotion_mappings: CollectionProperty(type=BLIpsyncEmotionMapping)
    emotion_mappings_index: IntProperty(default=0)

    # Legacy: migrated into phoneme_mappings on load.
    phoneme_exprs: CollectionProperty(type=BLIpsyncPhonemeExpr)
    phoneme_exprs_index: IntProperty(default=0)
    profile_path: StringProperty(name="Profile JSON (legacy)", default="")

    bake_use_range: BoolProperty(
        name="範囲を指定",
        default=False,
        description="オフ: シーンのフレーム範囲全体をベイク。オン: 下の開始/終了フレームでベイク",
    )
    bake_frame_start: IntProperty(name="開始フレーム", default=1)
    bake_frame_end: IntProperty(name="終了フレーム", default=250)
    bake_step: IntProperty(
        name="ステップ",
        min=1,
        default=1,
        description="何フレームおきにサンプルしてキーフレームを打つか（1 = 毎フレーム）",
    )

    use_phoneme_blend: BoolProperty(name="Phoneme Blend", default=True)
    smoothness: FloatProperty(name="Smoothness", min=0.001, max=0.3, default=0.05)
    min_volume: FloatProperty(name="Min Volume (log10)", default=-2.5)
    max_volume: FloatProperty(name="Max Volume (log10)", default=-1.5)
    max_blend_value: FloatProperty(name="Max Blend Value", min=0.0, max=100.0, default=1.0)

    emotion_high_threshold_happy: FloatProperty(
        name="Happy 通常/High 境目",
        description="0〜この値で Happy、それ以上で Happy_High へ徐々に移行",
        min=0.01,
        max=0.99,
        default=0.5,
        subtype="FACTOR",
    )
    emotion_high_threshold_sad: FloatProperty(
        name="Sad 通常/High 境目",
        min=0.01,
        max=0.99,
        default=0.5,
        subtype="FACTOR",
    )
    emotion_high_threshold_angry: FloatProperty(
        name="Angry 通常/High 境目",
        min=0.01,
        max=0.99,
        default=0.5,
        subtype="FACTOR",
    )
    emotion_smoothness: FloatProperty(
        name="Emotion Smoothness",
        description="感情変化のローパス（大きいほど緩やか）",
        min=0.001,
        max=0.5,
        default=0.08,
    )
    emotion_threshold: FloatProperty(
        name="Emotion Threshold",
        description="スロット重みのデッドゾーン（この値未満の感情変化は無視）",
        min=0.0,
        max=0.5,
        default=0.05,
        subtype="FACTOR",
    )
    emotion_valence_pivot: FloatProperty(
        name="Valence 偏り",
        description=(
            "感情モデルの Valence 出力を再マッピングする基準点。"
            "[0〜n] を [0〜0.5]、[n〜1] を [0.5〜1] に写像してから 4 感情へ分配。"
            "0.5 = 無変換"
        ),
        min=0.01,
        max=0.99,
        default=0.5,
        subtype="FACTOR",
    )
    emotion_arousal_pivot: FloatProperty(
        name="Arousal 偏り",
        description=(
            "感情モデルの Arousal 出力を再マッピングする基準点。"
            "[0〜n] を [0〜0.5]、[n〜1] を [0.5〜1] に写像してから 4 感情へ分配。"
            "0.5 = 無変換"
        ),
        min=0.01,
        max=0.99,
        default=0.5,
        subtype="FACTOR",
    )
    emotion_vad_neutral_radius: FloatProperty(
        name="VAD Neutral Radius",
        description="（未使用・旧マッピング用）今後削除予定",
        min=0.0,
        max=0.5,
        default=0.12,
        subtype="FACTOR",
    )

    debug_channel: IntProperty(name="表示チャンネル", default=0)
    debug_phoneme: StringProperty(name="検出音素", default="-")
    debug_raw_phoneme: StringProperty(name="解析音素", default="-")
    debug_volume: FloatProperty(name="音量", default=0.0, precision=3)
    debug_emotion: StringProperty(name="検出感情", default="neutral")
    debug_emotion_happy: FloatProperty(name="Happy", default=0.0, precision=3)
    debug_emotion_sad: FloatProperty(name="Sad", default=0.0, precision=3)
    debug_emotion_angry: FloatProperty(name="Angry", default=0.0, precision=3)
    debug_emotion_neutral: FloatProperty(name="Neutral", default=0.0, precision=3)

    realtime_during_render: BoolProperty(
        name="レンダー時もリアルタイム適用",
        description=(
            "オン（既定）: レンダー中もビューポートと同様に適用（フレーム評価後・撮影直前に反映）。"
            "ベイク後に各モジュールを OFF にすればキーフレームのみで高速レンダー。"
            "オフ: レンダー中はリアルタイム適用をスキップ（ベイク済みキーフレームのみ）"
        ),
        default=True,
    )
    render_apply_mode: EnumProperty(
        name="レンダー適用方式",
        description=(
            "オーバーレイ: レンダー中はUIロック＋RNA適用（notifier回避・EEVEE反映）。"
            "RNA直接: 旧方式（クラッシュする場合のみ切り替え）"
        ),
        items=(
            (
                "OVERLAY",
                "オーバーレイ（推奨）",
                "レンダー中UIロック＋RNA適用",
            ),
            (
                "RNA",
                "RNA直接（旧方式）",
                "レンダー中も kb.value を直接更新（ロックなし）",
            ),
        ),
        default="OVERLAY",
    )
    debug_profile_ticks: BoolProperty(
        name="ティック処理時間をコンソールへ出力",
        description="再生・スクラブ時の blipsync 処理時間を System Console に出力",
        default=False,
    )
    debug_profile_render: BoolProperty(
        name="レンダー時プロファイルをファイル保存",
        description=(
            "「レンダー時もリアルタイム適用」がオンのとき、"
            "各フレームの処理時間を .blend と同じフォルダへ保存"
        ),
        default=False,
    )
    render_rt_fixup_v1: BoolProperty(
        name="Render RT Fixup",
        default=False,
        options={"HIDDEN"},
    )


_LEGACY_CLASSES = (
    "BLIpsyncChannelItem",
    "BLIpsyncChannelEntry",
    "BLIpsyncSoundTarget",
    "BLIpsyncSettings",
    "BLIpsyncMapping",
    "BLIpsyncPhonemeSlot",
    "BLIpsyncUISection",
    "BLIPSYNC_UL_ui_sections",
    "BLIPSYNC_PT_panel_v6",
    "BLIPSYNC_PT_panel_v7",
    "BLIPSYNC_PT_panel_seq_v6",
    "BLIPSYNC_PT_panel_seq_v7",
    "BLIPSYNC_PT_root",
    "BLIPSYNC_PT_root_seq",
    "BLIPSYNC_PT_basic",
    "BLIPSYNC_PT_basic_seq",
    "BLIPSYNC_PT_phoneme",
    "BLIPSYNC_PT_phoneme_seq",
    "BLIPSYNC_PT_bake",
    "BLIPSYNC_PT_bake_seq",
    "BLIPSYNC_PT_advanced",
    "BLIPSYNC_PT_advanced_seq",
)

classes = (
    BLIpsyncMorphBind,
    BLIpsyncPoseBind,
    BLIpsyncBindSlot,
    BLIpsyncBlinkEyeSlot,
    BLIpsyncBlinkMapping,
    BLIpsyncBlinkEye,
    BLIpsyncPhonemeExpr,
    BLIpsyncPhonemeMapping,
    BLIpsyncEmotionExpr,
    BLIpsyncEmotionMapping,
    BLIpsyncBreathingMapping,
    BLIpsyncMicroMotionMapping,
    BLIpsyncChannelTarget,
    BLIpsyncSceneSettings,
)


def _unregister_legacy():
    import bpy.types as bt

    for name in _LEGACY_CLASSES:
        cls = getattr(bt, name, None)
        if cls is None:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def register():
    from .registration import add_scene_pointer_deferred, ensure_scene_pointer, register_classes

    _unregister_legacy()
    register_classes(classes)
    if not ensure_scene_pointer("blipsync", BLIpsyncSceneSettings):
        add_scene_pointer_deferred("blipsync", BLIpsyncSceneSettings)


def unregister():
    from .registration import (
        cancel_scene_pointer_timers,
        remove_scene_pointer,
        unregister_classes,
    )

    cancel_scene_pointer_timers()
    remove_scene_pointer("blipsync")
    unregister_classes(classes)
    _unregister_legacy()
