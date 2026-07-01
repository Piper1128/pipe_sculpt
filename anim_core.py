"""Animation core — pure Python logic, no Blender dependencies.

Born Clean per IronCore conventions: NO bpy import. Everything here is
plain-data in, plain-data out, so it unit-tests headlessly with pytest.
The bpy adapter in anim_ops.py reads pose-bone transforms / keyframes
out of Blender, calls these functions, and writes the results back.

Public API (Phase 1):
  Mirror:
    mirror_bone_name(name)        -> str | None  (.L↔.R, None for centerline)
    is_centerline(name)           -> bool
  Breakdown / tween:
    lerp(a, b, t)                 -> float
    breakdown_vec(a, b, t)        -> tuple
    breakdown_quat(a, b, t)       -> tuple  (nlerp, shortest-arc)
  Loop validation:
    transforms_differ(a, b, eps)  -> bool
    diff_pose(pose_a, pose_b, eps)-> list[BoneDiff]
  In-place / root motion:
    strip_root_translation(keys, keep_z) -> list
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ======================================================================
# Mirror mapping
# ======================================================================

# Suffix pairs tried in order. GTR uses ".L"/".R"; the others are accepted
# so the pose tools also work on imported rigs using Blender's other common
# left/right conventions.
_MIRROR_SUFFIX_PAIRS = (
    (".L", ".R"),
    ("_L", "_R"),
    (".l", ".r"),
    ("_l", "_r"),
)

# GTR centerline bones — they sit on the X=0 plane and have no mirror twin.
# Used for validation (a centerline bone returning a mirror would be a bug)
# and so callers can explicitly skip them.
CENTERLINE_BONES = frozenset({
    "root", "pelvis", "spine", "chest", "neck", "head", "jaw", "tail", "beak",
})


def mirror_bone_name(name: str) -> str | None:
    """Return the left/right mirror counterpart of a bone name.

    'upper_arm.L' -> 'upper_arm.R', 'index_02.R' -> 'index_02.L'.
    Returns None for a name with no recognised L/R suffix (centerline).
    """
    if not name:
        return None
    for left, right in _MIRROR_SUFFIX_PAIRS:
        if name.endswith(left):
            return name[: -len(left)] + right
        if name.endswith(right):
            return name[: -len(right)] + left
    return None


def is_centerline(name: str) -> bool:
    """True if the bone has no L/R mirror counterpart (sits on the centerline)."""
    return mirror_bone_name(name) is None


# ======================================================================
# Breakdown / tween-machine math
# ======================================================================

def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation a→b by t. t is NOT clamped (allows over/undershoot)."""
    return a + (b - a) * t


def breakdown_vec(a, b, t: float):
    """Component-wise lerp of two 3-tuples (location or scale)."""
    return tuple(lerp(a[i], b[i], t) for i in range(3))


def _quat_dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def _quat_normalize(q):
    n = math.sqrt(_quat_dot(q, q))
    if n < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def breakdown_quat(a, b, t: float):
    """Normalised lerp (nlerp) between two quaternions, shortest arc.

    nlerp is cheaper than slerp and visually identical for the small
    blends a breakdown slider produces. Flips b if the dot is negative so
    we always take the short way around (avoids a 360° spin).
    """
    if _quat_dot(a, b) < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
    blended = tuple(lerp(a[i], b[i], t) for i in range(4))
    return _quat_normalize(blended)


def find_bracketing_values(keys, frame: float):
    """Find the values of the keyframes straddling `frame`.

    keys: iterable of (key_frame, value). Sorted internally so callers
          don't have to. Returns (prev_value, next_value) — the value of
          the last key strictly BEFORE `frame` and the first key strictly
          AFTER it. A key exactly on `frame` is ignored (it's the
          breakdown being adjusted). Returns None if there are no keys.

    Used by the breakdown / tween slider: blending t=0→prev, t=1→next
    moves the current frame's pose between its surrounding keys.
    Out-of-range frames clamp to the nearest key (no blend).
    """
    ks = sorted(keys, key=lambda kv: kv[0])
    if not ks:
        return None
    prev = None
    nxt = None
    for f, v in ks:
        if f < frame:
            prev = v
        elif f > frame:
            nxt = v
            break
        # f == frame: the key being adjusted — skip it
    if prev is None and nxt is None:
        # frame sits exactly on the only key(s) — nothing surrounds it
        return (ks[0][1], ks[-1][1])
    if prev is None:
        prev = nxt
    if nxt is None:
        nxt = prev
    return (prev, nxt)


# ======================================================================
# Loop validation
# ======================================================================

