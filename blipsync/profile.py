"""uLipSync profile loading."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from .algorithm import CompareMethod


@dataclass
class LipSyncProfile:
    mfcc_num: int = 12
    mel_filter_bank_channels: int = 30
    target_sample_rate: int = 16000
    sample_count: int = 1024
    use_standardization: bool = False
    compare_method: CompareMethod = "cosine_similarity"
    phoneme_names: List[str] = field(default_factory=list)
    phonemes: np.ndarray = field(default_factory=lambda: np.zeros((0, 12)))
    means: np.ndarray = field(default_factory=lambda: np.zeros(12))
    std_devs: np.ndarray = field(default_factory=lambda: np.ones(12))

    def input_sample_count(self, output_sample_rate: int) -> int:
        import math

        ratio = output_sample_rate / self.target_sample_rate
        return int(math.ceil(self.sample_count * ratio))

    @classmethod
    def from_dict(cls, data: dict) -> "LipSyncProfile":
        phoneme_map: Dict[str, List[float]] = data.get("phonemes", {})
        names = list(phoneme_map.keys())
        mfcc_num = int(data.get("mfcc_num", 12))
        phonemes = np.array(
            [phoneme_map[name] for name in names], dtype=np.float64
        )
        profile = cls(
            mfcc_num=mfcc_num,
            mel_filter_bank_channels=int(data.get("mel_filter_bank_channels", 30)),
            target_sample_rate=int(data.get("target_sample_rate", 16000)),
            sample_count=int(data.get("sample_count", 1024)),
            use_standardization=bool(data.get("use_standardization", False)),
            compare_method=data.get("compare_method", "cosine_similarity"),
            phoneme_names=names,
            phonemes=phonemes,
        )
        profile._update_standardization(phoneme_map)
        return profile

    def _update_standardization(self, phoneme_map: Dict[str, List[float]]) -> None:
        self.means = np.zeros(self.mfcc_num, dtype=np.float64)
        self.std_devs = np.ones(self.mfcc_num, dtype=np.float64)
        if not self.use_standardization:
            return

        values = []
        for coeffs in phoneme_map.values():
            values.append(coeffs)
        arr = np.array(values, dtype=np.float64)
        self.means = np.mean(arr, axis=0)
        self.std_devs = np.std(arr, axis=0)
        self.std_devs[self.std_devs < 1e-8] = 1.0

    @classmethod
    def load_json(cls, path: str) -> "LipSyncProfile":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def _data_path(cls, filename: str) -> str:
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(addon_dir, "data", filename)

    @classmethod
    def load_male(cls) -> "LipSyncProfile":
        return cls.load_json(cls._data_path("default_profile.json"))

    @classmethod
    def load_female(cls) -> "LipSyncProfile":
        return cls.load_json(cls._data_path("female_profile.json"))

    @classmethod
    def load_default(cls) -> "LipSyncProfile":
        return cls.load_male()


_PROFILE_CACHE: Dict[str, LipSyncProfile] = {}


def clear_profile_cache() -> None:
    _PROFILE_CACHE.clear()


def resolve_profile(source: str, custom_path: str = "") -> LipSyncProfile:
    import bpy

    if source == "FEMALE":
        cache_key = "FEMALE"
        loader = LipSyncProfile.load_female
    elif source == "CUSTOM":
        path = bpy.path.abspath(custom_path) if custom_path else ""
        if not path or not os.path.isfile(path):
            cache_key = "MALE"
            loader = LipSyncProfile.load_male
        else:
            cache_key = f"CUSTOM:{path}"
            loader = lambda: LipSyncProfile.load_json(path)
    else:
        cache_key = "MALE"
        loader = LipSyncProfile.load_male

    if cache_key not in _PROFILE_CACHE:
        _PROFILE_CACHE[cache_key] = loader()
    return _PROFILE_CACHE[cache_key]
