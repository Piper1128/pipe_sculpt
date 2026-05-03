from . import preferences
from . import keymap

_modules = (preferences, keymap)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
