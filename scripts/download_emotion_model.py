"""Download audeering emotion ONNX model into addon data/ (run at build time)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLIPSYNC = ROOT / "blipsync"
MODEL_DIR = BLIPSYNC / "data" / "audeering_model"

if str(BLIPSYNC) not in sys.path:
    sys.path.insert(0, str(BLIPSYNC))

from emotion_onnx import ensure_model_files  # noqa: E402

MODEL_DIR.mkdir(parents=True, exist_ok=True)

print(f"Downloading audeering emotion model to: {MODEL_DIR}")
ensure_model_files(MODEL_DIR)
print("Done.")
