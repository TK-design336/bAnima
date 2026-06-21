"""Optional bundled third-party libraries (onnxruntime, …)."""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR_READY = False


def package_root() -> Path:
    return Path(__file__).resolve().parent


def vendor_dir() -> Path:
    return package_root() / "vendor"


def emotion_model_dir() -> Path:
    """Legacy SpeechBrain model cache (deprecated, kept for migration)."""
    import bpy

    config_dir = Path(bpy.utils.user_resource("CONFIG", path="blipsync"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "emotion_model"


def audeering_model_dir() -> Path:
    """User-writable audeering ONNX model cache."""
    import bpy

    config_dir = Path(bpy.utils.user_resource("CONFIG", path="blipsync"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "audeering_model"


def bundled_audeering_model_dir() -> Path:
    """Shipped model files from build (blipsync/data/audeering_model)."""
    return package_root() / "data" / "audeering_model"


def pip_packages_dir() -> Path:
    """User-writable pip --target install location (no admin required)."""
    import bpy

    config_dir = Path(bpy.utils.user_resource("CONFIG", path="blipsync"))
    target = config_dir / "pip_packages"
    target.mkdir(parents=True, exist_ok=True)
    return target


def setup_pip_packages_path() -> bool:
    """Prepend user pip_packages/ when onnxruntime was installed there."""
    target = pip_packages_dir()
    has_onnx = (target / "onnxruntime").is_dir() or any(target.glob("onnxruntime-*.dist-info"))
    if not has_onnx:
        return False
    path = str(target)
    if path not in sys.path:
        sys.path.insert(0, path)
    return True


def setup_vendor_path() -> bool:
    """Prepend addon vendor/ to sys.path when a bundle is present."""
    global _VENDOR_READY
    if _VENDOR_READY:
        return True

    vdir = vendor_dir()
    if not vdir.is_dir():
        return False

    has_onnxruntime = (vdir / "onnxruntime").is_dir() or any(vdir.glob("onnxruntime-*.dist-info"))
    if not has_onnxruntime:
        return False

    path = str(vdir)
    if path not in sys.path:
        sys.path.insert(0, path)
    _VENDOR_READY = True
    return True


def is_vendor_bundled() -> bool:
    return setup_vendor_path()
