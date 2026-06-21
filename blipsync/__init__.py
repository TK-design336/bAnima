bl_info = {
    "name": "BlipSync",
    "author": "BlipSync",
    "version": (0, 6, 24),
    "blender": (3, 6, 0),
    "location": "View3D / Video Sequencer > Sidebar (N) > BlipSync",
    "description": "uLipSync-based lip sync for Blender VSE (realtime & bake)",
    "category": "Animation",
}

import sys

from . import handlers, operators, properties, ui


def register():
    # Blender 5.x: register 中は bpy.data / Scene プロパティ削除が禁止。
    # クラスの再登録は各 module.register() 内で行う。
    from .deps_installer import reset_install_state
    from .emotion_engine import reset_classifier_state

    for name in list(sys.modules):
        if name == "speechbrain" or name.startswith("speechbrain."):
            del sys.modules[name]
    reset_classifier_state()
    reset_install_state()
    properties.register()
    operators.register()
    ui.register()
    handlers.register_handlers()


def unregister():
    handlers.unregister_handlers()
    ui.unregister()
    operators.unregister()
    properties.unregister()


if __name__ == "__main__":
    register()
