"""Safe Blender class registration (Blender 5.x RestrictData aware)."""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty


def is_data_restricted() -> bool:
    """True while addon is being enabled (bpy.data.scenes unavailable)."""
    try:
        _ = bpy.data.scenes
        return False
    except (AttributeError, TypeError):
        return True


def unregister_classes(classes) -> None:
    for cls in reversed(classes):
        if not cls:
            continue
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


def register_classes(classes) -> None:
    unregister_classes(classes)
    for cls in classes:
        bpy.utils.register_class(cls)


def remove_scene_pointer(attr_name: str) -> None:
    if is_data_restricted():
        return
    if hasattr(bpy.types.Scene, attr_name):
        try:
            delattr(bpy.types.Scene, attr_name)
        except Exception:
            pass


_SCENE_POINTER_TIMERS: dict[str, object] = {}


def ensure_scene_pointer(attr_name: str, prop_type) -> bool:
    """Attach Scene PointerProperty when RNA is writable."""
    if is_data_restricted():
        return False
    if hasattr(bpy.types.Scene, attr_name):
        return True
    try:
        setattr(
            bpy.types.Scene,
            attr_name,
            PointerProperty(type=prop_type),
        )
        return True
    except (AttributeError, TypeError):
        return False


def _tag_ui_redraw() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def add_scene_pointer_deferred(attr_name: str, prop_type) -> None:
    """Assign Scene PointerProperty after RestrictData lifts."""

    def _apply():
        _SCENE_POINTER_TIMERS.pop(attr_name, None)
        if is_data_restricted():
            _SCENE_POINTER_TIMERS[attr_name] = bpy.app.timers.register(
                _apply, first_interval=0.2
            )
            return None
        ensure_scene_pointer(attr_name, prop_type)
        _tag_ui_redraw()
        return None

    if attr_name in _SCENE_POINTER_TIMERS:
        try:
            bpy.app.timers.unregister(_SCENE_POINTER_TIMERS[attr_name])
        except Exception:
            pass

    if ensure_scene_pointer(attr_name, prop_type):
        return

    _SCENE_POINTER_TIMERS[attr_name] = bpy.app.timers.register(
        _apply, first_interval=0.2
    )


def cancel_scene_pointer_timers() -> None:
    for key, timer in list(_SCENE_POINTER_TIMERS.items()):
        try:
            bpy.app.timers.unregister(timer)
        except Exception:
            pass
        _SCENE_POINTER_TIMERS.pop(key, None)
