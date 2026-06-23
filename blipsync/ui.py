"""Blender UI panels."""

from __future__ import annotations

import bpy
from bpy.types import Object, Panel

from .defaults import check_emotion_configured, check_scene_configured, peek_channel_emotion_mapping, peek_channel_mapping
from .deps_installer import (
    get_import_error,
    get_install_error,
    get_install_log_path,
    get_install_progress,
    get_install_status,
    is_installing,
    onnxruntime_importable,
)
from .emotion_engine import (
    emotion_deps_install_hint,
    get_classifier_error,
    get_emotion_backend,
    is_classifier_available,
)
from .properties import (
    EMOTION_LABELS,
    MICRO_MOTION_GAZE_BONE_SLOTS,
    MICRO_MOTION_GAZE_SHAPE_SLOTS,
    PHONEME_LABELS,
    PROFILE_SOURCE_ITEMS,
)
from .sequencer import channel_label, collect_channels_with_sound
from .shape_key_utils import WEIGHT_UI_KEY, schedule_morph_weight_sync

_PANEL_ID_PREFIX = "BLIPSYNC_PT_"
_POINTER_RETRY_SCHEDULED = False


def _settings_ready(scene) -> bool:
    if not hasattr(scene, "blipsync"):
        return False
    settings = scene.blipsync
    return settings.__class__.__name__ != "_PropertyDeferred"


def _schedule_pointer_retry() -> None:
    global _POINTER_RETRY_SCHEDULED
    if _POINTER_RETRY_SCHEDULED:
        return
    _POINTER_RETRY_SCHEDULED = True
    from .properties import BLIpsyncSceneSettings
    from .registration import add_scene_pointer_deferred

    add_scene_pointer_deferred("blipsync", BLIpsyncSceneSettings)


def _panel_poll(_context) -> bool:
    return True


def _settings_or_init(layout, scene):
    if scene is None:
        layout.label(text="シーンがありません", icon="ERROR")
        return None
    if not _settings_ready(scene):
        _schedule_pointer_retry()
        layout.label(text="初期化中...", icon="INFO")
        return None
    return scene.blipsync


def _channel_display(scene, item) -> str:
    if item.label:
        return item.label
    channel_map = collect_channels_with_sound(scene)
    return channel_label(item.channel, channel_map.get(item.channel))


def _morph_bind_label(bind) -> str:
    mesh_name = bind.mesh.name if bind.mesh else "未設定"
    shape_key = bind.shape_key or "未設定"
    return f"{mesh_name} / {shape_key}"


def _pose_bind_label(pose_bind) -> str:
    arm_name = pose_bind.armature.name if pose_bind.armature else "未設定"
    bone_name = pose_bind.pose_bone or "未設定"
    return f"{arm_name} / {bone_name}"


