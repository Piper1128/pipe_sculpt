import bpy

_addon_keymaps: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


def register():
    pass


def unregister():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is not None:
        for km, kmi in _addon_keymaps:
            try:
                km.keymap_items.remove(kmi)
            except RuntimeError:
                pass
    _addon_keymaps.clear()
