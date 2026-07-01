"""Pose serialization core — pure Python, no Blender dependencies.

Turns a PoseSpec into a JSON-serialisable dict and back, so a user can save
their own hand-tuned poses to disk (one .json file per pose, like a Unity
ScriptableObject asset) and reload them into the Pose Library. bpy-free and
pytest-tested; pose_library_ops does the actual file I/O.

On-disk format (one file per pose):
  {
    "format": "pipe_sculpt_pose", "version": 1,
    "name": "MY_POSE", "label": "My Pose", "category": "User",
    "description": "...",
    "channels": { "hand_ik.L": [[lx,ly,lz],[qw,qx,qy,qz]], ... }
  }
"""
from __future__ import annotations

import re

try:  # addon (package) context
    from . import pose_library_core as plc
except ImportError:  # pytest standalone context
    import pose_library_core as plc


FORMAT = "pipe_sculpt_pose"
VERSION = 1
USER_CATEGORY = "User"


def slugify(name: str) -> str:
    """Filesystem-safe slug for a pose file name.

    Lowercases, keeps [a-z0-9_-], collapses runs of other chars to '_'.
    Empty / all-invalid names fall back to 'pose'.
    """
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s or "pose"


def normalise_pose_id(name: str) -> str:
    """Catalog id (used as the EnumProperty identifier) from a display name."""
    s = re.sub(r"[^A-Z0-9]+", "_", name.strip().upper()).strip("_")
    return s or "POSE"


def pose_to_dict(spec) -> dict:
    """Serialise a PoseSpec to a JSON-ready dict."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "name": spec.name,
        "label": spec.label,
        "category": spec.category,
        "description": spec.description,
        "channels": {
            bone: [list(loc), list(quat)]
            for bone, (loc, quat) in spec.channels.items()
        },
    }


def validate_dict(d: dict) -> list:
    """Return a list of problems with a loaded pose dict (empty = OK)."""
    issues = []
    if not isinstance(d, dict):
        return ["not a JSON object"]
    if d.get("format") != FORMAT:
        issues.append(f"wrong format tag {d.get('format')!r} (expected {FORMAT!r})")
    if not d.get("name"):
        issues.append("missing 'name'")
    chans = d.get("channels", {})
    if not isinstance(chans, dict):
        issues.append("'channels' is not an object")
        return issues
    for bone, val in chans.items():
        if (not isinstance(val, (list, tuple)) or len(val) != 2
                or len(val[0]) != 3 or len(val[1]) != 4):
            issues.append(f"channel '{bone}' malformed (want [[x,y,z],[w,x,y,z]])")
    return issues


def pose_from_dict(d: dict):
    """Build a PoseSpec from a loaded dict. Raises ValueError if invalid.

    Channels are coerced to the in-memory tuple form. IK-solved bones are
    dropped defensively (a hand-edited file must never fight the solver).
    """
    issues = validate_dict(d)
    if issues:
        raise ValueError("; ".join(issues))
    channels = {}
    for bone, (loc, quat) in d["channels"].items():
        if bone in plc.IK_SOLVED_BONES:
            continue
        channels[bone] = (tuple(float(v) for v in loc), tuple(float(v) for v in quat))
    return plc.PoseSpec(
        name=d["name"],
        label=d.get("label") or d["name"],
        category=d.get("category") or USER_CATEGORY,
        description=d.get("description", ""),
        channels=channels,
    )