def _draw_collapsible_section(
    layout,
    owner,
    title: str,
    icon: str,
    draw_content,
    *,
    preview: bool = False,
) -> None:
    box = layout.box()
    row = box.row(align=True)
    expanded = bool(getattr(owner, "ui_expanded", False))
    row.prop(
        owner,
        "ui_expanded",
        text="",
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    row.label(text=title, icon=icon)
    if expanded:
        if preview and hasattr(owner, "preview_amount"):
            box.prop(owner, "preview_amount", text="プレビュー", slider=True)
        draw_content(box)


def _draw_morph_bind_details(layout, bind):
    layout.prop(bind, "mesh", text="メッシュ")
    obj = bind.mesh
    if isinstance(obj, Object) and obj.type == "MESH" and obj.data and obj.data.shape_keys:
        layout.prop_search(bind, "shape_key", obj.data.shape_keys, "key_blocks", text="Shape key")
    else:
        layout.prop(bind, "shape_key", text="Shape key")

    if WEIGHT_UI_KEY in bind:
        ui_value = float(bind[WEIGHT_UI_KEY])
        if abs(ui_value - float(bind.weight_value)) > 1e-9:
            schedule_morph_weight_sync(bind, ui_value)
        layout.prop(bind, f'["{WEIGHT_UI_KEY}"]', text="weight", slider=True)
    else:
        layout.prop(bind, "weight", text="weight", slider=True)


def _draw_pose_bind_details(layout, pose_bind):
    layout.prop(pose_bind, "armature", text="アーマチュア")
    arm = pose_bind.armature
    if isinstance(arm, Object) and arm.type == "ARMATURE":
        layout.prop_search(pose_bind, "pose_bone", arm.pose, "bones", text="ボーン")
    else:
        layout.prop(pose_bind, "pose_bone", text="ボーン")
    layout.prop(pose_bind, "pose_axis", text="軸")
    layout.prop(pose_bind, "weight", text="weight", slider=True)
    if pose_bind.pose_axis.startswith("ROT"):
        hint = layout.column(align=True)
        hint.scale_y = 0.85
        hint.label(text="回転ボーンは適用時に XYZ オイラーへ切替", icon="INFO")


def _draw_motion_pose_bind_details(layout, pose_bind):
    layout.prop(pose_bind, "armature", text="アーマチュア")
    arm = pose_bind.armature
    if isinstance(arm, Object) and arm.type == "ARMATURE":
        layout.prop_search(pose_bind, "pose_bone", arm.pose, "bones", text="ボーン")
    else:
        layout.prop(pose_bind, "pose_bone", text="ボーン")
    layout.prop(pose_bind, "pose_axis", text="軸")
    axis = pose_bind.pose_axis
    if axis.startswith("SCALE"):
        layout.prop(pose_bind, "motion_amount", text="倍率")
        hint = layout.column(align=True)
        hint.scale_y = 0.85
        hint.label(text="0.5〜2.0（1.0 = 変化なし）", icon="BLANK1")
    elif axis.startswith("ROT"):
        layout.prop(pose_bind, "motion_amount", text="角度 (±度)")
        hint = layout.column(align=True)
        hint.scale_y = 0.85
        hint.label(text="最大 ±180°", icon="BLANK1")
        hint.label(text="回転ボーンは適用時に XYZ オイラーへ切替", icon="INFO")
    elif axis.startswith("LOC"):
        layout.prop(pose_bind, "motion_amount", text="距離 (±m)")
        hint = layout.column(align=True)
        hint.scale_y = 0.85
        hint.label(text="最大 ±1.0 m", icon="BLANK1")
    else:
        layout.prop(pose_bind, "motion_amount")


def _profile_source_label(source: str) -> str:
    for key, label, _desc in PROFILE_SOURCE_ITEMS:
        if key == source:
            return label
    return source


def _draw_bind_list(
    layout,
    expr,
    expr_index: int,
    mapping_index: int,
    *,
    list_id: str,
    collection: str,
    index_prop: str,
    add_op: str,
    remove_op: str,
    header: str,
    header_icon: str,
    draw_details,
    expr_index_prop: str = "phoneme_index",
    slot_index_prop: str = "",
    slot_attr: str = "",
):
    row = layout.row()
    row.label(text=header, icon=header_icon)

    items = getattr(expr, collection)
    index = getattr(expr, index_prop)

    row = layout.row()
    row.template_list(
        list_id, "",
        expr, collection,
        expr, index_prop,
        rows=max(2, len(items)),
    )
    col = row.column(align=True)
    op = col.operator(add_op, icon="ADD", text="")
    op.mapping_index = mapping_index
    if slot_attr:
        op.slot_attr = slot_attr
    elif slot_index_prop:
        setattr(op, slot_index_prop, expr_index)
    elif expr_index_prop:
        setattr(op, expr_index_prop, expr_index)
    op = col.operator(remove_op, icon="REMOVE", text="")
    op.mapping_index = mapping_index
    if slot_attr:
        op.slot_attr = slot_attr
    elif slot_index_prop:
        setattr(op, slot_index_prop, expr_index)
    elif expr_index_prop:
        setattr(op, expr_index_prop, expr_index)

    if items and 0 <= index < len(items):
        draw_details(layout, items[index])


def _draw_bind_slot_content(
    layout,
    slot,
    slot_index: int,
    mapping_index: int,
    *,
    morph_add_op: str,
    morph_remove_op: str,
    pose_add_op: str,
    pose_remove_op: str,
    expr_index_prop: str = "phoneme_index",
    slot_index_prop: str = "",
    slot_attr: str = "",
    pose_first: bool = False,
    morph_only: bool = False,
    pose_only: bool = False,
    motion_pose_binds: bool = False,
) -> None:
    pose_details = _draw_motion_pose_bind_details if motion_pose_binds else _draw_pose_bind_details
    morph_kwargs = dict(
        list_id="BLIPSYNC_UL_morph_binds",
        collection="binds",
        index_prop="binds_index",
        add_op=morph_add_op,
        remove_op=morph_remove_op,
        header="Morph Target Binds",
        header_icon="MESH_DATA",
        draw_details=_draw_morph_bind_details,
        expr_index_prop=expr_index_prop,
        slot_index_prop=slot_index_prop,
        slot_attr=slot_attr,
    )
    pose_kwargs = dict(
        list_id="BLIPSYNC_UL_pose_binds",
        collection="pose_binds",
        index_prop="pose_binds_index",
        add_op=pose_add_op,
        remove_op=pose_remove_op,
        header="Pose Target Binds",
        header_icon="BONE_DATA",
        draw_details=pose_details,
        expr_index_prop=expr_index_prop,
        slot_index_prop=slot_index_prop,
        slot_attr=slot_attr,
    )

    if morph_only:
        _draw_bind_list(layout, slot, slot_index, mapping_index, **morph_kwargs)
        return
    if pose_only:
        _draw_bind_list(layout, slot, slot_index, mapping_index, **pose_kwargs)
        return
    if pose_first:
        _draw_bind_list(layout, slot, slot_index, mapping_index, **pose_kwargs)
        layout.separator()
        _draw_bind_list(layout, slot, slot_index, mapping_index, **morph_kwargs)
    else:
        _draw_bind_list(layout, slot, slot_index, mapping_index, **morph_kwargs)
        layout.separator()
        _draw_bind_list(layout, slot, slot_index, mapping_index, **pose_kwargs)


def _draw_phoneme_expr(layout, expr, expr_index: int, mapping_index: int):
    _draw_bind_slot_content(
        layout, expr, expr_index, mapping_index,
        morph_add_op="blipsync.add_morph_bind",
        morph_remove_op="blipsync.remove_morph_bind",
        pose_add_op="blipsync.add_pose_bind",
        pose_remove_op="blipsync.remove_pose_bind",
        motion_pose_binds=True,
    )
    layout.separator()


def _draw_emotion_expr(layout, expr, expr_index: int, mapping_index: int):
    _draw_bind_slot_content(
        layout, expr, expr_index, mapping_index,
        morph_add_op="blipsync.add_emotion_morph_bind",
        morph_remove_op="blipsync.remove_emotion_morph_bind",
        pose_add_op="blipsync.add_emotion_pose_bind",
        pose_remove_op="blipsync.remove_emotion_pose_bind",
        expr_index_prop="emotion_index",
        motion_pose_binds=True,
    )
    layout.separator()


def _draw_basic(layout, scene, settings):
    layout.prop(settings, "enabled")
    layout.prop(settings, "emotion_enabled")

    ok, msg = check_scene_configured(scene)
    if settings.enabled and not ok:
        layout.box().label(text=msg, icon="ERROR")

    emotion_ok, emotion_msg = check_emotion_configured(scene)
    if settings.emotion_enabled and not emotion_ok:
        layout.box().label(text=emotion_msg, icon="ERROR")

    if settings.emotion_enabled and not is_classifier_available():
        status = get_install_status()
        box = layout.box()
        if status == "installing" or is_installing():
            progress = get_install_progress()
            box.label(text="onnxruntime をインストール中...", icon="IMPORT")
            if progress:
                box.label(text=progress, icon="TIME")
            box.label(text=f"Log: {get_install_log_path()}", icon="TEXT")
        elif status == "failed":
            box.label(text="ライブラリのインストールに失敗", icon="ERROR")
            err = get_install_error() or get_classifier_error()
            if err:
                box.label(text=err, icon="NONE")
            box.operator("blipsync.install_emotion_deps", text="再試行", icon="FILE_REFRESH")
        elif status == "ok" and not onnxruntime_importable():
            box.label(text="インストール完了 — ライブラリを検出中", icon="INFO")
            err = get_import_error() or get_install_error()
            if err:
                for line in err.splitlines()[:4]:
                    box.label(text=line, icon="NONE")
            else:
                box.label(text=emotion_deps_install_hint(), icon="NONE")
            box.operator("blipsync.refresh_emotion_deps", text="再検出", icon="FILE_REFRESH")
        elif not onnxruntime_importable():
            box.label(text="感情認識ライブラリ（onnxruntime）が未インストール", icon="INFO")
            box.label(text=emotion_deps_install_hint(), icon="NONE")
            box.operator("blipsync.install_emotion_deps", text="今すぐインストール", icon="IMPORT")
        else:
            box.label(text="感情モデルの読み込みに失敗", icon="ERROR")
            err = get_classifier_error()
            if err and "speechbrain" in err.lower():
                box.label(
                    text="古い SpeechBrain 版 blipsync が読み込まれています。",
                    icon="ERROR",
                )
                box.label(
                    text="bAnima 0.2.9+ を再インストールし、旧 blipsync アドオンを無効化してください。",
                    icon="NONE",
                )
            elif err:
                box.label(text=err, icon="NONE")
            box.operator("blipsync.install_emotion_deps", text="依存関係を再インストール", icon="FILE_REFRESH")

    row = layout.row(align=True)
    if settings.debug_channel > 0:
        row.label(text=f"Ch{settings.debug_channel}: {settings.debug_phoneme}")
    else:
        row.label(text=f"検出: {settings.debug_phoneme}")
    row.label(text=f"Vol: {settings.debug_volume:.3f}")

    if settings.emotion_enabled:
        layout.label(text=f"感情エンジン: {get_emotion_backend()}")
        row = layout.row(align=True)
        row.label(text=f"感情: {settings.debug_emotion}")
        row.label(
            text=(
                f"H:{settings.debug_emotion_happy:.2f} "
                f"S:{settings.debug_emotion_sad:.2f} "
                f"A:{settings.debug_emotion_angry:.2f} "
                f"N:{settings.debug_emotion_neutral:.2f}"
            ),
        )

    layout.separator()
    layout.label(text="シーケンサー チャンネル", icon="SOUND")
    layout.label(text="チャンネルごとにプロファイルと音素マッピングを指定")
    layout.operator("blipsync.sync_channels", text="SOUND があるチャンネルを検出", icon="FILE_REFRESH")

    if not collect_channels_with_sound(scene):
        layout.label(text="SOUND ストリップがありません", icon="INFO")

    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_channel_targets", "",
        settings, "channel_targets",
        settings, "channel_targets_index",
        rows=4,
    )
    col = row.column(align=True)
    col.operator("blipsync.remove_channel", icon="REMOVE", text="")

    if settings.channel_targets:
        item = settings.channel_targets[settings.channel_targets_index]
        box = layout.box()
        box.label(text="選択中チャンネルの設定", icon="SETTINGS")
        box.prop(item, "profile_source", text="プロファイル")
        if item.profile_source == "CUSTOM":
            box.prop(item, "profile_path", text="JSON")
        if settings.phoneme_mappings:
            mapping = peek_channel_mapping(settings, item)
            mapping_label = mapping.name if mapping else "未設定"
            row = box.row(align=True)
            row.label(text="音素マッピング")
            row.menu("BLIPSYNC_MT_channel_mapping", text=mapping_label)
        else:
            box.label(text="音素マッピングを作成してください", icon="INFO")
        if settings.emotion_mappings:
            emotion_mapping = peek_channel_emotion_mapping(settings, item)
            emotion_label = emotion_mapping.name if emotion_mapping else "未設定"
            row = box.row(align=True)
            row.label(text="感情マッピング")
            row.menu("BLIPSYNC_MT_channel_emotion_mapping", text=emotion_label)
        else:
            box.label(text="感情マッピングを作成してください", icon="INFO")


