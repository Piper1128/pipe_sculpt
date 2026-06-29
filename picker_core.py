"""Bone-picker layout — pure Python, no Blender dependencies.

Born Clean per IronCore conventions: NO bpy import. Takes a list of bone
names (read from the live armature by picker_ops) and classifies each into
a group + column + row so the panel can draw a body-shaped clickable grid
without any per-rig manual setup.

Works for any of PipeSculpt's rigs (humanoid / quadruped / bird / mech)
and degrades gracefully on unknown bones (→ 'other' group).

Public API:
  classify_bone(name)        -> BoneSlot
  build_picker_layout(names) -> list[BoneSlot]
  body_columns(slots)        -> {'L': [...], 'C': [...], 'R': [...]} ordered by row
  finger_slots(slots)        -> list[BoneSlot]  (sided fingers, for a separate grid)
  control_slots(slots)       -> list[BoneSlot]  (IK targets / poles)
"""
from __future__ import annotations

from dataclasses import dataclass


# Column: 'L' left, 'R' right, 'C' centerline.
def _column_of(name: str) -> str:
    for suf in (".L", "_L", ".l", "_l"):
        if name.endswith(suf):
            return 'L'
    for suf in (".R", "_R", ".r", "_r"):
        if name.endswith(suf):
            return 'R'
    return 'C'


def _strip_suffix(name: str) -> str:
    for suf in (".L", ".R", "_L", "_R", ".l", ".r", "_l", "_r"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


# Short display labels for the picker buttons (suffix already stripped).
_LABELS = {
    "upper_arm": "U.Arm", "forearm": "F.Arm", "clavicle": "Clav",
    "upper_leg": "U.Leg", "lower_leg": "L.Leg",
    "hand_ik": "HandIK", "foot_ik": "FootIK",
    "elbow_pole": "Elbow", "knee_pole": "Knee",
    "foreleg_upper": "FU.Leg", "foreleg_lower": "FL.Leg", "forepaw": "F.Paw",
    "hindleg_upper": "HU.Leg", "hindleg_lower": "HL.Leg", "hindpaw": "H.Paw",
    "wing_upper": "U.Wing", "wing_lower": "L.Wing", "wingtip": "W.Tip",
    "bird_leg_upper": "U.Leg", "bird_leg_lower": "L.Leg",
}


def _label_for(base: str) -> str:
    if base in _LABELS:
        return _LABELS[base]
    # Title-case the leftover (e.g. "spine" -> "Spine", "upper_arm" handled above)
    return base.replace("_", " ").title()


# Classification table: (predicate over the suffix-stripped base, group, row).
# row: lower = higher on the body (head 0 → feet 9). First match wins, so
# order specific entries before general ones.
_FINGER_PREFIXES = ("thumb", "index", "middle", "ring", "pinky")


def _classify_base(base: str):
    """Return (group, row) for a suffix-stripped bone base name."""
    # Fingers first (they'd otherwise fall through to 'other')
    if any(base.startswith(fp) for fp in _FINGER_PREFIXES):
        return ('fingers', 6)

    table = (
        ("root",          'control', 10),
        ("pelvis",        'torso',   5),
        ("spine",         'torso',   4),
        ("chest",         'torso',   3),
        ("neck",          'head',    1),
        ("head",          'head',    0),
        ("jaw",           'head',    1),
        ("ear",           'head',    0),
        ("beak",          'head',    0),
        ("clavicle",      'arm',     2),
        ("upper_arm",     'arm',     3),
        ("forearm",       'arm',     4),
        ("hand_ik",       'control', 5),
        ("hand",          'hand',    5),
        ("elbow_pole",    'control', 4),
        ("upper_leg",     'leg',     6),
        ("lower_leg",     'leg',     7),
        ("foot_ik",       'control', 8),
        ("foot",          'leg',     8),
        ("toes",          'leg',     9),
        ("knee_pole",     'control', 7),
        ("tail",          'torso',   6),
        ("wing_upper",    'arm',     2),
        ("wing_lower",    'arm',     3),
        ("wingtip",       'arm',     4),
        ("foreleg_upper", 'leg',     3),
        ("foreleg_lower", 'leg',     4),
        ("forepaw",       'leg',     5),
        ("hindleg_upper", 'leg',     6),
        ("hindleg_lower", 'leg',     7),
        ("hindpaw",       'leg',     8),
        ("bird_leg_upper", 'leg',    6),
        ("bird_leg_lower", 'leg',    7),
    )
    for prefix, group, row in table:
        if base == prefix or base.startswith(prefix):
            return (group, row)
    return ('other', 5)


@dataclass(frozen=True)
class BoneSlot:
    bone: str       # full bone name (for selection)
    label: str      # short display label
    column: str     # 'L' / 'C' / 'R'
    group: str      # 'head' / 'torso' / 'arm' / 'hand' / 'fingers' / 'leg' / 'control' / 'other'
    row: int        # vertical ordering, lower = higher on the body


def classify_bone(name: str) -> BoneSlot:
    base = _strip_suffix(name)
    group, row = _classify_base(base)
    return BoneSlot(
        bone=name,
        label=_label_for(base),
        column=_column_of(name),
        group=group,
        row=row,
    )


def build_picker_layout(names) -> list[BoneSlot]:
    """Classify every bone name into a BoneSlot."""
    return [classify_bone(n) for n in names]


# Groups that make up the main body grid (fingers + controls drawn separately)
_BODY_GROUPS = frozenset({'head', 'torso', 'arm', 'hand', 'leg', 'other'})


def body_columns(slots):
    """Bucket the body slots into L/C/R columns, each sorted top→bottom.

    Returns {'L': [...], 'C': [...], 'R': [...]}. Within a column, slots are
    sorted by row then label so the layout reads like a body silhouette.
    """
    cols = {'L': [], 'C': [], 'R': []}
    for s in slots:
        if s.group in _BODY_GROUPS:
            cols[s.column].append(s)
    for c in cols.values():
        c.sort(key=lambda s: (s.row, s.label))
    return cols


def finger_slots(slots):
    """The finger bones, sorted by side then label (for a separate grid)."""
    fingers = [s for s in slots if s.group == 'fingers']
    fingers.sort(key=lambda s: (s.column, s.label))
    return fingers


def control_slots(slots):
    """IK target / pole control bones, sorted by side then row."""
    ctrls = [s for s in slots if s.group == 'control']
    ctrls.sort(key=lambda s: (s.column, s.row, s.label))
    return ctrls
