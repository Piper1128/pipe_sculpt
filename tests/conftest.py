"""pytest config — block pytest from importing pipe_sculpt's __init__.py.

The addon's __init__.py imports bpy (and every operator module), so pytest
collecting it triggers a ModuleNotFoundError outside Blender. We work
around it by importing core modules directly via importlib's file loader,
bypassing the package machinery entirely.
"""
from __future__ import annotations

import importlib.util
import os
import sys


_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module_by_path(name: str, rel_path: str):
    """Load a single .py file as a top-level module, skipping any package init."""
    full_path = os.path.join(_ADDON_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(name, full_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Pre-load the pure-Python core modules so test files can `import hair_core`
# without triggering pipe_sculpt/__init__.py (which imports bpy).
_load_module_by_path('hair_core', 'hair_core.py')
_load_module_by_path('validator_core', 'validator_core.py')
_load_module_by_path('project_core', 'project_core.py')
_load_module_by_path('palette_core', 'palette_core.py')