def _draw_phoneme_mapping(layout, settings):
    if not settings.phoneme_mappings:
        layout.operator("blipsync.init_scene", text="音素マッピングを初期化", icon="FILE_REFRESH")
        return

    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_phoneme_mappings", "",
        settings, "phoneme_mappings",
        settings, "phoneme_mappings_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blipsync.add_phoneme_mapping", icon="ADD", text="")
    col.operator("blipsync.remove_phoneme_mapping", icon="REMOVE", text="")

    mapping = settings.phoneme_mappings[settings.phoneme_mappings_index]
    layout.prop(mapping, "name", text="名前")

    if len(mapping.phoneme_exprs) < len(PHONEME_LABELS):
        layout.operator("blipsync.init_scene", text="音素スロットを再初期化", icon="FILE_REFRESH")

    mapping_index = settings.phoneme_mappings_index
    for i, expr in enumerate(mapping.phoneme_exprs):
        _draw_collapsible_section(
            layout,
            expr,
            f"音素: {expr.label}",
            "SHAPEKEY_DATA",
            lambda body, e=expr, idx=i, mi=mapping_index: _draw_phoneme_expr(body, e, idx, mi),
            preview=True,
        )


def _draw_emotion_mapping(layout, settings):
    if not settings.emotion_mappings:
        layout.operator("blipsync.init_scene", text="感情マッピングを初期化", icon="FILE_REFRESH")
        return

    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_emotion_mappings", "",
        settings, "emotion_mappings",
        settings, "emotion_mappings_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blipsync.add_emotion_mapping", icon="ADD", text="")
    col.operator("blipsync.remove_emotion_mapping", icon="REMOVE", text="")

    mapping = settings.emotion_mappings[settings.emotion_mappings_index]
    layout.prop(mapping, "name", text="名前")

    if len(mapping.emotion_exprs) < len(EMOTION_LABELS):
        layout.operator("blipsync.init_scene", text="感情スロットを再初期化", icon="FILE_REFRESH")

    mapping_index = settings.emotion_mappings_index
    for i, expr in enumerate(mapping.emotion_exprs):
        _draw_collapsible_section(
            layout,
            expr,
            f"感情: {expr.label}",
            "SHAPEKEY_DATA",
            lambda body, e=expr, idx=i, mi=mapping_index: _draw_emotion_expr(body, e, idx, mi),
            preview=True,
        )


