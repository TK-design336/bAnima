"""Emotion recognition engine (audeering wav2vec2 ONNX via onnxruntime)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import bpy
import numpy as np

from .audio import estimate_output_sample_rate, frame_to_seconds, mix_audio_at_time
from .engine import smooth_damp
from .emotion_onnx import (
    EMOTION_TARGET_RATE,
    clear_session_cache,
    get_download_progress,
    get_session_error,
    is_session_available,
    predict_vad,
    vad_to_emotion_scores,
)
from .properties import EMOTION_LABELS

EMOTION_BACKEND = "audeering-onnx"
EMOTION_SAMPLE_COUNT = 16000  # ~1 s window at 16 kHz


def get_emotion_backend() -> str:
    return EMOTION_BACKEND


def emotion_deps_install_hint() -> str:
    from .deps_installer import get_install_error, get_install_status

    progress = get_download_progress()
    if progress:
        return progress

    status = get_install_status()
    if status == "installing":
        return "感情認識ライブラリ（onnxruntime）をインストール中です。"
    if status == "failed":
        err = get_install_error()
        return err or "インストールに失敗しました。再試行ボタンを押してください。"
    if status == "ok":
        return "インストール済みです。「再検出」を押すか Blender を再起動してください。"
    return "初回有効化時に onnxruntime を自動インストールします。"


def speechbrain_install_hint() -> str:
    """Deprecated alias."""
    return emotion_deps_install_hint()


@dataclass
class EmotionResult:
    happy: float = 0.0
    sad: float = 0.0
    angry: float = 0.0
    neutral: float = 1.0
    dominant: str = "neutral"
    valence: float = 0.5
    arousal: float = 0.5
    dominance: float = 0.5
    confidence: float = 0.0


@dataclass
class EmotionChannelState:
    happy: float = 0.0
    happy_velocity: float = 0.0
    sad: float = 0.0
    sad_velocity: float = 0.0
    angry: float = 0.0
    angry_velocity: float = 0.0
    neutral: float = 1.0
    neutral_velocity: float = 0.0


def get_classifier_error() -> Optional[str]:
    err = get_session_error()
    progress = get_download_progress()
    if progress:
        return progress
    return err


def is_classifier_available() -> bool:
    return is_session_available()


def clear_classifier_cache() -> None:
    reset_classifier_state()


def reset_classifier_state() -> None:
    clear_session_cache()


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    count = max(1, int(samples.size * dst_rate / src_rate))
    indices = np.linspace(0, samples.size - 1, count)
    return np.interp(indices, np.arange(samples.size), samples).astype(np.float32)


def _prepare_window(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    wav = _resample(samples, sample_rate, EMOTION_TARGET_RATE)
    if wav.size < EMOTION_SAMPLE_COUNT:
        padded = np.zeros(EMOTION_SAMPLE_COUNT, dtype=np.float32)
        padded[: wav.size] = wav
        wav = padded
    else:
        start = max(0, (wav.size - EMOTION_SAMPLE_COUNT) // 2)
        wav = wav[start : start + EMOTION_SAMPLE_COUNT]
    return wav


def analyze_samples(
    samples: np.ndarray,
    sample_rate: int,
    *,
    valence_pivot: float = 0.5,
    arousal_pivot: float = 0.5,
) -> Tuple[EmotionResult, Optional[str]]:
    if not is_session_available():
        return EmotionResult(), get_classifier_error() or "onnxruntime が利用できません"

    if samples.size == 0:
        return EmotionResult(), None

    try:
        wav = _prepare_window(samples, sample_rate)
        vad = predict_vad(wav, EMOTION_TARGET_RATE)
        dominant, confidence, happy, sad, angry, neutral = vad_to_emotion_scores(
            vad["valence"],
            vad["arousal"],
            valence_pivot=valence_pivot,
            arousal_pivot=arousal_pivot,
        )
        return EmotionResult(
            happy=happy,
            sad=sad,
            angry=angry,
            neutral=neutral,
            dominant=dominant,
            valence=vad["valence"],
            arousal=vad["arousal"],
            dominance=vad["dominance"],
            confidence=confidence,
        ), None
    except Exception as exc:
        return EmotionResult(), str(exc)


def _apply_dead_zone(value: float, threshold: float) -> float:
    if threshold <= 0.0:
        return value
    if value < threshold:
        return 0.0
    return (value - threshold) / max(1e-8, 1.0 - threshold)


def _split_normal_high(score: float, threshold: float) -> Tuple[float, float]:
    threshold = max(0.01, min(0.99, threshold))
    score = max(0.0, min(1.0, score))
    if score <= threshold:
        return score / threshold, 0.0
    t = (score - threshold) / (1.0 - threshold)
    return 1.0 - t, t


def compute_slot_targets(settings, result: EmotionResult) -> Dict[str, float]:
    happy = _apply_dead_zone(result.happy, settings.emotion_threshold)
    sad = _apply_dead_zone(result.sad, settings.emotion_threshold)
    angry = _apply_dead_zone(result.angry, settings.emotion_threshold)
    neutral = _apply_dead_zone(result.neutral, settings.emotion_threshold)

    happy_n, happy_h = _split_normal_high(happy, settings.emotion_high_threshold_happy)
    sad_n, sad_h = _split_normal_high(sad, settings.emotion_high_threshold_sad)
    angry_n, angry_h = _split_normal_high(angry, settings.emotion_high_threshold_angry)

    return {
        "Happy": happy_n,
        "Happy_High": happy_h,
        "Sad": sad_n,
        "Sad_High": sad_h,
        "Angry": angry_n,
        "Angry_High": angry_h,
        "Neutral": neutral,
        "__raw_happy__": happy,
        "__raw_sad__": sad,
        "__raw_angry__": angry,
        "__raw_neutral__": neutral,
    }


class EmotionEngine:
    def __init__(self) -> None:
        self._channel_states: Dict[int, EmotionChannelState] = {}
        self.last_results: Dict[int, EmotionResult] = {}
        self.last_result = EmotionResult()
        self.last_error: Optional[str] = None

    def _channel_state(self, channel: int) -> EmotionChannelState:
        if channel not in self._channel_states:
            self._channel_states[channel] = EmotionChannelState()
        return self._channel_states[channel]

    def analyze_channel(
        self,
        scene: bpy.types.Scene,
        frame: float,
        channel_target,
    ) -> EmotionResult:
        settings = scene.blipsync
        channels = {channel_target.channel}
        time_sec = frame_to_seconds(scene, frame)
        output_rate = estimate_output_sample_rate(scene, channels)
        sample_count = max(EMOTION_SAMPLE_COUNT, output_rate // 2)

        samples, rate = mix_audio_at_time(scene, time_sec, channels, sample_count, output_rate)
        result, error = analyze_samples(
            samples,
            rate,
            valence_pivot=settings.emotion_valence_pivot,
            arousal_pivot=settings.emotion_arousal_pivot,
        )
        self.last_error = error
        self.last_results[channel_target.channel] = result
        self.last_result = result
        return result

    def update_smoothed_weights(
        self,
        scene: bpy.types.Scene,
        result: EmotionResult,
        dt: float,
        channel: int,
        emotion_mapping,
    ) -> Dict[str, float]:
        settings = scene.blipsync
        state = self._channel_state(channel)
        targets = compute_slot_targets(settings, result)
        smoothness = settings.emotion_smoothness

        for key, attr, vel_attr in (
            ("__raw_happy__", "happy", "happy_velocity"),
            ("__raw_sad__", "sad", "sad_velocity"),
            ("__raw_angry__", "angry", "angry_velocity"),
            ("__raw_neutral__", "neutral", "neutral_velocity"),
        ):
            current = getattr(state, attr)
            velocity = getattr(state, vel_attr)
            smoothed, new_velocity = smooth_damp(current, targets[key], velocity, smoothness, dt)
            setattr(state, attr, smoothed)
            setattr(state, vel_attr, new_velocity)

        smoothed_result = EmotionResult(
            happy=state.happy,
            sad=state.sad,
            angry=state.angry,
            neutral=state.neutral,
            dominant=result.dominant,
            valence=result.valence,
            arousal=result.arousal,
            dominance=result.dominance,
            confidence=result.confidence,
        )
        slot_targets = compute_slot_targets(settings, smoothed_result)
        return {label: slot_targets.get(label, 0.0) for label in EMOTION_LABELS}

    def reset_smoothing(self, channel: Optional[int] = None) -> None:
        if channel is None:
            self._channel_states.clear()
            self.last_results.clear()
            self.last_result = EmotionResult()
            self.last_error = None
            return
        self._channel_states.pop(channel, None)
        self.last_results.pop(channel, None)


_ENGINE = EmotionEngine()


def get_emotion_engine() -> EmotionEngine:
    return _ENGINE
