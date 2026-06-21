"""bAnima parent addon — stacks feature panels (Lip & Emotion Sync, …)."""

bl_info = {
    "name": "bAnima",
    "author": "bAnima",
    "version": (0, 2, 51),
    "blender": (3, 6, 0),
    "location": "View3D / Video Sequencer > Sidebar (N) > bAnima",
    "description": "Animation toolkit: Lip & Emotion Sync and more",
    "category": "Animation",
}

import sys
from pathlib import Path

_addon_root = Path(__file__).resolve().parent


def _load_blipsync():
    embedded = _addon_root / "blipsync"
    if embedded.is_dir() and (embedded / "__init__.py").is_file():
        from . import blipsync as pkg

        return pkg

    repo_root = _addon_root.parent
    sibling = repo_root / "blipsync"
    if sibling.is_dir() and (sibling / "__init__.py").is_file():
        repo_str = str(repo_root)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)
        import blipsync as pkg

        return pkg

    raise ImportError(
        "bAnima: blipsync package not found. Reinstall bAnima from a build that "
        "includes banima/blipsync/, or place the blipsync folder next to banima/."
    )


_blipsync_pkg = _load_blipsync()

handlers = _blipsync_pkg.handlers
operators = _blipsync_pkg.operators
properties = _blipsync_pkg.properties

from . import ui


def _blipsync_ui():
    return _blipsync_pkg.ui


def _cleanup_blipsync_sidebar() -> None:
    """Drop legacy BlipSync tab panels; bAnima owns the UI."""
    _blipsync_ui().cleanup_blipsync_panels()


def _register_blipsync_lists() -> None:
    _blipsync_ui().register_lists()


def _unregister_blipsync_lists() -> None:
    _blipsync_ui().unregister_lists()


def _reset_emotion_stack() -> None:
    for name in list(sys.modules):
        if name == "speechbrain" or name.startswith("speechbrain."):
            del sys.modules[name]
    reset_classifier_state = _blipsync_pkg.emotion_engine.reset_classifier_state
    reset_classifier_state()
    reset_install_state = _blipsync_pkg.deps_installer.reset_install_state
    reset_install_state()


def register():
    _reset_emotion_stack()
    properties.register()
    operators.register()
    _register_blipsync_lists()
    _cleanup_blipsync_sidebar()
    ui.register()
    handlers.register_handlers()
    _cleanup_blipsync_sidebar()


def unregister():
    handlers.unregister_handlers()
    ui.unregister()
    _unregister_blipsync_lists()
    operators.unregister()
    properties.unregister()
    _cleanup_blipsync_sidebar()


if __name__ == "__main__":
    register()
