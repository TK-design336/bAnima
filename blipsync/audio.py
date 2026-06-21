"""Sequencer audio extraction for lip sync."""

from __future__ import annotations

import os
from typing import Dict, Optional, Set, Tuple

import numpy as np

try:
    import aud
except ImportError:
    aud = None

import bpy

from .sequencer import get_strips_on_channels

_sound_cache: Dict[str, Tuple[np.ndarray, int, int]] = {}


def _resolve_sound_path(sound: bpy.types.Sound) -> Optional[str]:
    if sound.packed_file:
        import tempfile

        suffix = os.path.splitext(sound.filepath or ".wav")[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(sound.packed_file.data)
        tmp.close()
        return tmp.name
    path = bpy.path.abspath(sound.filepath)
    return path if path and os.path.isfile(path) else None


def _sound_cache_key(sound: bpy.types.Sound) -> str:
    if sound.filepath and not sound.packed_file:
        path = bpy.path.abspath(sound.filepath)
        if path and os.path.isfile(path):
            return path
    return f"blend:{sound.as_pointer()}"


def _samples_from_aud_data(data) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.shape[1] == 1:
        return arr[:, 0]
    return arr.mean(axis=1).astype(np.float32)


def _load_from_aud_sound(snd) -> Tuple[np.ndarray, int]:
    rate = int(snd.specs[0])
    channels = int(snd.specs[1])

    if hasattr(snd, "data"):
        if hasattr(aud.Sound, "cache"):
            snd = aud.Sound.cache(snd)
        return _samples_from_aud_data(snd.data()), rate

    if hasattr(snd, "createReader"):
        count = int(snd.length * rate)
        if count <= 0:
            return np.zeros(0, dtype=np.float32), rate
        reader = snd.createReader()
        arr = np.array(reader.read(count), dtype=np.float32)
        if channels > 1:
            arr = arr.reshape(-1, channels).mean(axis=1)
        return arr, rate

    raise AttributeError("Unsupported aud.Sound API")


def _load_with_wave(path: str) -> Tuple[np.ndarray, int]:
    import wave

    with wave.open(path, "rb") as wf:
        rate = wf.getframerate()
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
        dtype = np.int16 if wf.getsampwidth() == 2 else np.int8
        arr = np.frombuffer(frames, dtype=dtype).astype(np.float32)
        arr /= 32768.0 if dtype == np.int16 else 128.0
        if channels > 1:
            arr = arr.reshape(-1, channels).mean(axis=1)
        return arr, rate


def _load_sound(sound: bpy.types.Sound) -> Tuple[np.ndarray, int, int]:
    key = _sound_cache_key(sound)
    if key in _sound_cache:
        return _sound_cache[key]

    samples = np.zeros(0, dtype=np.float32)
    rate = int(getattr(sound, "samplerate", 0) or 0)

    if aud is not None:
        factory = getattr(sound, "factory", None)
        if factory is not None:
            try:
                samples, rate = _load_from_aud_sound(factory)
            except Exception:
                samples = np.zeros(0, dtype=np.float32)

        if samples.size == 0:
            path = _resolve_sound_path(sound)
            if path:
                try:
                    if hasattr(aud.Sound, "file"):
                        snd = aud.Sound.file(path)
                    else:
                        snd = aud.Sound(path)
                    samples, rate = _load_from_aud_sound(snd)
                except Exception:
                    samples = np.zeros(0, dtype=np.float32)

    if samples.size == 0:
        path = _resolve_sound_path(sound)
        if not path:
            result = (samples, rate or 48000, 1)
            _sound_cache[key] = result
            return result
        try:
            samples, rate = _load_with_wave(path)
        except Exception:
            samples = np.zeros(0, dtype=np.float32)
            rate = rate or 48000

    result = (samples, rate or 48000, 1)
    _sound_cache[key] = result
    return result


def clear_sound_cache() -> None:
    _sound_cache.clear()


def scene_fps(scene: bpy.types.Scene) -> float:
    return scene.render.fps / scene.render.fps_base


def frame_to_seconds(scene: bpy.types.Scene, frame: float) -> float:
    return (frame - scene.frame_start) / scene_fps(scene)


def mix_audio_at_time(
    scene: bpy.types.Scene,
    time_sec: float,
    channels: Set[int],
    sample_count: int,
    sample_rate: int,
) -> Tuple[np.ndarray, int]:
    """Mix all SOUND strips on the selected VSE channels."""
    strips = get_strips_on_channels(scene, channels)
    if not strips:
        return np.zeros(sample_count, dtype=np.float32), sample_rate

    mixed = np.zeros(sample_count, dtype=np.float64)
    used = False
    fps = scene_fps(scene)

    for strip in strips:
        strip_start = frame_to_seconds(scene, strip.frame_start)
        strip_end = strip_start + strip.frame_final_duration / fps
        if time_sec < strip_start or time_sec > strip_end:
            continue

        sound = getattr(strip, "sound", None)
        if not sound:
            continue

        samples, src_rate, _ = _load_sound(sound)
        if samples.size == 0:
            continue

        local_sec = time_sec - strip_start
        pitch = getattr(strip, "pitch", 1.0)
        local_sec *= pitch

        offset_sec = 0.0
        if hasattr(strip, "frame_offset"):
            offset_sec = strip.frame_offset / fps

        center_index = int((local_sec + offset_sec) * src_rate)
        half = sample_count * src_rate // (2 * sample_rate)
        start = max(0, center_index - half)
        end = min(samples.size, start + int(sample_count * src_rate / sample_rate) + 1)
        if start >= end:
            continue

        chunk = samples[start:end]
        if src_rate != sample_rate:
            indices = np.linspace(0, chunk.size - 1, sample_count)
            resampled = np.interp(indices, np.arange(chunk.size), chunk)
        else:
            resampled = np.zeros(sample_count, dtype=np.float64)
            n = min(sample_count, chunk.size)
            resampled[:n] = chunk[:n]

        mixed += resampled * getattr(strip, "volume", 1.0)
        used = True

    if not used:
        return np.zeros(sample_count, dtype=np.float32), sample_rate
    return mixed.astype(np.float32), sample_rate


def estimate_output_sample_rate(scene: bpy.types.Scene, channels: Set[int]) -> int:
    for strip in get_strips_on_channels(scene, channels):
        sound = getattr(strip, "sound", None)
        if not sound:
            continue
        _, rate, _ = _load_sound(sound)
        if rate > 0:
            return rate
    return 48000
