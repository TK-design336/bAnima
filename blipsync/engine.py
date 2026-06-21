"""Lip sync analysis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import bpy

from .algorithm import analyze_chunk, normalize_volume
from .audio import estimate_output_sample_rate, frame_to_seconds, mix_audio_at_time
from .profile import LipSyncProfile, resolve_profile
from .properties import PHONEME_LABELS


def smooth_damp(current, target, velocity, smoothness, dt):
    if smoothness <= 1e-8:
        return target, 0.0
    omega = 2.0 / smoothness
    x = omega * dt
    exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * exp
    return target + (change + temp) * exp, velocity


def map_phoneme_for_lipsync(raw: str) -> str:
    return raw if raw in PHONEME_LABELS else "-"


def mapped_phoneme_ratios(ratios: Dict[str, float]) -> Dict[str, float]:
    mapped = {label: 0.0 for label in PHONEME_LABELS}
    for name, value in ratios.items():
        mapped[map_phoneme_for_lipsync(name)] += value
    return mapped


@dataclass
class LipSyncResult:
    phoneme: str = "-"
    raw_phoneme: str = "-"
    volume: float = 0.0
    raw_volume: float = 0.0
    phoneme_ratios: Dict[str, float] = field(default_factory=dict)


@dataclass
class MappingState:
    weight: float = 0.0
    velocity: float = 0.0


@dataclass
class ChannelSmoothingState:
    ring_index: int = 0
    volume: float = 0.0
    volume_velocity: float = 0.0
    mapping_states: Dict[str, MappingState] = field(default_factory=dict)


class LipSyncEngine:
    def __init__(self) -> None:
        self._channel_states: Dict[int, ChannelSmoothingState] = {}
        self.last_results: Dict[int, LipSyncResult] = {}
        self.last_result = LipSyncResult()

    def _channel_state(self, channel: int) -> ChannelSmoothingState:
        if channel not in self._channel_states:
            self._channel_states[channel] = ChannelSmoothingState()
        return self._channel_states[channel]

    def analyze_channel(
        self,
        scene: bpy.types.Scene,
        frame: float,
        channel_target,
    ) -> LipSyncResult:
        settings = scene.blipsync
        profile = resolve_profile(channel_target.profile_source, channel_target.profile_path)
        channels = {channel_target.channel}
        time_sec = frame_to_seconds(scene, frame)
        output_rate = estimate_output_sample_rate(scene, channels)
        sample_count = profile.input_sample_count(output_rate)

        samples, rate = mix_audio_at_time(scene, time_sec, channels, sample_count, output_rate)
        if samples.size < sample_count:
            padded = samples
            samples = samples.__class__.zeros(sample_count, dtype=samples.dtype)
            samples[: padded.size] = padded

        state = self._channel_state(channel_target.channel)
        scores, raw_volume, main_index = analyze_chunk(
            samples,
            state.ring_index,
            rate,
            profile.target_sample_rate,
            profile.mel_filter_bank_channels,
            profile.mfcc_num,
            profile.phonemes,
            profile.means,
            profile.std_devs,
            profile.compare_method,
        )
        state.ring_index = (state.ring_index + 1) % max(sample_count, 1)

        ratios = {name: float(scores[i]) for i, name in enumerate(profile.phoneme_names)}
        raw_phoneme = profile.phoneme_names[main_index] if 0 <= main_index < len(profile.phoneme_names) else "-"
        phoneme = map_phoneme_for_lipsync(raw_phoneme)
        volume = normalize_volume(raw_volume, settings.min_volume, settings.max_volume)

        result = LipSyncResult(
            phoneme=phoneme,
            raw_phoneme=raw_phoneme,
            volume=volume,
            raw_volume=raw_volume,
            phoneme_ratios=ratios,
        )
        self.last_results[channel_target.channel] = result
        self.last_result = result
        return result

    def update_smoothed_weights(
        self,
        scene: bpy.types.Scene,
        result: LipSyncResult,
        dt: float,
        channel: int,
        phoneme_mapping,
    ) -> Dict[str, float]:
        settings = scene.blipsync
        state = self._channel_state(channel)
        target_volume = result.volume if result.raw_volume > 0 else 0.0
        state.volume, state.volume_velocity = smooth_damp(
            state.volume,
            target_volume,
            state.volume_velocity,
            settings.smoothness,
            dt,
        )

        weights: Dict[str, float] = {}
        sum_weight = 0.0

        for expr in phoneme_mapping.phoneme_exprs:
            phoneme = expr.label
            if phoneme not in state.mapping_states:
                state.mapping_states[phoneme] = MappingState()
            mapping_state = state.mapping_states[phoneme]

            blend_ratios = mapped_phoneme_ratios(result.phoneme_ratios)
            if settings.use_phoneme_blend:
                target = blend_ratios.get(phoneme, 0.0)
            else:
                target = 1.0 if phoneme == result.phoneme else 0.0

            mapping_state.weight, mapping_state.velocity = smooth_damp(
                mapping_state.weight,
                target,
                mapping_state.velocity,
                settings.smoothness,
                dt,
            )
            weights[phoneme] = mapping_state.weight
            sum_weight += mapping_state.weight

        if sum_weight > 0:
            for key in list(weights.keys()):
                weights[key] /= sum_weight

        weights["__volume__"] = state.volume
        return weights

    def reset_smoothing(self, channel: Optional[int] = None) -> None:
        if channel is None:
            self._channel_states.clear()
            self.last_results.clear()
            self.last_result = LipSyncResult()
            return
        self._channel_states.pop(channel, None)
        self.last_results.pop(channel, None)


_ENGINE = LipSyncEngine()


def get_engine() -> LipSyncEngine:
    return _ENGINE
