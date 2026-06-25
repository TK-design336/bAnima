"""Direct DNA writes for shape keys (bypass RNA notifiers during render)."""

from __future__ import annotations

import ctypes
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import bpy.types as _bpy_types

# KeyBlock.curval offset on 64-bit (two listbase pointers). Stable across 3.6–5.x.
_KEYBLOCK_CURVAL_OFFSET = 16

_touched_shape_keys: list = []
_dna_write_available: Optional[bool] = None


def _probe_dna_write(kb) -> bool:
    global _dna_write_available
    if _dna_write_available is not None:
        return _dna_write_available
    try:
        ptr = int(kb.as_pointer())
        if ptr <= 0:
            _dna_write_available = False
            return False
        addr = ptr + _KEYBLOCK_CURVAL_OFFSET
        ref = ctypes.c_float.from_address(addr)
        original = float(ref.value)
        ref.value = original
        _dna_write_available = True
        return True
    except Exception:
        _dna_write_available = False
        return False


def dna_read_shape_key_value(kb) -> Optional[float]:
    try:
        ptr = int(kb.as_pointer())
        if ptr <= 0:
            return None
        return float(ctypes.c_float.from_address(ptr + _KEYBLOCK_CURVAL_OFFSET).value)
    except Exception:
        return None


def dna_write_shape_key_value(kb, value: float) -> bool:
    if not _probe_dna_write(kb):
        return False
    try:
        ptr = int(kb.as_pointer())
        if ptr <= 0:
            return False
        ctypes.c_float.from_address(ptr + _KEYBLOCK_CURVAL_OFFSET).value = float(value)
        if kb not in _touched_shape_keys:
            _touched_shape_keys.append(kb)
        return True
    except Exception:
        global _dna_write_available
        _dna_write_available = False
        return False


def tag_shape_key_mesh_update(mesh) -> None:
    if mesh is None:
        return
    try:
        owner = mesh.id_data if hasattr(mesh, "id_data") else mesh
        owner.update_tag(refresh={"DATA"})
    except Exception:
        pass


def flush_touched_shape_keys_to_rna() -> None:
    """Sync DNA curval back to RNA once after render (viewport restore)."""
    for kb in list(_touched_shape_keys):
        dna_val = dna_read_shape_key_value(kb)
        if dna_val is not None:
            try:
                kb.value = dna_val
            except Exception:
                pass
    _touched_shape_keys.clear()


def clear_touched_shape_keys() -> None:
    _touched_shape_keys.clear()
