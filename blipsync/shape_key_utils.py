"""Shape key helpers for morph bind weights."""

from __future__ import annotations

import bpy

WEIGHT_UI_KEY = "weight_ui"


def get_shape_key_block(mesh: bpy.types.Object | None, shape_key_name: str):
    if not mesh or mesh.type != "MESH" or not mesh.data or not shape_key_name:
        return None
    keys = mesh.data.shape_keys
    if not keys:
        return None
    return keys.key_blocks.get(shape_key_name)


def shape_key_range(mesh: bpy.types.Object | None, shape_key_name: str) -> tuple[float, float]:
    kb = get_shape_key_block(mesh, shape_key_name)
    if kb is None:
        return 0.0, 1.0
    return float(kb.slider_min), float(kb.slider_max)


def clamp_weight_value(bind, value: float) -> float:
    kb = get_shape_key_block(bind.mesh, bind.shape_key)
    if kb is None:
        return float(value)
    return max(float(kb.slider_min), min(float(kb.slider_max), float(value)))


def get_morph_bind_weight(bind) -> float:
    if WEIGHT_UI_KEY in bind:
        return float(bind[WEIGHT_UI_KEY])
    return float(bind.weight_value)


def sync_morph_weight_ui(bind) -> None:
    """Update per-bind custom weight UI limits from the target shape key."""
    bind_id = id(bind)
    if bind_id in _WEIGHT_SYNC_GUARD:
        return
    _WEIGHT_SYNC_GUARD.add(bind_id)
    try:
        kb = get_shape_key_block(bind.mesh, bind.shape_key)
        if kb is None:
            soft_min, soft_max = 0.0, 1.0
        else:
            soft_min = float(kb.slider_min)
            soft_max = float(kb.slider_max)
        if soft_max <= soft_min:
            soft_max = soft_min + 1.0

        clamped = clamp_weight_value(bind, bind.weight_value)
        if abs(clamped - float(bind.weight_value)) > 1e-9:
            bind.weight_value = clamped
        bind[WEIGHT_UI_KEY] = clamped
        bind.id_properties_ui(WEIGHT_UI_KEY).update(
            soft_min=soft_min,
            soft_max=soft_max,
            min=soft_min,
            max=soft_max,
            description="音素が最大のときのシェイプキー値",
        )
    finally:
        _WEIGHT_SYNC_GUARD.discard(bind_id)


_WEIGHT_SYNC_GUARD: set[int] = set()
_WEIGHT_SYNC_PENDING: dict[int, tuple[object, float]] = {}
_WEIGHT_SYNC_TIMER = None


def schedule_morph_weight_sync(bind, value: float) -> None:
    """Defer bind.weight_value writes until after UI draw."""
    global _WEIGHT_SYNC_TIMER

    _WEIGHT_SYNC_PENDING[id(bind)] = (bind, float(value))
    if _WEIGHT_SYNC_TIMER is None:
        _WEIGHT_SYNC_TIMER = bpy.app.timers.register(_flush_morph_weight_sync, first_interval=0)


def _flush_morph_weight_sync():
    global _WEIGHT_SYNC_TIMER

    _WEIGHT_SYNC_TIMER = None
    pending = dict(_WEIGHT_SYNC_PENDING)
    _WEIGHT_SYNC_PENDING.clear()
    for bind, value in pending.values():
        try:
            bind_id = id(bind)
            if bind_id in _WEIGHT_SYNC_GUARD:
                continue
            _WEIGHT_SYNC_GUARD.add(bind_id)
            try:
                clamped = clamp_weight_value(bind, value)
                if abs(clamped - float(bind.weight_value)) > 1e-9:
                    bind.weight_value = clamped
            finally:
                _WEIGHT_SYNC_GUARD.discard(bind_id)
        except (ReferenceError, AttributeError):
            pass
    return None
