"""Additive-layer core — pure Python, no Blender dependencies.

Born Clean per IronCore conventions: NO bpy import. The additive-layer
feature (§G) is mostly NLA manipulation, but the influence math, blend-mode
classification, and layer-description formatting are pure and live here.

Background (from SPIKE_SLOTTED_ACTIONS.md): additive animation in Blender
5.1 is done with NLA strips, NOT the layered-action API (one layer max per
action). COMBINE is the correct blend for rotations; ADD breaks quaternions.

Public API:
  clamp_influence(v)              -> float   (0..1)
  influence_percent(v)            -> int
  is_additive(blend_mode)         -> bool
  describe_layer(name, blend, influence, mute) -> str
  ALL_BLEND_MODES, ADDITIVE_BLEND_MODES
"""
from __future__ import annotations


INFLUENCE_MIN = 0.0
INFLUENCE_MAX = 1.0

# NLA strip blend modes (Blender 5.1, verified in the spike).
ALL_BLEND_MODES = ("REPLACE", "COMBINE", "ADD", "SUBTRACT", "MULTIPLY")

# Modes that layer additively on top of the base. COMBINE is the default for
# rotation-bearing layers (quaternion-aware); ADD is component-wise and only
# safe for location/scale-only layers.
ADDITIVE_BLEND_MODES = ("COMBINE", "ADD", "SUBTRACT", "MULTIPLY")

# The recommended default for a new additive layer.
DEFAULT_BLEND_MODE = "COMBINE"


def clamp_influence(v: float) -> float:
    """Clamp an influence value to the valid 0..1 range."""
    return max(INFLUENCE_MIN, min(INFLUENCE_MAX, v))


def influence_percent(v: float) -> int:
    """Influence as an integer percentage 0..100."""
    return int(round(clamp_influence(v) * 100))


def is_additive(blend_mode: str) -> bool:
    """True if the blend mode layers on top of the base (not a full replace)."""
    return blend_mode in ADDITIVE_BLEND_MODES


def describe_layer(name: str, blend: str, influence: float, mute: bool) -> str:
    """One-line human description of a layer for the panel / reports.

    e.g. "Recoil · Combine · 75%"  or  "Breathing · Combine · muted · 100%"
    """
    parts = [name, blend.title()]
    if mute:
        parts.append("muted")
    parts.append(f"{influence_percent(influence)}%")
    return " · ".join(parts)
