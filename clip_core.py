"""Clip-manager core — pure Python, no Blender dependencies.

Born Clean per IronCore conventions: NO bpy import. The clip manager is
mostly bpy data-block juggling (create/activate/duplicate/push actions),
but the naming logic — unique names, duplicate-suffix handling, list
ordering — is pure and lives here so it's headless-tested.

Public API:
  strip_dup_suffix(name)            -> str    ("Walk.001" -> "Walk")
  unique_name(base, existing)       -> str    (collision-free name)
  next_duplicate_name(name, exist)  -> str    (name for a duplicate)
  sort_clip_names(names)            -> list   (stable, case-insensitive)
"""
from __future__ import annotations


def strip_dup_suffix(name: str) -> str:
    """Remove Blender's ``.NNN`` duplicate suffix if present.

    'Walk.001' -> 'Walk'; 'Walk' -> 'Walk'; 'Run.beta' -> 'Run.beta'
    (only a 3-digit numeric suffix counts as a duplicate marker).
    """
    if len(name) >= 5 and name[-4] == '.' and name[-3:].isdigit():
        return name[:-4]
    return name


def unique_name(base: str, existing) -> str:
    """Return `base`, or `base.NNN` if it collides with an existing name.

    existing: any container supporting ``in``. Matches Blender's own
    ``.001`` / ``.002`` incrementing so manager-created names look native.
    """
    existing = set(existing)
    if base not in existing:
        return base
    i = 1
    while f"{base}.{i:03d}" in existing:
        i += 1
    return f"{base}.{i:03d}"


def next_duplicate_name(name: str, existing) -> str:
    """Pick a name for a duplicate of `name`, avoiding collisions.

    Strips an existing ``.NNN`` first so duplicating 'Walk.001' yields
    'Walk.002' (next free), not 'Walk.001.001'.
    """
    base = strip_dup_suffix(name)
    return unique_name(base, existing)


def sort_clip_names(names) -> list:
    """Case-insensitive, stable sort of clip names for the panel list."""
    return sorted(names, key=lambda n: (n.lower(), n))