def _draw_bake(layout, scene, settings):
    layout.prop(settings, "bake_use_range", text="範囲を指定")
    if settings.bake_use_range:
        layout.prop(settings, "bake_frame_start")
        layout.prop(settings, "bake_frame_end")
    else:
        layout.label(text=f"範囲: {scene.frame_start} – {scene.frame_end}（シーン設定）", icon="TIME")
    layout.prop(settings, "bake_step")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="1 = 毎フレーム、2 = 1フレームおき…", icon="BLANK1")
    layout.separator()
    col = layout.column(align=True)
    op = col.operator("blipsync.bake", text="リップのみベイク", icon="SPEAKER")
    op.bake_lip = True
    op.bake_emotion = False
    op = col.operator("blipsync.bake", text="感情のみベイク", icon="HEART")
    op.bake_lip = False
    op.bake_emotion = True
    op = col.operator("blipsync.bake", text="リップ + 感情をベイク", icon="ANIM")
    op.bake_lip = True
    op.bake_emotion = True


def _draw_blink_eye_slot(layout, eye_slot, label: str, mapping_index: int, eye_index: int) -> None:
    _draw_collapsible_section(
        layout,
        eye_slot,
        label,
        "HIDE_OFF",
        lambda body, slot=eye_slot, mi=mapping_index, ei=eye_index: _draw_bind_slot_content(
            body, slot, ei, mi,
            morph_add_op="blipsync.add_blink_morph_bind",
            morph_remove_op="blipsync.remove_blink_morph_bind",
            pose_add_op="blipsync.add_blink_pose_bind",
            pose_remove_op="blipsync.remove_blink_pose_bind",
            expr_index_prop="eye_index",
            motion_pose_binds=True,
        ),
        preview=True,
    )


