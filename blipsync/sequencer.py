"""VSE strip access (Blender 3.6 - 5.x compatible)."""

from __future__ import annotations

import bpy


def get_sequence_editor(scene: bpy.types.Scene):
    return scene.sequence_editor


def iter_strips(seq) -> list:
    if seq is None:
        return []
    for attr in ("sequences_all", "sequences", "strips"):
        strips = getattr(seq, attr, None)
        if strips is not None:
            return list(strips)
    return []


def strip_type(strip) -> str:
    t = getattr(strip, "type", None)
    if t is None:
        return ""
    if hasattr(t, "idname"):
        return str(t.idname)
    return str(t)


def is_sound_strip(strip) -> bool:
    t = strip_type(strip).upper()
    return "SOUND" in t


def strip_display_name(strip) -> str:
    name = getattr(strip, "name", "") or ""
    if name:
        return name
    sound = getattr(strip, "sound", None)
    if sound and getattr(sound, "name", None):
        return sound.name
    return f"Sound Ch{getattr(strip, 'channel', 0)}"


def collect_sound_strips(scene: bpy.types.Scene) -> list:
    seq = get_sequence_editor(scene)
    result = []
    for strip in iter_strips(seq):
        if not is_sound_strip(strip):
            continue
        if getattr(strip, "mute", False):
            continue
        result.append(strip)
    return result


def collect_channels_with_sound(scene: bpy.types.Scene) -> dict[int, list]:
    channels: dict[int, list] = {}
    for strip in collect_sound_strips(scene):
        ch = int(getattr(strip, "channel", 0))
        if ch <= 0:
            continue
        channels.setdefault(ch, []).append(strip)
    return channels


def channel_label(channel: int, strips: list | None = None) -> str:
    if not strips:
        return f"Channel {channel}"
    names = [strip_display_name(s) for s in strips[:3]]
    text = ", ".join(names)
    if len(strips) > 3:
        text += f" (+{len(strips) - 3})"
    return f"Channel {channel}: {text}" if text else f"Channel {channel}"


def get_strips_on_channels(scene: bpy.types.Scene, channels: set[int]) -> list:
    if not channels:
        return []
    return [
        s for s in collect_sound_strips(scene)
        if int(getattr(s, "channel", 0)) in channels
    ]
