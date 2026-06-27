"""PipeSculpt addon entry point.

Born Clean per IronCore conventions: imports are lazy so pure-Python
core modules (hair_core, etc.) can be unit-tested without pulling in
bpy via this file. Blender calls register() once when the addon is
enabled; that's when we trigger the bpy-dependent imports.
"""


def _modules():
    from . import preferences
    from . import pie_menus
    from . import rigging
    from . import starters
    from . import workflow_ops
    from . import bake_ops
    from . import export_ops
    from . import manual_retopo_ops
    from . import uv_ops
    from . import paint_ops
    from . import ref_ops
    from . import workflow_panel
    from . import keymap
    return [
        preferences, pie_menus, rigging, starters, workflow_ops,
        bake_ops, export_ops, manual_retopo_ops, uv_ops, paint_ops,
        ref_ops, workflow_panel, keymap,
    ]


def register():
    for m in _modules():
        m.register()


def unregister():
    for m in reversed(_modules()):
        m.unregister()
