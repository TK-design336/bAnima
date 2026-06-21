"""audeering wav2vec2 emotion model via onnxruntime (Zenodo ONNX export)."""

from __future__ import annotations

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .vendor import audeering_model_dir, bundled_audeering_model_dir, setup_vendor_path

ZENODO_URL = "https://zenodo.org/record/6221127/files/w2v2-L-robust-12.6bc4a7fd-1.1.0.zip"
MODEL_MARKER = "model.onnx"
EMOTION_TARGET_RATE = 16000

_SESSION = None
_SESSION_ERROR: Optional[str] = None
_SESSION_CHECKED = False
_INPUT_NAME: Optional[str] = None
_OUTPUT_NAME: Optional[str] = None
_DOWNLOAD_PROGRESS = ""


def get_download_progress() -> str:
    return _DOWNLOAD_PROGRESS


def get_session_error() -> Optional[str]:
    return _SESSION_ERROR


def is_session_available() -> bool:
    if not _SESSION_CHECKED:
        _load_session()
    return _SESSION is not None


def clear_session_cache() -> None:
    reset_session_state()


def reset_session_state() -> None:
    global _SESSION, _SESSION_ERROR, _SESSION_CHECKED, _INPUT_NAME, _OUTPUT_NAME, _DOWNLOAD_PROGRESS
    _SESSION = None
    _SESSION_ERROR = None
    _SESSION_CHECKED = False
    _INPUT_NAME = None
    _OUTPUT_NAME = None
    _DOWNLOAD_PROGRESS = ""


def _copy_bundled_model(dest_dir: Path) -> bool:
    bundled = bundled_audeering_model_dir()
    marker = bundled / MODEL_MARKER
    if not marker.is_file():
        return False
    dest_dir.mkdir(parents=True, exist_ok=True)
    for path in bundled.iterdir():
        if path.is_file():
            shutil.copy2(path, dest_dir / path.name)
    return (dest_dir / MODEL_MARKER).is_file()


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest_dir)

    marker = dest_dir / MODEL_MARKER
    if marker.is_file():
        return

    for candidate in dest_dir.rglob(MODEL_MARKER):
        if candidate.parent == dest_dir:
            return
        nested_root = candidate.parent
        for path in nested_root.iterdir():
            target = dest_dir / path.name
            if path.is_file():
                shutil.move(str(path), str(target))
            elif path.is_dir() and not target.exists():
                shutil.move(str(path), str(target))
        return

    raise FileNotFoundError(f"{MODEL_MARKER} not found after extracting {archive_path}")


def _download_progress_hook(block_num: int, block_size: int, total_size: int) -> None:
    global _DOWNLOAD_PROGRESS
    if total_size <= 0:
        _DOWNLOAD_PROGRESS = "Downloading emotion model..."
        return
    downloaded = min(block_num * block_size, total_size)
    pct = downloaded * 100.0 / total_size
    mb_done = downloaded / (1024 * 1024)
    mb_total = total_size / (1024 * 1024)
    _DOWNLOAD_PROGRESS = f"Downloading emotion model... {pct:.1f}% ({mb_done:.0f}/{mb_total:.0f} MB)"


def ensure_model_files(model_dir: Optional[Path] = None) -> Path:
    """Download and extract the audeering ONNX model if missing."""
    global _DOWNLOAD_PROGRESS

    target = model_dir or audeering_model_dir()
    marker = target / MODEL_MARKER
    if marker.is_file():
        _DOWNLOAD_PROGRESS = ""
        return target

    if _copy_bundled_model(target):
        _DOWNLOAD_PROGRESS = ""
        return target

    target.mkdir(parents=True, exist_ok=True)
    _DOWNLOAD_PROGRESS = "Downloading emotion model..."
    print(f"[blipsync] Downloading audeering emotion model from Zenodo to {target}")

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "audeering_emotion.zip"
        urllib.request.urlretrieve(ZENODO_URL, archive_path, reporthook=_download_progress_hook)
        _extract_zip(archive_path, target)

    if not marker.is_file():
        raise FileNotFoundError(f"Model marker missing: {marker}")

    _DOWNLOAD_PROGRESS = ""
    return target


def _resolve_io_names(session) -> Tuple[str, str]:
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if not inputs or not outputs:
        raise RuntimeError("ONNX model has no inputs or outputs")

    input_name = inputs[0].name
    output_name = None
    for out in outputs:
        if out.name == "logits":
            output_name = out.name
            break
    if output_name is None:
        output_name = outputs[0].name

    print(f"[blipsync] emotion ONNX input={input_name!r}, outputs={[o.name for o in outputs]}")
    return input_name, output_name