def _draw_blink_mapping(layout, settings) -> None:
    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_blink_mappings", "",
        settings, "blink_mappings",
        settings, "blink_mappings_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blipsync.add_blink_mapping", icon="ADD", text="")
    col.operator("blipsync.remove_blink_mapping", icon="REMOVE", text="")

    if not settings.blink_mappings:
        return

    mapping = settings.blink_mappings[settings.blink_mappings_index]
    layout.prop(mapping, "name", text="名前")
    layout.prop(mapping, "random_seed", text="ランダムシード")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="0 = マッピング名から自動生成", icon="BLANK1")
    layout.prop(mapping, "fac_jitter_amount", text="瞼揺らぎ幅")

    mapping_index = settings.blink_mappings_index
    _draw_blink_eye_slot(layout, mapping.left_eye, "左目", mapping_index, 0)
    _draw_blink_eye_slot(layout, mapping.right_eye, "右目", mapping_index, 1)


def _draw_blink_basic(layout, settings) -> None:
    from .defaults import blink_is_configured

    layout.prop(settings, "blink_enabled")
    if not settings.blink_enabled:
        return
    if not blink_is_configured(settings):
        layout.box().label(text="瞬きマッピングにターゲットを設定してください", icon="ERROR")


def _draw_blink_advanced(layout, settings) -> None:
    if not settings.blink_enabled:
        return

    layout.label(text="タイミング（全マッピング共通）", icon="TIME")
    layout.prop(settings, "blink_interval_mean")
    layout.prop(settings, "blink_jitter")
    col = layout.column(align=True)
    col.scale_y = 0.85
    col.label(text="ガウス分布で間隔をランダム化（生体らしいばらつき）", icon="BLANK1")

    layout.separator()
    layout.label(text="瞬き速度", icon="MOD_TIME")
    layout.prop(settings, "blink_close_duration")
    layout.prop(settings, "blink_open_duration")

    layout.separator()
    layout.label(text="瞼揺らぎ（全マッピング共通速度）", icon="FORCE_TURBULENCE")
    layout.prop(settings, "blink_eyelid_jitter_speed", text="揺らぎ速度")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="揺らぎ幅は各マッピングの「瞼揺らぎ幅」で設定", icon="BLANK1")


def _draw_blink_bake(layout, scene, settings) -> None:
    if not settings.blink_enabled:
        return

    layout.prop(settings, "blink_bake_use_range", text="範囲を指定")
    if settings.blink_bake_use_range:
        layout.prop(settings, "blink_bake_frame_start")
        layout.prop(settings, "blink_bake_frame_end")
    else:
        layout.label(text=f"範囲: {scene.frame_start} – {scene.frame_end}（シーン設定）", icon="TIME")
    layout.prop(settings, "blink_bake_step")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="1 = 毎フレーム、2 = 1フレームおき…", icon="BLANK1")
    layout.operator("blipsync.bake_blink", text="瞬きをベイク", icon="REC")


def _draw_blink_settings(layout, scene, settings) -> None:
    _draw_blink_basic(layout, settings)
    if not settings.blink_enabled:
        return
    layout.separator()
    layout.label(text="瞬きマッピング", icon="RNA")
    _draw_blink_mapping(layout, settings)
    layout.separator()
    _draw_blink_advanced(layout, settings)
    layout.separator()
    layout.label(text="ベイク", icon="RENDER_ANIMATION")
    _draw_blink_bake(layout, scene, settings)


def _draw_breathing_basic(layout, settings) -> None:
    from .defaults import breathing_is_configured

    layout.prop(settings, "breathing_enabled")
    layout.prop(settings, "micro_motion_enabled")
    if settings.breathing_enabled and not breathing_is_configured(settings):
        layout.box().label(text="呼吸マッピングにターゲットを設定してください", icon="ERROR")
    if settings.micro_motion_enabled:
        from .defaults import micro_motion_is_configured
        if not micro_motion_is_configured(settings):
            layout.box().label(text="マイクロモーションマッピングにターゲットを設定してください", icon="ERROR")


def _draw_breathing_mapping(layout, settings) -> None:
    if not settings.breathing_enabled:
        return

    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_breathing_mappings", "",
        settings, "breathing_mappings",
        settings, "breathing_mappings_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blipsync.add_breathing_mapping", icon="ADD", text="")
    col.operator("blipsync.remove_breathing_mapping", icon="REMOVE", text="")

    if not settings.breathing_mappings:
        return

    mapping = settings.breathing_mappings[settings.breathing_mappings_index]
    layout.prop(mapping, "name", text="名前")
    layout.prop(mapping, "random_seed", text="ランダムシード")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="0 = マッピング名から自動生成", icon="BLANK1")

    mapping_index = settings.breathing_mappings_index
    _draw_collapsible_section(
        layout,
        mapping.targets,
        "呼吸ターゲット（自由指定）",
        "FORCE_TURBULENCE",
        lambda body, slot=mapping.targets, mi=mapping_index: _draw_bind_slot_content(
            body, slot, 0, mi,
            morph_add_op="blipsync.add_breathing_morph_bind",
            morph_remove_op="blipsync.remove_breathing_morph_bind",
            pose_add_op="blipsync.add_breathing_pose_bind",
            pose_remove_op="blipsync.remove_breathing_pose_bind",
            expr_index_prop="",
            pose_first=True,
            motion_pose_binds=True,
        ),
        preview=True,
    )


