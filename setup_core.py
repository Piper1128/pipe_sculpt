"""Rig-styling core — pure Python, no Blender dependencies.

Born Clean: NO bpy. Decides which bones are grabbable controls, what widget
shape + size + colour each gets, and which bone collection it belongs to.
The bpy adapter in setup_ops.py builds the widget meshes and applies these.

Goal: make the IK controls (hand_ik / foot_ik / poles / root) visible and
obviously draggable instead of tiny octahedra hidden inside the mesh.

Public API:
  widget_for_control(name)  -> (shape, base_scale) | None
  is_control(name)          -> bool
  is_finger(name)           -> bool
  theme_for_bone(name)      -> 'THEME04' / 'THEME01' / 'THEME09' / 'DEFAULT'
  collection_for_bone(name) -> 'Controls' / 'Fingers' / 'Deform'
  widget_scale(name, mult)  -> float | None
"""
from __future__ import annotations


_FINGER_PREFIXES = ("thumb", "index", "middle", "ring", "pinky")

# Control-bone base name → (widget shape id, base scale). Widget meshes are
# unit-sized (~1 unit across); scale is applied via custom_shape_scale_xyz.
CONTROL_WIDGETS = {
    'hand_ik':    ('CUBE', 0.12),
    'foot_ik':    ('CUBE', 0.12),
    'elbow_pole': ('DIAMOND', 0.06),
    'knee_pole':  ('DIAMOND', 0.06),
    'root':       ('RING', 0.5),
}


def _strip_side(name: str):
    """Return (base, side) where side is 'L'/'R'/None."""
    for suf, side in (('.L', 'L'), ('.R', 'R'), ('_L', 'L'), ('_R', 'R')):
        if name.endswith(suf):
            return name[: -len(suf)], side
    return name, None


def widget_for_control(name: str):
    """(shape, base_scale) for a control bone, or None if it's not a styled control."""
    base, _ = _strip_side(name)
    return CONTROL_WIDGETS.get(base)


def is_control(name: str) -> bool:
    return widget_for_control(name) is not None


def is_finger(name: str) -> bool:
    base, _ = _strip_side(name)
    return any(base.startswith(p) for p in _FINGER_PREFIXES)


def theme_for_bone(name: str) -> str:
    """Bone colour theme. Left controls blue, right red, centre yellow; deform default.

    Standard rigging convention (left=blue, right=red) so the animator can
    tell sides apart at a glance. Deform bones stay neutral.
    """
    if not is_control(name):
        return 'DEFAULT'
    _, side = _strip_side(name)
    if side == 'L':
        return 'THEME04'  # blue
    if side == 'R':
        return 'THEME01'  # red
    return 'THEME09'      # centre control (root) — yellow


def collection_for_bone(name: str) -> str:
    if is_control(name):
        return 'Controls'
    if is_finger(name):
        return 'Fingers'
    return 'Deform'


def widget_scale(name: str, multiplier: float = 1.0):
    """Absolute widget scale for a control bone, or None if not a control."""
    w = widget_for_control(name)
    if w is None:
        return None
    return w[1] * max(0.01, multiplier)
