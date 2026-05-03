from . import preferences
from . import pie_menus
from . import keymap

_modules = (preferences, pie_menus, keymap)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