def _draw_micro_motion_mapping(layout, settings) -> None:
    if not settings.micro_motion_enabled:
        return

    row = layout.row()
    row.template_list(
        "BLIPSYNC_UL_micro_motion_mappings", "",
        settings, "micro_motion_mappings",
        settings, "micro_motion_mappings_index",
        rows=3,
    )
    col = row.column(align=True)
    col.operator("blipsync.add_micro_motion_mapping", icon="ADD", text="")
    col.operator("blipsync.remove_micro_motion_mapping", icon="REMOVE", text="")

    if not settings.micro_motion_mappings:
        return

    mapping = settings.micro_motion_mappings[settings.micro_motion_mappings_index]
    layout.prop(mapping, "name", text="名前")
    layout.prop(mapping, "gaze_control", text="視線制御")
    layout.prop(mapping, "random_seed", text="ランダムシード")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="0 = マッピング名から自動生成", icon="BLANK1")

    mapping_index = settings.micro_motion_mappings_index
    bind_ops = dict(
        morph_add_op="blipsync.add_micro_motion_morph_bind",
        morph_remove_op="blipsync.remove_micro_motion_morph_bind",
        pose_add_op="blipsync.add_micro_motion_pose_bind",
        pose_remove_op="blipsync.remove_micro_motion_pose_bind",
    )

    def _draw_slot(body, attr, label, icon, *, morph_only=False, pose_only=False, motion_pose_binds=False):
        _draw_bind_slot_content(
            body, getattr(mapping, attr), 0, mapping_index,
            slot_attr=attr,
            morph_only=morph_only,
            pose_only=pose_only,
            pose_first=True,
            motion_pose_binds=motion_pose_binds,
            **bind_ops,
        )

    _draw_collapsible_section(
        layout,
        mapping.head,
        "頭",
        "OBJECT_DATA",
        lambda body: _draw_slot(body, "head", "頭", "OBJECT_DATA", pose_only=True),
        preview=True,
    )

    if mapping.gaze_control == "BONE":
        for attr, label in MICRO_MOTION_GAZE_BONE_SLOTS:
            _draw_collapsible_section(
                layout,
                getattr(mapping, attr),
                label,
                "HIDE_OFF",
                lambda body, a=attr: _draw_slot(body, a, label, "HIDE_OFF", pose_only=True),
                preview=True,
            )
    else:
        for attr, label in MICRO_MOTION_GAZE_SHAPE_SLOTS:
            _draw_collapsible_section(
                layout,
                getattr(mapping, attr),
                label,
                "HIDE_OFF",
                lambda body, a=attr: _draw_slot(body, a, label, "HIDE_OFF", morph_only=True),
                preview=True,
            )

    for attr, label, icon in (
        ("eyebrows", "眉", "GHOST_ENABLED"),
        ("mouth_open", "開口", "MOD_MASK"),
    ):
        _draw_collapsible_section(
            layout,
            getattr(mapping, attr),
            label,
            icon,
            lambda body, a=attr, ic=icon: _draw_slot(body, a, label, ic, motion_pose_binds=True),
            preview=True,
        )


def _draw_breathing_params(layout, settings) -> None:
    if not settings.breathing_enabled:
        return
    layout.label(text="呼吸", icon="FORCE_TURBULENCE")
    layout.prop(settings, "breathing_bpm")
    layout.prop(settings, "breathing_exhale_ratio")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="安静時 12〜18 回/分、吸:呼 = 1:N（N=1.5〜2）", icon="BLANK1")


def _draw_micro_motion_params(layout, settings) -> None:
    if not settings.micro_motion_enabled:
        box = layout.box()
        box.label(text="基礎設定で Enable Micro Motion をオンにしてください", icon="INFO")
        return
    layout.label(text="頭部揺れ", icon="OBJECT_DATA")
    layout.prop(settings, "micro_head_sway_amplitude")
    layout.prop(settings, "micro_head_sway_interval_min")
    layout.prop(settings, "micro_head_sway_interval_max")
    layout.prop(settings, "micro_head_sway_motion_time_min")
    layout.prop(settings, "micro_head_sway_motion_time_max")
    layout.separator()
    layout.label(text="視線サッカード", icon="HIDE_OFF")
    layout.prop(settings, "micro_saccade_enabled")
    if settings.micro_saccade_enabled:
        layout.prop(settings, "micro_saccade_interval_min")
        layout.prop(settings, "micro_saccade_interval_max")
        layout.prop(settings, "micro_saccade_travel_time")
        layout.prop(settings, "micro_saccade_return_time")
        has_bone_gaze = any(
            m.gaze_control == "BONE" for m in settings.micro_motion_mappings
        )
        has_shape_gaze = any(
            m.gaze_control == "SHAPE_KEY" for m in settings.micro_motion_mappings
        )
        if has_bone_gaze or not settings.micro_motion_mappings:
            layout.prop(settings, "micro_saccade_amplitude_deg")
        if has_shape_gaze:
            layout.prop(settings, "micro_saccade_intensity")
    layout.separator()
    layout.label(text="眉・開口マイクロ変動", icon="GHOST_ENABLED")
    layout.prop(settings, "micro_facial_noise_intensity")


