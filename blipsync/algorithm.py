"""uLipSync MFCC algorithm port for Blender."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

CompareMethod = Literal["l1_norm", "l2_norm", "cosine_similarity"]

DEFAULT_MIN_VOLUME = -2.5
DEFAULT_MAX_VOLUME = -1.5


def get_rms_volume(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(math.sqrt(np.mean(samples * samples)))


def copy_ring_buffer(data: np.ndarray, start_index: int) -> np.ndarray:
    n = data.size
    if n == 0:
        return data.copy()
    idx = np.arange(n)
    return data[(start_index + idx) % n].copy()


def normalize(data: np.ndarray, value: float = 1.0) -> np.ndarray:
    max_val = float(np.max(np.abs(data))) if data.size else 0.0
    if max_val < np.finfo(float).eps:
        return data
    return data * (value / max_val)


def low_pass_filter(
    data: np.ndarray, sample_rate: float, cutoff: float, range_hz: float
) -> np.ndarray:
    cutoff = (cutoff - range_hz) / sample_rate
    range_hz /= sample_rate
    tmp = data.copy()
    n = int(round(3.1 / range_hz))
    if (n + 1) % 2 == 0:
        n += 1
    b = np.zeros(n, dtype=np.float64)
    for i in range(n):
        x = i - (n - 1) / 2.0
        ang = 2.0 * math.pi * cutoff * x
        b[i] = 2.0 * cutoff * (math.sin(ang) / ang if abs(ang) > 1e-12 else 1.0)
    out = np.zeros_like(data, dtype=np.float64)
    for j in range(n):
        out[j:] += b[j] * tmp[: len(out) - j]
    return out


def down_sample(
    data: np.ndarray, sample_rate: int, target_sample_rate: int
) -> np.ndarray:
    if sample_rate <= target_sample_rate:
        return data.copy()
    if sample_rate % target_sample_rate == 0:
        skip = sample_rate // target_sample_rate
        return data[::skip].copy()
    df = sample_rate / target_sample_rate
    n = int(round(data.size / df))
    out = np.zeros(n, dtype=np.float64)
    for j in range(n):
        f_index = df * j
        i0 = int(math.floor(f_index))
        i1 = min(i0, data.size - 1)
        t = f_index - i0
        out[j] = data[i0] * (1.0 - t) + data[i1] * t
    return out


def pre_emphasis(data: np.ndarray, p: float = 0.97) -> np.ndarray:
    out = data.copy()
    tmp = data.copy()
    for i in range(1, len(out)):
        out[i] = tmp[i] - p * tmp[i - 1]
    return out


def hamming_window(data: np.ndarray) -> np.ndarray:
    out = data.copy()
    length = len(out)
    if length <= 1:
        return out
    for i in range(length):
        x = i / (length - 1)
        out[i] *= 0.54 - 0.46 * math.cos(2.0 * math.pi * x)
    return out


def fft_spectrum(data: np.ndarray) -> np.ndarray:
    spectrum = np.abs(np.fft.fft(data))
    return spectrum


def to_mel(hz: float, slaney: bool = False) -> float:
    a = 2595.0 if slaney else 1127.0
    return a * math.log(hz / 700.0 + 1.0)


def to_hz(mel: float, slaney: bool = False) -> float:
    a = 2595.0 if slaney else 1127.0
    return 700.0 * (math.exp(mel / a) - 1.0)


def mel_filter_bank(
    spectrum: np.ndarray, sample_rate: float, mel_div: int
) -> np.ndarray:
    mel_spectrum = np.zeros(mel_div, dtype=np.float64)
    f_max = sample_rate / 2.0
    mel_max = to_mel(f_max)
    n_max = len(spectrum) // 2
    df = f_max / n_max
    d_mel = mel_max / (mel_div + 1)

    for n in range(mel_div):
        mel_begin = d_mel * n
        mel_center = d_mel * (n + 1)
        mel_end = d_mel * (n + 2)
        f_begin = to_hz(mel_begin)
        f_center = to_hz(mel_center)
        f_end = to_hz(mel_end)
        i_begin = int(math.ceil(f_begin / df))
        i_center = int(round(f_center / df))
        i_end = int(math.floor(f_end / df))
        total = 0.0
        for i in range(i_begin + 1, i_end + 1):
            f = df * i
            if i < i_center:
                a = (f - f_begin) / (f_center - f_begin)
            else:
                a = (f_end - f) / (f_end - f_center)
            a /= (f_end - f_begin) * 0.5
            total += a * spectrum[i]
        mel_spectrum[n] = total
    return mel_spectrum


def power_to_db(data: np.ndarray) -> np.ndarray:
    out = data.copy()
    for i in range(len(out)):
        out[i] = 10.0 * math.log10(max(out[i], 1e-12))
    return out


def dct(spectrum: np.ndarray) -> np.ndarray:
    length = len(spectrum)
    cepstrum = np.zeros(length, dtype=np.float64)
    a = math.pi / length
    for i in range(length):
        total = 0.0
        for j in range(length):
            ang = (j + 0.5) * i * a
            total += spectrum[j] * math.cos(ang)
        cepstrum[i] = total
    return cepstrum


def calc_scores(
    mfcc: np.ndarray,
    phonemes: np.ndarray,
    means: np.ndarray,
    std_devs: np.ndarray,
    compare_method: CompareMethod,
) -> np.ndarray:
    n_phonemes = phonemes.shape[0]
    n_coeff = mfcc.shape[0]
    scores = np.zeros(n_phonemes, dtype=np.float64)

    for index in range(n_phonemes):
        phoneme = phonemes[index]
        if compare_method == "l1_norm":
            distance = 0.0
            for i in range(n_coeff):
                x = (mfcc[i] - means[i]) / std_devs[i]
                y = (phoneme[i] - means[i]) / std_devs[i]
                distance += abs(x - y)
            distance /= n_coeff
            scores[index] = 10.0 ** (-distance)
        elif compare_method == "l2_norm":
            distance = 0.0
            for i in range(n_coeff):
                x = (mfcc[i] - means[i]) / std_devs[i]
                y = (phoneme[i] - means[i]) / std_devs[i]
                distance += (x - y) ** 2
            distance = math.sqrt(distance / n_coeff)
            scores[index] = 10.0 ** (-distance)
        else:
            prod = 0.0
            mfcc_norm = 0.0
            phoneme_norm = 0.0
            for i in range(n_coeff):
                x = (mfcc[i] - means[i]) / std_devs[i]
                y = (phoneme[i] - means[i]) / std_devs[i]
                mfcc_norm += x * x
                phoneme_norm += y * y
                prod += x * y
            mfcc_norm = math.sqrt(mfcc_norm)
            phoneme_norm = math.sqrt(phoneme_norm)
            if mfcc_norm * phoneme_norm < 1e-12:
                similarity = 0.0
            else:
                similarity = max(prod / (mfcc_norm * phoneme_norm), 0.0)
            scores[index] = similarity ** 100

    total = float(np.sum(scores))
    if total > 0:
        scores /= total
    return scores


def analyze_chunk(
    input_samples: np.ndarray,
    start_index: int,
    output_sample_rate: int,
    target_sample_rate: int,
    mel_filter_bank_channels: int,
    mfcc_num: int,
    phonemes: np.ndarray,
    means: np.ndarray,
    std_devs: np.ndarray,
    compare_method: CompareMethod,
) -> tuple[np.ndarray, float, int]:
    volume = get_rms_volume(input_samples)
    buffer = copy_ring_buffer(input_samples, start_index)
    cutoff = target_sample_rate / 2
    range_hz = 500
    buffer = low_pass_filter(buffer, output_sample_rate, cutoff, range_hz)
    data = down_sample(buffer, output_sample_rate, target_sample_rate)
    data = pre_emphasis(data, 0.97)
    data = hamming_window(data)
    data = normalize(data, 1.0)
    spectrum = fft_spectrum(data)
    mel_spectrum = mel_filter_bank(
        spectrum, target_sample_rate, mel_filter_bank_channels
    )
    mel_spectrum = power_to_db(mel_spectrum)
    mel_cepstrum = dct(mel_spectrum)
    mfcc = np.array(
        [mel_cepstrum[i] for i in range(1, mfcc_num + 1)], dtype=np.float64
    )
    scores = calc_scores(mfcc, phonemes, means, std_devs, compare_method)
    main_index = int(np.argmax(scores))
    return scores, volume, main_index


def normalize_volume(raw_volume: float, min_volume: float, max_volume: float) -> float:
    if raw_volume <= 0.0:
        return 0.0
    norm = (math.log10(raw_volume) - min_volume) / max(max_volume - min_volume, 1e-4)
    return max(0.0, min(1.0, norm))