@dataclass
class BoneDiff:
    """How much a single bone's transform differs between two frames."""
    bone: str
    loc_delta: float
    rot_delta: float
    scale_delta: float

    @property
    def max_delta(self) -> float:
        return max(self.loc_delta, self.rot_delta, self.scale_delta)


def _vec_distance(a, b) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(len(a))))


def _quat_angle(a, b) -> float:
    """Angle in radians between two quaternions (0 = identical orientation)."""
    a = _quat_normalize(a)
    b = _quat_normalize(b)
    d = abs(_quat_dot(a, b))
    d = max(-1.0, min(1.0, d))
    return 2.0 * math.acos(d)


def transforms_differ(a, b, eps_loc=1e-4, eps_rot=1e-3, eps_scale=1e-4) -> bool:
    """True if two (loc, quat, scale) transforms differ beyond the tolerances."""
    if _vec_distance(a[0], b[0]) > eps_loc:
        return True
    if _quat_angle(a[1], b[1]) > eps_rot:
        return True
    if _vec_distance(a[2], b[2]) > eps_scale:
        return True
    return False


def diff_pose(pose_a: dict, pose_b: dict, eps_loc=1e-4, eps_rot=1e-3, eps_scale=1e-4):
    """Compare two poses bone-by-bone; return the bones that differ.

    pose_a / pose_b: dict[bone_name -> (loc, quat, scale)] sampled at the
    two frames. Returns a list of BoneDiff for bones whose transform
    exceeds tolerance, sorted worst-first — these are the bones that will
    'pop' when the animation loops.
    """
    diffs = []
    for bone, ta in pose_a.items():
        tb = pose_b.get(bone)
        if tb is None:
            continue
        loc_d = _vec_distance(ta[0], tb[0])
        rot_d = _quat_angle(ta[1], tb[1])
        scale_d = _vec_distance(ta[2], tb[2])
        if loc_d > eps_loc or rot_d > eps_rot or scale_d > eps_scale:
            diffs.append(BoneDiff(bone, loc_d, rot_d, scale_d))
    diffs.sort(key=lambda d: d.max_delta, reverse=True)
    return diffs


# ======================================================================
# In-place / root-motion stripping
# ======================================================================

def strip_root_translation(keys, keep_z: bool = True):
    """Zero out the root bone's horizontal translation for an in-place loop.

    keys: list of (frame, x, y, z) tuples for the root bone's location.
    keep_z: if True, vertical motion (crouch/jump height) is preserved;
            only X and Y are zeroed. If False, all translation is removed.

    Returns a new list of (frame, x, y, z) with the stripped values. The
    rig stays planted at the origin so Unity's 'Bake Into Pose' on root
    position produces a clean in-place cycle.
    """
    out = []
    for frame, x, y, z in keys:
        out.append((frame, 0.0, 0.0, z if keep_z else 0.0))
    return out


def root_motion_delta(keys):
    """Total horizontal travel of the root across the clip (for UI display).

    Returns (dx, dy) = last frame's XY minus first frame's XY. Lets the
    operator tell the user 'this clip travels 1.4 m forward' before they
    decide to strip it or keep it as root motion.
    """
    if len(keys) < 2:
        return (0.0, 0.0)
    first = keys[0]
    last = keys[-1]
    return (last[1] - first[1], last[2] - first[2])


# ======================================================================
# Frame-range helpers
# ======================================================================

def nearest_key(key_frames, current, direction: str):
    """Nearest keyframe strictly before/after `current`.

    key_frames: iterable of frame numbers (any order, duplicates ok).
    direction: 'NEXT' → first key > current; 'PREV' → last key < current.
    Returns the frame (int) or None if there's no key on that side.
    """
    fs = sorted({int(round(f)) for f in key_frames})
    cur = int(round(current))
    if direction == 'NEXT':
        for f in fs:
            if f > cur:
                return f
        return None
    # PREV
    prev = None
    for f in fs:
        if f < cur:
            prev = f
        else:
            break
    return prev


def is_keyed_at(key_frames, frame) -> bool:
    """True if any of the given keyframes lands exactly on `frame`."""
    target = int(round(frame))
    return any(int(round(f)) == target for f in key_frames)


def fit_preview_range(frame_start: int, frame_end: int):
    """Clamp/normalise an action's frame range into a valid preview range.

    Guarantees start <= end and both are ints. Trivial, but keeps the
    operator free of off-by-one guards.
    """
    s = int(round(frame_start))
    e = int(round(frame_end))
    if e < s:
        s, e = e, s
    return (s, e)
