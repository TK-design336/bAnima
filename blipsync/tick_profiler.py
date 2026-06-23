"""Per-tick timing breakdown (diagnose viewport / render stalls)."""

from __future__ import annotations

import time
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import bpy


class TickProfiler:
    def __init__(self) -> None:
        self.sections: Dict[str, float] = {}

    @contextmanager
    def section(self, name: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.sections[name] = self.sections.get(name, 0.0) + (time.perf_counter() - t0)

    def total_sec(self) -> float:
        return sum(self.sections.values())

    def format_report(self, *, frame: int, context: str = "") -> str:
        lines = [f"=== blipsync {context} frame {frame} ==="]
        for name, sec in sorted(self.sections.items(), key=lambda item: -item[1]):
            lines.append(f"  {name}: {sec * 1000.0:.2f} ms")
        lines.append(f"  TOTAL: {self.total_sec() * 1000.0:.2f} ms")
        return "\n".join(lines)


def profiler_section(profiler: Optional[TickProfiler], name: str):
    if profiler is None:
        return nullcontext()
    return profiler.section(name)


def default_profile_log_path(scene: "bpy.types.Scene") -> Path:
    import bpy

    blend = getattr(bpy.data, "filepath", "") or ""
    if blend:
        base = Path(blend).parent
    else:
        base = Path.home() / "blipsync_profiles"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scene_name = getattr(scene, "name", "Scene") or "Scene"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in scene_name)
    return base / f"blipsync_profile_{safe}_{stamp}.txt"


def append_profile_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n\n")
