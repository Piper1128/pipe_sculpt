import bpy

_addon_keymaps: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


def _add(km, idname, key, *, shift=False, ctrl=False, alt=False, properties=None):
    kmi = km.keymap_items.new(idname, type=key, value='PRESS', shift=shift, ctrl=ctrl, alt=alt)
    if properties:
        for k, v in properties.items():
            setattr(kmi.properties, k, v)
    _addon_keymaps.append((km, kmi))
    return kmi


def register():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc is None:
        return

    km = kc.keymaps.new(name="Sculpt", space_type='EMPTY')

    _add(km, "wm.call_menu_pie", 'Q',
         properties={"name": "SCULPTKIT_MT_pie_primary"})
    _add(km, "wm.call_menu_pie", 'Q', shift=True,
         properties={"name": "SCULPTKIT_MT_pie_secondary"})


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
