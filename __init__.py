from . import preferences
from . import pie_menus
from . import workflow_ops
from . import workflow_panel
from . import keymap

_modules = (preferences, pie_menus, workflow_ops, workflow_panel, keymap)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