def _draw_breathing_bake(layout, scene, settings) -> None:
    layout.prop(settings, "motion_bake_use_range", text="範囲を指定")
    if settings.motion_bake_use_range:
        layout.prop(settings, "motion_bake_frame_start")
        layout.prop(settings, "motion_bake_frame_end")
    else:
        layout.label(text=f"範囲: {scene.frame_start} – {scene.frame_end}（シーン設定）", icon="TIME")
    layout.prop(settings, "motion_bake_step")
    hint = layout.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="1 = 毎フレーム、2 = 1フレームおき…", icon="BLANK1")
    layout.separator()
    col = layout.column(align=True)
    op = col.operator("blipsync.bake_motion", text="呼吸のみベイク", icon="FORCE_TURBULENCE")
    op.bake_breathing = True
    op.bake_micro_motion = False
    op = col.operator("blipsync.bake_motion", text="マイクロモーションベイク", icon="OBJECT_DATA")
    op.bake_breathing = False
    op.bake_micro_motion = True
    op = col.operator("blipsync.bake_motion", text="呼吸 + マイクロモーションをベイク", icon="ANIM")
    op.bake_breathing = True
    op.bake_micro_motion = True


def _draw_emotion_vad_pivot_help(layout, settings) -> None:
    box = layout.box()
    box.label(text="Valence / Arousal 偏り調整", icon="INFO")
    col = box.column(align=True)
    col.scale_y = 0.85
    col.label(text="モデル出力を 0.5=中立 として再スケールし、")
    col.label(text="Happy / Sad / Angry / Neutral へ分配する前処理です。")
    col.label(text="0.50 = モデル出力そのまま（無変換）")
    box.separator()
    box.prop(settings, "emotion_valence_pivot")
    hint = box.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="Valence: 下げる → Sad/Angry が出にくい（ポジティブ寄り）")
    hint.label(text="          上げる → Sad/Angry が出やすい")
    box.separator()
    box.prop(settings, "emotion_arousal_pivot")
    hint = box.column(align=True)
    hint.scale_y = 0.85
    hint.label(text="Arousal: 下げる → 高テンション（Happy 強・Angry）が出やすい")
    hint.label(text="         上げる → 低テンション（Sad・穏やか Neutral）が出やすい")


def _draw_advanced(layout, settings):
    layout.operator("blipsync.reload_profile", text="Profile キャッシュを再読込")
    layout.label(text="リップシンク", icon="SPEAKER")
    layout.prop(settings, "use_phoneme_blend")
    layout.prop(settings, "smoothness")
    layout.prop(settings, "min_volume")
    layout.prop(settings, "max_volume")
    layout.prop(settings, "max_blend_value")
    layout.separator()
    layout.label(text="感情同期", icon="HEART")
    layout.prop(settings, "emotion_high_threshold_happy")
    layout.prop(settings, "emotion_high_threshold_sad")
    layout.prop(settings, "emotion_high_threshold_angry")
    layout.prop(settings, "emotion_smoothness")
    layout.prop(settings, "emotion_threshold")
    layout.separator()
    _draw_emotion_vad_pivot_help(layout, settings)
    layout.separator()
    layout.label(text="診断 / レンダー", icon="CONSOLE")
    layout.prop(settings, "realtime_during_render")
    layout.prop(settings, "debug_profile_ticks")
    layout.prop(settings, "debug_profile_render")
    layout.operator("blipsync.profile_tick", text="現在フレームの処理時間を計測", icon="TIME")


