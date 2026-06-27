"""Project setup wizard — pure Python validation + folder layout.

Born Clean: no bpy. The bpy adapter in project_ops.py calls these
helpers to validate user input and decide what folders to create.
"""
from __future__ import annotations

import os
import re


# Sub-folders created under <project_root>/<project_name>/.
# Order matters: this is also the order they appear in the report.
PROJECT_SUBFOLDERS = (
    "sculpt",       # high-poly sculpt .blend files
    "low",          # retopo'd low-poly .blend files
    "textures",     # baked/painted PNGs (bake_ops + paint_ops write here)
    "exports",      # .fbx files for Unity
    "references",   # source image references
)


# Reserved Windows filenames (case-insensitive) — Blender would happily
# create a folder called CON, but Windows can't open it from Explorer.
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\- ]{0,63}$")


def validate_project_name(name: str) -> str | None:
    """Return an error message string, or None if `name` is acceptable.

    Rules:
      - 1-64 characters
      - starts with letter or digit
      - only letters, digits, underscore, hyphen, space afterwards
      - not a Windows reserved name (CON, PRN, etc.)
    """
    if not name or not name.strip():
        return "Project name is empty"
    name = name.strip()
    if len(name) > 64:
        return f"Project name too long ({len(name)} chars; max 64)"
    if not _PROJECT_NAME_RE.match(name):
        return (
            f"'{name}' contains illegal characters. Use letters, digits, "
            "underscore, hyphen, or space only; must start with a letter or digit"
        )
    if name.upper() in _WINDOWS_RESERVED:
        return f"'{name}' is a Windows reserved name (CON, PRN, etc.)"
    return None


def project_paths(parent_dir: str, project_name: str) -> dict:
    """Build the planned project filesystem layout.

    Returns:
      {
          'root':       <parent>/<name>,
          'subfolders': {name: <parent>/<name>/<sub> for sub in PROJECT_SUBFOLDERS},
          'blend_file': <parent>/<name>/<name>.blend,
      }
    """
    root = os.path.join(parent_dir, project_name)
    return {
        'root': root,
        'subfolders': {sub: os.path.join(root, sub) for sub in PROJECT_SUBFOLDERS},
        'blend_file': os.path.join(root, f"{project_name}.blend"),
    }


def is_directory_writeable(path: str) -> bool:
    """Cheap pre-flight check: does the parent dir exist and look writeable.

    Doesn't actually try to write — that's the caller's job. We just rule
    out the obvious 'parent doesn't exist' case so the bpy adapter can
    fail early with a clear message.
    """
    if not path:
        return False
    return os.path.isdir(path) and os.access(path, os.W_OK)


def project_summary(parent_dir: str, project_name: str) -> str:
    """Human-readable summary of what `setup_project` will create.

    Used in the wizard dialog so the user sees exactly what's about to
    happen before they click OK.
    """
    paths = project_paths(parent_dir, project_name)
    lines = [f"Project: {paths['root']}"]
    for sub in PROJECT_SUBFOLDERS:
        lines.append(f"  └─ {sub}/")
    lines.append(f"  └─ {project_name}.blend (saved here on creation)")
    return "\n".join(lines)
