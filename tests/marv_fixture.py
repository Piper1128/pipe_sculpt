"""Synthetic Marv body for tests: one box per bone, arms down, millimetres.

Frame: +Z up, character faces -Y, left = +X (the same as Blender's, so the
axis conversion is the identity unless a test overrides 'up'/'forward').
Proportions are round numbers, not anatomy; Marv's own files replace this.
"""
from __future__ import annotations

# (name, parent, center, tail or None, half-width) in mm
_JOINTS = [
    ("Hips",          None,           (0, 0, 1000),   (0, 0, 1080),   140),
    ("Spine",         "Hips",         (0, 0, 1080),   None,           130),
    ("Chest",         "Spine",        (0, 0, 1280),   (0, 0, 1480),   150),
    ("Neck",          "Chest",        (0, 0, 1480),   None,            50),
    ("Head",          "Neck",         (0, 0, 1560),   (0, 0, 1750),    95),
    ("LeftShoulder",  "Chest",        (30, 0, 1430),  None,            40),
    ("LeftUpperArm",  "LeftShoulder", (180, 0, 1430), None,            45),
    ("LeftLowerArm",  "LeftUpperArm", (190, 0, 1130), None,            40),
    ("LeftHand",      "LeftLowerArm", (195, 0, 880),  (195, 0, 700),   35),
    ("RightShoulder", "Chest",        (-30, 0, 1430), None,            40),
    ("RightUpperArm", "RightShoulder", (-180, 0, 1430), None,          45),
    ("RightLowerArm", "RightUpperArm", (-190, 0, 1130), None,          40),
    ("RightHand",     "RightLowerArm", (-195, 0, 880), (-195, 0, 700), 35),
    ("LeftUpperLeg",  "Hips",         (90, 0, 950),   None,            70),
    ("LeftLowerLeg",  "LeftUpperLeg", (90, 0, 520),   None,            55),
    ("LeftFoot",      "LeftLowerLeg", (90, 0, 80),    None,            45),
    ("LeftToes",      "LeftFoot",     (90, -150, 20), (90, -200, 20),  40),
    ("RightUpperLeg", "Hips",         (-90, 0, 950),  None,            70),
    ("RightLowerLeg", "RightUpperLeg", (-90, 0, 520), None,            55),
    ("RightFoot",     "RightLowerLeg", (-90, 0, 80),  None,            45),
    ("RightToes",     "RightFoot",    (-90, -150, 20), (-90, -200, 20), 40),
]


def _parent_after_drop(parent, drop):
    """A dropped joint's children move up to its parent, so the tree stays valid."""
    parents = {n: p for n, p, *_ in _JOINTS}
    while parent in drop:
        parent = parents[parent]
    return parent


def joints_doc(drop: tuple[str, ...] = ()) -> dict:
    joints = []
    for name, parent, center, tail, _w in _JOINTS:
        if name in drop:
            continue
        parent = _parent_after_drop(parent, drop)
        j = {"name": name, "parent": parent, "center": list(center),
             "provenance": {"source": "tests/marv_fixture.py", "kind": "Assumed"}}
        if tail is not None:
            j["tail"] = list(tail)
        joints.append(j)
    return {"schema": "marv.joints/1", "unit": "mm", "up": "+Z", "forward": "-Y", "right": "-X",
            "rest_pose": "arms_down", "joints": joints}


def _tail_of(name):
    for n, _p, _c, tail, _w in _JOINTS:
        if n == name and tail is not None:
            return tail
    children = [c for c, p, *_ in _JOINTS if p == name]
    return next(c for n, _p, c, *_ in _JOINTS if n == children[0])


def obj_text(drop: tuple[str, ...] = ()) -> str:
    """One axis-aligned box per bone, spanning head..tail grown by the half-width."""
    lines = ["# synthetic Marv body, mm"]
    base = 1
    for name, _p, center, _t, w in _JOINTS:
        if name in drop:
            continue
        tail = _tail_of(name)
        lo = [min(center[i], tail[i]) - w for i in range(3)]
        hi = [max(center[i], tail[i]) + w for i in range(3)]
        lines.append(f"g {name}")
        for x in (lo[0], hi[0]):
            for y in (lo[1], hi[1]):
                for z in (lo[2], hi[2]):
                    lines.append(f"v {x} {y} {z}")
        # vertex k = 4*ix + 2*iy + iz; outward-facing quads
        for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            lines.append("f " + " ".join(str(base + k) for k in q))
        base += 8
    return "\n".join(lines) + "\n"