class BLIpsync_UL_channel_targets(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_channel_targets"

    def draw_item(self, context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        settings = context.scene.blipsync
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=_channel_display(context.scene, item), icon="SOUND")
        mapping = peek_channel_mapping(settings, item)
        mapping_name = mapping.name if mapping else "?"
        emotion_mapping = peek_channel_emotion_mapping(settings, item)
        emotion_name = emotion_mapping.name if emotion_mapping else "?"
        row.label(text=f"{_profile_source_label(item.profile_source)} / {mapping_name} / {emotion_name}")


class BLIpsync_UL_phoneme_mappings(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_phoneme_mappings"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or f"Mapping {_index + 1}", icon="RNA")


class BLIpsync_UL_emotion_mappings(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_emotion_mappings"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or f"Emotion {_index + 1}", icon="RNA")


class BLIpsync_UL_blink_mappings(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_blink_mappings"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or f"Blink {_index + 1}", icon="RNA")


class BLIpsync_UL_breathing_mappings(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_breathing_mappings"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or f"Breathing {_index + 1}", icon="RNA")


class BLIpsync_UL_micro_motion_mappings(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_micro_motion_mappings"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name or f"Micro Motion {_index + 1}", icon="RNA")


class BLIpsync_UL_morph_binds(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_morph_binds"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=_morph_bind_label(item), icon="SHAPEKEY_DATA")


class BLIpsync_UL_pose_binds(bpy.types.UIList):
    bl_idname = "BLIPSYNC_UL_pose_binds"

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=_pose_bind_label(item), icon="BONE_DATA")


class BLIpsync_PT_root(Panel):
    """Root panel: keeps the BlipSync sidebar tab visible (same role as 0.3.4)."""

    bl_label = "BlipSync"
    bl_idname = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="SPEAKER")

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        self.layout.label(text="リップシンク設定", icon="SPEAKER")


class BLIpsync_PT_basic(Panel):
    bl_label = "基礎設定"
    bl_idname = "BLIPSYNC_PT_basic"
    bl_parent_id = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_basic(self.layout, scene, settings)


class BLIpsync_PT_phoneme(Panel):
    bl_label = "音素マッピング A / I / U / E / O / -"
    bl_idname = "BLIPSYNC_PT_phoneme"
    bl_parent_id = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_phoneme_mapping(self.layout, settings)


class BLIpsync_PT_emotion(Panel):
    bl_label = "感情マッピング Happy / Sad / Angry / Neutral"
    bl_idname = "BLIPSYNC_PT_emotion"
    bl_parent_id = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_emotion_mapping(self.layout, settings)


class BLIpsync_PT_advanced(Panel):
    bl_label = "詳細設定"
    bl_idname = "BLIPSYNC_PT_advanced"
    bl_parent_id = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_advanced(self.layout, settings)


class BLIpsync_PT_bake(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BLIPSYNC_PT_bake"
    bl_parent_id = "BLIPSYNC_PT_root"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlipSync"
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


class BLIpsync_PT_root_seq(Panel):
    bl_label = "BlipSync"
    bl_idname = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw_header(self, _context):
        self.layout.label(icon="SPEAKER")

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        self.layout.label(text="リップシンク設定", icon="SPEAKER")


class BLIpsync_PT_basic_seq(Panel):
    bl_label = "基礎設定"
    bl_idname = "BLIPSYNC_PT_basic_seq"
    bl_parent_id = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        scene = context.scene
        settings = _settings_or_init(self.layout, scene)
        if settings is None:
            return
        _draw_basic(self.layout, scene, settings)


class BLIpsync_PT_phoneme_seq(Panel):
    bl_label = "音素マッピング A / I / U / E / O / -"
    bl_idname = "BLIPSYNC_PT_phoneme_seq"
    bl_parent_id = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_phoneme_mapping(self.layout, settings)


class BLIpsync_PT_emotion_seq(Panel):
    bl_label = "感情マッピング Happy / Sad / Angry / Neutral"
    bl_idname = "BLIPSYNC_PT_emotion_seq"
    bl_parent_id = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_emotion_mapping(self.layout, settings)


class BLIpsync_PT_advanced_seq(Panel):
    bl_label = "詳細設定"
    bl_idname = "BLIPSYNC_PT_advanced_seq"
    bl_parent_id = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _panel_poll(context)

    def draw(self, context):
        settings = _settings_or_init(self.layout, context.scene)
        if settings is None:
            return
        _draw_advanced(self.layout, settings)


class BLIpsync_PT_bake_seq(Panel):
    bl_label = "ベイク設定"
    bl_idname = "BLIPSYNC_PT_bake_seq"
    bl_parent_id = "BLIPSYNC_PT_root_seq"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "BlipSync"
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


list_classes = (
    BLIpsync_UL_channel_targets,
    BLIpsync_UL_phoneme_mappings,
    BLIpsync_UL_emotion_mappings,
    BLIpsync_UL_blink_mappings,
    BLIpsync_UL_breathing_mappings,
    BLIpsync_UL_micro_motion_mappings,
    BLIpsync_UL_morph_binds,
    BLIpsync_UL_pose_binds,
)

panel_classes = (
    BLIpsync_PT_root,
    BLIpsync_PT_basic,
    BLIpsync_PT_phoneme,
    BLIpsync_PT_emotion,
    BLIpsync_PT_advanced,
    BLIpsync_PT_bake,
    BLIpsync_PT_root_seq,
    BLIpsync_PT_basic_seq,
    BLIpsync_PT_phoneme_seq,
    BLIpsync_PT_emotion_seq,
    BLIpsync_PT_advanced_seq,
    BLIpsync_PT_bake_seq,
)

classes = list_classes + panel_classes


def _cleanup_stale_panels() -> None:
    stale = []
    for cls in Panel.__subclasses__():
        bl_idname = getattr(cls, "bl_idname", "")
        if bl_idname.startswith(_PANEL_ID_PREFIX) or getattr(cls, "bl_category", "") == "BlipSync":
            stale.append(cls)
    for cls in reversed(stale):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def cleanup_blipsync_panels() -> None:
    """Remove BlipSync sidebar panels (used when only bAnima UI should appear)."""
    _cleanup_stale_panels()


def register_lists():
    from .registration import register_classes

    register_classes(list_classes)


def unregister_lists():
    from .registration import unregister_classes

    unregister_classes(list_classes)


def register_panels():
    _cleanup_stale_panels()
    from .registration import register_classes

    register_classes(panel_classes)


def unregister_panels():
    from .registration import unregister_classes

    unregister_classes(panel_classes)
    _cleanup_stale_panels()


def register():
    register_lists()
    register_panels()


def unregister():
    unregister_panels()
    unregister_lists()