def _load_session():
    global _SESSION, _SESSION_ERROR, _SESSION_CHECKED, _INPUT_NAME, _OUTPUT_NAME

    _SESSION_CHECKED = True
    if _SESSION is not None:
        return _SESSION
    if _SESSION_ERROR is not None:
        return None

    try:
        from .deps_installer import try_import_onnxruntime

        ok, detail = try_import_onnxruntime(refresh=True)
        if not ok:
            _SESSION_ERROR = detail
            return None

        setup_vendor_path()
        import onnxruntime as rt

        model_dir = ensure_model_files()
        onnx_path = model_dir / MODEL_MARKER
        _SESSION = rt.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        _INPUT_NAME, _OUTPUT_NAME = _resolve_io_names(_SESSION)
        _SESSION_ERROR = None
        return _SESSION
    except Exception as exc:
        _SESSION_ERROR = str(exc)
        return None


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    count = max(1, int(samples.size * dst_rate / src_rate))
    indices = np.linspace(0, samples.size - 1, count)
    return np.interp(indices, np.arange(samples.size), samples).astype(np.float32)


def remap_axis(value: float, pivot: float) -> float:
    """Map [0, pivot] -> [0, 0.5], [pivot, 1] -> [0.5, 1]."""
    x = max(0.0, min(1.0, float(value)))
    p = max(0.01, min(0.99, float(pivot)))
    if x <= p:
        return 0.5 * (x / p)
    return 0.5 + 0.5 * ((x - p) / (1.0 - p))


def remap_valence(valence: float, pivot: float) -> float:
    return remap_axis(valence, pivot)


def remap_arousal(arousal: float, pivot: float) -> float:
    return remap_axis(arousal, pivot)


def map_to_emotion_class(
    valence: float,
    arousal: float,
    valence_pivot: float = 0.5,
    arousal_pivot: float = 0.5,
) -> str:
    """Dominant label from continuous VAD scores."""
    _dominant, _confidence, happy, sad, angry, neutral = vad_to_emotion_scores(
        valence,
        arousal,
        valence_pivot=valence_pivot,
        arousal_pivot=arousal_pivot,
    )
    return max(
        (("happy", happy), ("sad", sad), ("angry", angry), ("neutral", neutral)),
        key=lambda item: item[1],
    )[0]


def vad_to_emotion_scores(
    valence: float,
    arousal: float,
    *,
    valence_pivot: float = 0.5,
    arousal_pivot: float = 0.5,
) -> Tuple[str, float, float, float, float, float]:
    """Map valence/arousal (0..1) to happy/sad/angry/neutral summing to 1.

    valence/arousal are remapped via pivot before quadrant mapping.
    pivot < 0.5 shifts the axis upward; pivot > 0.5 shifts downward; 0.5 = no remap.
    """
    v = remap_valence(valence, valence_pivot)
    a = remap_arousal(arousal, arousal_pivot)
    happy = sad = angry = 0.0

    if v >= 0.5:
        arousal_factor = 0.25 + 0.75 * max(a - 0.5, 0.0)
        happy = 4.0 * (v - 0.5) * arousal_factor
    else:
        dist = (2.0 * ((a - 0.5) ** 2 + (v - 0.5) ** 2)) ** 0.5
        if a >= 0.5:
            angry = dist
        else:
            # Both valence and arousal absolutely low → lean neutral (not full sad at origin).
            low_factor = min(1.0, 4.0 * v * a)
            sad = dist * low_factor

    happy = max(0.0, happy)
    sad = max(0.0, sad)
    angry = max(0.0, angry)

    total = happy + sad + angry
    if total > 1.0:
        scale = 1.0 / total
        happy *= scale
        sad *= scale
        angry *= scale

    neutral = max(0.0, 1.0 - (happy + sad + angry))
    scores = {"happy": happy, "sad": sad, "angry": angry, "neutral": neutral}
    dominant = max(scores, key=scores.get)
    confidence = scores[dominant]
    return dominant, confidence, happy, sad, angry, neutral


def predict_vad(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    session = _load_session()
    if session is None:
        raise RuntimeError(_SESSION_ERROR or "onnxruntime session unavailable")

    wav = _resample(audio, sample_rate, EMOTION_TARGET_RATE)
    if wav.ndim != 1:
        wav = wav.reshape(-1)

    assert _INPUT_NAME is not None
    assert _OUTPUT_NAME is not None

    inputs = {_INPUT_NAME: wav[np.newaxis, :].astype(np.float32)}
    outputs = session.run([_OUTPUT_NAME], inputs)
    logits = outputs[0][0]
    if logits.size < 3:
        raise RuntimeError(f"Unexpected logits shape: {outputs[0].shape}")

    arousal, dominance, valence = (float(logits[0]), float(logits[1]), float(logits[2]))
    return {
        "valence": valence,
        "arousal": arousal,
        "dominance": dominance,
    }
