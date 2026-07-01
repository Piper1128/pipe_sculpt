"""Pose library core — pure Python, no Blender dependencies.

Born Clean per IronCore conventions: the standard-pose catalog + all the
pose math (mirroring, influence blend, validation) live here, bpy-free and
unit-tested with pytest. The bpy adapter (pose_library_ops.py) reads a pose
from here and writes its channels onto the armature's pose bones / keyframes.

WHY the catalog stores what it does
-----------------------------------
The generated humanoid rig is IK-driven: forearm.L/R and lower_leg.L/R carry
IK constraints (chain=2), so upper_arm/forearm/upper_leg/lower_leg are solved
by the IK solver at evaluation time — their .location/.rotation_quaternion
channels stay at rest and are meaningless to store. A pose is therefore fully
defined by:
  * the IK CONTROL bones (hand_ik/foot_ik/elbow_pole/knee_pole/root) — moving
    the control makes the solver bend the limb, and
  * the FK bones (torso, clavicles, hand/foot/toes, fingers) — plain rotation.
Capture-then-replay of exactly those channels reproduces an IK pose to the
micron (verified). So the 8 IK-solved bones are NEVER stored, applied, or
keyed — see IK_SOLVED_BONES.

Channel format (matches anim_ops pose buffer, minus scale which poses leave
at identity):  channels = { bone_name: (loc, quat) }
  loc  = (x, y, z)
  quat = (w, x, y, z)  normalised
Bones absent from a pose's channels are at REST — applying a pose resets every
capturable bone to rest first, so poses never bleed into each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# anim_core holds the single source of truth for L↔R name mirroring and the
# nlerp/lerp helpers. In the Blender addon this module lives under the
# pipe_sculpt package; under pytest each *_core is exec'd as a top-level
# module (see tests/conftest.py). Support both without importing bpy.
try:  # addon (package) context
    from . import anim_core
except ImportError:  # pytest standalone context
    import anim_core


# The 8 bones whose transform the IK solver computes — never store/apply/key.
IK_SOLVED_BONES = frozenset({
    "upper_arm.L", "upper_arm.R", "forearm.L", "forearm.R",
    "upper_leg.L", "upper_leg.R", "lower_leg.L", "lower_leg.R",
})

REST_LOC = (0.0, 0.0, 0.0)
REST_QUAT = (1.0, 0.0, 0.0, 0.0)

POSE_CATEGORIES = ("Stance", "Locomotion", "Action")


@dataclass(frozen=True)
class PoseSpec:
    """One standard pose: a name/label + the non-rest bone channels.

    channels maps bone_name -> (loc, quat). Bones not listed are at rest.
    Never contains an IK_SOLVED_BONES entry (validated).
    """
    name: str
    label: str
    category: str
    description: str
    channels: dict = field(default_factory=dict)


# ----------------------------------------------------------------------
# Mirroring (pure) — used for "apply mirrored" and to expand symmetric
# catalog entries authored on the .L side only.
# ----------------------------------------------------------------------

def mirror_transform(loc, quat):
    """Mirror one (loc, quat) across the X axis (Blender's X-flip convention).

    Position: negate X. Rotation quaternion: negate Y and Z. Matches
    anim_ops._mirror_transform so hand-posed mirroring and library mirroring
    agree exactly.
    """
    lx, ly, lz = loc
    w, x, y, z = quat
    return ((-lx, ly, lz), (w, x, -y, -z))


def mirror_channels(channels: dict) -> dict:
    """Return a fully L<->R mirrored copy of a channels dict.

    Each bone maps to its mirror twin (upper_arm.L -> upper_arm.R); a centre
    bone (no twin) keeps its name but is mirrored in place so an off-centre
    lean flips sides correctly.
    """
    out: dict = {}
    for bone, (loc, quat) in channels.items():
        twin = anim_core.mirror_bone_name(bone) or bone
        out[twin] = mirror_transform(loc, quat)
    return out


def expand_symmetric(channels: dict) -> dict:
    """Expand a pose authored on the .L/centre side into a full L+R pose.

    For every .L (or centre-with-nonzero) channel, add the mirrored .R twin.
    Centre bones are kept as-is (a symmetric pose must author them already
    symmetric, i.e. no side-lean). Used when a catalog entry is flagged
    symmetric to halve the stored data and guarantee perfect symmetry.
    """
    out = dict(channels)
    for bone, (loc, quat) in channels.items():
        twin = anim_core.mirror_bone_name(bone)
        if twin is not None and twin not in out:
            out[twin] = mirror_transform(loc, quat)
    return out


# ----------------------------------------------------------------------
# Influence blend (pure) — apply a pose at t in [0,1] from the rest pose.
# ----------------------------------------------------------------------

def blend_from_rest(loc, quat, t: float):
    """Blend a single channel from rest toward (loc, quat) by t in [0,1].

    Location lerps from (0,0,0); rotation nlerps from identity (shortest arc).
    t=0 -> rest, t=1 -> the pose. Reuses anim_core's tween math.
    """
    b_loc = anim_core.breakdown_vec(REST_LOC, loc, t)
    b_quat = anim_core.breakdown_quat(REST_QUAT, quat, t)
    return (b_loc, b_quat)


def blend_channels(channels: dict, t: float) -> dict:
    """Blend a whole channels dict from rest by t (for influence < 1.0)."""
    if t >= 1.0:
        return dict(channels)
    return {bone: blend_from_rest(loc, quat, t) for bone, (loc, quat) in channels.items()}


# ----------------------------------------------------------------------
# Catalog access
# ----------------------------------------------------------------------

def get_pose(name: str) -> PoseSpec:
    """Look up a pose by name. Raises KeyError if unknown."""
    for p in POSE_LIBRARY:
        if p.name == name:
            return p
    raise KeyError(f"Unknown pose '{name}'. Known: {[p.name for p in POSE_LIBRARY]}")


def pose_names() -> tuple:
    return tuple(p.name for p in POSE_LIBRARY)


def poses_by_category() -> dict:
    """Return {category: [PoseSpec, ...]} preserving catalog order."""
    out = {c: [] for c in POSE_CATEGORIES}
    for p in POSE_LIBRARY:
        out.setdefault(p.category, []).append(p)
    return out


def validate_pose(spec: PoseSpec, known_bones=None) -> list:
    """Return a list of problem strings for a pose (empty = valid).

    Checks: no IK-solved bone stored, quats look normalised, and (if
    known_bones given) every channel bone exists on the rig.
    """
    issues = []
    for bone, val in spec.channels.items():
        if bone in IK_SOLVED_BONES:
            issues.append(f"{spec.name}: stores IK-solved bone '{bone}' (would fight the solver)")
        loc, quat = val
        if len(loc) != 3 or len(quat) != 4:
            issues.append(f"{spec.name}: '{bone}' malformed channel {val!r}")
            continue
        mag = sum(c * c for c in quat) ** 0.5
        if abs(mag - 1.0) > 1e-3:
            issues.append(f"{spec.name}: '{bone}' quat not normalised (|q|={mag:.4f})")
        if known_bones is not None and bone not in known_bones:
            issues.append(f"{spec.name}: '{bone}' not on the rig")
    return issues


# ----------------------------------------------------------------------
# THE CATALOG
# Poses are authored via tools/author_poses.py (sets IK-control world targets
# + FK eulers on the live rig, captures channels) and frozen here as data.
# T_POSE is the trivial empty pose (everything at rest). The rest are filled
# in by the authoring pass.
# ----------------------------------------------------------------------

POSE_LIBRARY: tuple = (
    PoseSpec(
        name='T_POSE',
        label='T-Pose',
        category='Stance',
        description='Canonical bind/calibration pose. All FK bones zero, all IK controls at rest. Arms horizontal at Z=0.400, legs straight down. The only pose that intentionally has zero bend margin (dead-straight limbs) — use strictly as skinning/retarget reference.',
        channels={},
    ),
    PoseSpec(
        name='A_POSE',
        label='A-Pose',
        category='Stance',
        description='Relaxed calibration pose; arms lowered along a clean diagonal so the deltoid skins naturally. Hand target clamped to 0.714 from shoulder (was 0.75 at the limit) to leave a hair of IK bend so the arm does not lock straight.',
        channels={
            "clavicle.L": ((0.0, 0.0, 0.0), (0.99863, 0.0, 0.0, 0.05234)),
            "clavicle.R": ((0.0, 0.0, 0.0), (0.99863, 0.0, 0.0, -0.05234)),
            "elbow_pole.L": ((0.05, 0.1, -0.3), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((-0.05, 0.1, -0.3), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.0, -0.18, -0.43), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.0, -0.18, -0.43), (1.0, 0.0, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='RELAXED_IDLE',
        label='Relaxed Idle',
        category='Stance',
        description='Neutral standing base — weight even, arms hang just ahead of the thighs with a soft elbow bend, chest lifted a touch, soft knees. The blend-tree centre every state cross-fades from. Hand dist 0.436, foot micro-stance — all comfortably inside reach.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99966, 0.02618, 0.0, 0.0)),
            "clavicle.L": ((0.0, 0.0, 0.0), (0.99939, 0.0, 0.0, 0.0349)),
            "clavicle.R": ((0.0, 0.0, 0.0), (0.99939, 0.0, 0.0, -0.0349)),
            "elbow_pole.L": ((-0.06, 0.06, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.06, 0.06, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.02, -0.00485, 0.0194), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((-0.02, -0.00485, 0.0194), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.05, -0.42, -0.28), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.05, -0.42, -0.28), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99985, 0.01745, 0.0, 0.0)),
            "knee_pole.L": ((0.0, 0.03, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.03, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99985, -0.01745, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='CONTRAPPOSTO_HIP',
        label='Contrapposto (Weight Shift)',
        category='Stance',
        description='Living-idle weight shift onto the LEFT leg — hip hikes over the weighted foot, spine S-curves to counter, free (R) foot eases out+forward+in with a light heel and broken knee. Genuinely asymmetric so both sides are given explicitly (do not auto-mirror). Free-foot dist 0.933. NOTE: pelvis Z sign assumes +Z hikes the left hip; flip pelvis/head Z if the left hip drops in-editor.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99966, 0.0, 0.0, 0.02618)),
            "elbow_pole.L": ((-0.05, 0.05, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.05, 0.05, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((-0.06, 0.06791, 0.05821), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.06, -0.45, -0.3), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.1, -0.4, -0.28), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99905, 0.0, 0.0, -0.04362)),
            "knee_pole.L": ((0.0, 0.02, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.06, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99813, 0.0, 0.0, 0.06105)),
            "spine": ((0.0, 0.0, 0.0), (0.99939, 0.0, 0.0, -0.0349)),
        },
    ),
    PoseSpec(
        name='POWER_STANCE_ARMS_CROSSED',
        label='Power Stance (Arms Crossed)',
        category='Stance',
        description='Confident/skeptical hero portrait: feet a touch wider than hips, forearms folded across the chest (right forearm on top). Foot offset widened with a small lift to 0.931 (a flat wide stance alone hits the 0.968 straight-leg limit). Hands cross the chest at 0.687/0.638. Asymmetric fold — both arms given.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99939, 0.0349, 0.0, 0.0)),
            "elbow_pole.L": ((0.3, -0.1, -0.28), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((-0.3, -0.1, -0.3), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.08, -0.0097, 0.03881), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((-0.08, -0.0097, 0.03881), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.32, -1.3, -0.05), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.3, -1.35, -0.15), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99939, 0.0, 0.0, -0.0349)),
            "index_01.L": ((0.0, 0.0, 0.0), (0.98481, 0.17365, 0.0, 0.0)),
            "index_01.R": ((0.0, 0.0, 0.0), (0.98481, 0.17365, 0.0, 0.0)),
            "neck": ((0.0, 0.0, 0.0), (0.99966, -0.02618, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='CROUCH_SNEAK',
        label='Crouch / Sneak',
        category='Stance',
        description='Lowered stealth stance: root drops 0.32 (whole body lowers), deep knee bend, torso pitched forward with head kept level, hands drawn in and ready near chest. Foot offset adds +0.30 Z to keep feet on the floor as the root sinks (apply root offset first, then foot). Deep-bend leg ~0.33, strongly folded (intended). Hand dist 0.373.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99756, 0.06976, 0.0, 0.0)),
            "elbow_pole.L": ((-0.05, 0.05, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.05, 0.05, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot.L": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "foot.R": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "foot_ik.L": ((0.03, -0.0291, 0.32257), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((-0.03, -0.0291, 0.32257), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.22, -0.45, 0.02), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.22, -0.45, 0.02), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99863, -0.05234, 0.0, 0.0)),
            "knee_pole.L": ((0.0, 0.12, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.12, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "neck": ((0.0, 0.0, 0.0), (0.99619, -0.08716, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99619, 0.08716, 0.0, 0.0)),
            "root": ((0.0, -0.32, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.98769, 0.15643, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='SITTING_RELAXED',
        label='Sitting (Invisible Chair)',
        category='Stance',
        description='Seated on an implied stool: root drops 0.42 and nudges forward so thighs go horizontal, knees bent ~90 via strong +Y knee pole, feet flat, hands resting on thighs. Foot offset adds +0.42 Z to cancel the root drop. With the dropped root the shoulder also lowers, so hand-on-thigh dist is only 0.44 and knee-bend leg ~0.47. Apply root first, then feet/hands.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99863, 0.05234, 0.0, 0.0)),
            "elbow_pole.L": ((-0.1, 0.1, -0.15), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.1, 0.1, -0.15), (1.0, 0.0, 0.0, 0.0)),
            "foot.L": ((0.0, 0.0, 0.0), (0.99619, 0.08716, 0.0, 0.0)),
            "foot.R": ((0.0, 0.0, 0.0), (0.99619, 0.08716, 0.0, 0.0)),
            "foot_ik.L": ((0.0, 0.3347, 0.5166), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((0.0, 0.3347, 0.5166), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.32, -0.48, -0.5), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.32, -0.48, -0.5), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.L": ((0.0, 0.2, 0.05), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.2, 0.05), (1.0, 0.0, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99756, 0.06976, 0.0, 0.0)),
            "root": ((0.0, -0.42, -0.05), (1.0, 0.0, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='AIM_READY_2H',
        label='Aim / Ready (Two-Hand)',
        category='Stance',
        description='Weapon-up firing stance: right hand at the trigger (0.586), left hand forward on the fore-end (0.712, deliberately near reach for an extended support arm), torso bladed, shoulder into the stock, bladed foot stance. Asymmetric two-hand grip — both sides given. Author the weapon-mesh grip points to these world targets.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99829, 0.02614, -0.05232, 0.00137)),
            "clavicle.L": ((0.0, 0.0, 0.0), (0.99756, 0.06976, 0.0, 0.0)),
            "clavicle.R": ((0.0, 0.0, 0.0), (0.99863, 0.0, 0.0, -0.05234)),
            "elbow_pole.L": ((-0.05, 0.1, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.05, 0.1, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.06, 0.04366, 0.03153), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((-0.04, -0.14067, -0.01455), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.62, -0.4, -0.02), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.55, -0.55, -0.02), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99939, 0.0, -0.0349, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99756, 0.0, -0.06976, 0.0)),
        },
    ),
    PoseSpec(
        name='WALK_CONTACT_L',
        label='Walk — Contact (L Fwd)',
        category='Locomotion',
        description='Stride contact key: LEFT foot heel-strikes forward (0.944, trimmed from 0.983 by adding a small heel lift), RIGHT foot at toe-off behind (0.939). Opposite-arm swing — L arm back, R arm forward. Pelvis twists toward the trailing leg, ribcage counter-rotates. Asymmetric contact — both sides given; mirror it in time for the R-contact key.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99905, 0.0, -0.04362, 0.0)),
            "elbow_pole.L": ((-0.04, 0.08, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.04, 0.06, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot.L": ((0.0, 0.0, 0.0), (0.99452, -0.10453, 0.0, 0.0)),
            "foot.R": ((0.0, 0.0, 0.0), (0.98163, 0.19081, 0.0, 0.0)),
            "foot_ik.L": ((0.0, 0.2013, 0.10186), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((0.0, -0.24739, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.18, -0.38, -0.22), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.2, -0.32, -0.2), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99985, 0.0, 0.01745, 0.0)),
            "knee_pole.L": ((0.0, 0.05, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.1, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99863, 0.0, 0.05234, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99966, 0.0, -0.02618, 0.0)),
        },
    ),
    PoseSpec(
        name='WALK_PASSING_L',
        label='Walk — Passing',
        category='Locomotion',
        description="The 'up' position between contacts: RIGHT (swing) leg lifts up under the hip with a high bent knee (swing foot 0.75), LEFT (support) leg planted straight and vertical (0.948). Body rides up ~0.03 over the support leg; the planted foot subtracts that rise to stay on the floor. Arms pass through near-neutral. Asymmetric — both sides given.",
        channels={
            "foot.R": ((0.0, 0.0, 0.0), (0.98769, -0.15643, 0.0, 0.0)),
            "foot_ik.R": ((0.0, 0.00485, 0.22798), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.0, -0.4, -0.24), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.0, -0.4, -0.24), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.L": ((0.0, 0.02, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.16, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99966, 0.0, 0.0, 0.02618)),
            "root": ((0.0, 0.02, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99996, -0.00873, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='RUN_CONTACT_L',
        label='Run — Contact / Drive (L Fwd)',
        category='Locomotion',
        description='Aggressive run stride: LEFT foot strikes under the mass near CoM (short forward reach, 0.926), RIGHT leg drives fully back with heel high (0.825), torso pitched forward, arms pumping bent ~90 opposite the legs (hands rise toward chest/hip). Root compresses 0.10 at contact. Asymmetric — both sides given; mirror in time for R-contact.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99483, 0.08704, -0.05214, 0.00456)),
            "elbow_pole.L": ((-0.05, 0.14, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.05, 0.12, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.0, 0.10429, 0.07761), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((0.0, -0.33955, 0.12127), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.3, -0.4, 0.05), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.34, -0.34, 0.06), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99604, -0.08714, 0.01739, 0.00152)),
            "knee_pole.L": ((0.0, 0.14, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.06, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "neck": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.9962, 0.05221, 0.06966, -0.00365)),
            "root": ((0.0, -0.1, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99194, 0.1218, -0.03464, 0.00425)),
        },
    ),
    PoseSpec(
        name='REACH_FORWARD',
        label='Reach Forward (Both Hands)',
        category='Action',
        description="Both arms extended forward at chest height, palms out — push / catch / 'stop'. Shoulders protract, upper back rounds, slight lean into the push. Hand dist 0.680, elbows soft and down-out. Symmetric.",
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99863, 0.05234, 0.0, 0.0)),
            "clavicle.L": ((0.0, 0.0, 0.0), (0.99619, 0.08716, 0.0, 0.0)),
            "clavicle.R": ((0.0, 0.0, 0.0), (0.99619, 0.08716, 0.0, 0.0)),
            "elbow_pole.L": ((-0.02, -0.06, -0.08), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.02, -0.06, -0.08), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.55, -0.35, -0.02), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.55, -0.35, -0.02), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99985, 0.01745, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99939, 0.0349, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='REACH_HIGH',
        label='Reach Overhead (Extreme)',
        category='Action',
        description='Both arms stretch up-and-forward toward full extension — grab-a-ledge / surrender-high / stretch. Hands converge inboard as they rise (real overhead reach), ribcage opens with a slight back-bend, look up toward the hands. Hand dist 0.682, kept deliberately under 0.75 so the arm never straight-locks. Symmetric.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "clavicle.L": ((0.0, 0.0, 0.0), (0.99255, 0.0, 0.0, -0.12187)),
            "clavicle.R": ((0.0, 0.0, 0.0), (0.99255, 0.0, 0.0, 0.12187)),
            "elbow_pole.L": ((-0.1, -0.04, -0.06), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.1, -0.04, -0.06), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.18, -0.48, 0.6), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.18, -0.48, 0.6), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99863, 0.05234, 0.0, 0.0)),
            "neck": ((0.0, 0.0, 0.0), (0.99939, 0.0349, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99863, -0.05234, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='WAVE_HELLO',
        label='Waving Hello',
        category='Action',
        description='Right arm raised beside the head, forearm vertical, mid-wave; left arm relaxed in A-pose; head and chest turn toward the wave. Waving-hand dist 0.427 (strong elbow bend, hand at head height), resting-hand dist 0.728. Asymmetric — both arms given. Open-hand fan on the fingers is optional.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99939, 0.0, 0.0, -0.0349)),
            "elbow_pole.L": ((0.05, 0.1, -0.3), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((-0.1, 0.05, -0.35), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.0, -0.18, -0.43), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.05, -0.45, 0.3), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99863, 0.0, 0.0, -0.05234)),
            "index_01.R": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "pinky_01.R": ((0.0, 0.0, 0.0), (0.99756, 0.06976, 0.0, 0.0)),
            "thumb_01.R": ((0.0, 0.0, 0.0), (0.99452, 0.0, 0.0, -0.10453)),
        },
    ),
    PoseSpec(
        name='VICTORY_CHEER',
        label='Victory / Cheer',
        category='Action',
        description='Both arms thrown up in a wide celebratory V, fists clenched, chest open, chin up. High-energy reel closer. Hand target CLAMPED to 0.612 from shoulder (raw draft offset overshot to 1.05 — the fists must come inboard as they rise since the arm is only 0.75 long and rest is already at shoulder height). The big vertical read comes from the chest/head lean, not from overstretching the arm. Symmetric.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
            "elbow_pole.L": ((-0.1, -0.1, 0.3), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.1, -0.1, 0.3), (1.0, 0.0, 0.0, 0.0)),
            "hand.L": ((0.0, 0.0, 0.0), (0.99144, 0.0, 0.0, -0.13053)),
            "hand.R": ((0.0, 0.0, 0.0), (0.99144, 0.0, 0.0, 0.13053)),
            "hand_ik.L": ((-0.1, -0.5, 0.55), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.1, -0.5, 0.55), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99619, -0.08716, 0.0, 0.0)),
            "index_01.L": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "index_01.R": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "middle_01.L": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "middle_01.R": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "pinky_01.L": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "pinky_01.R": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "ring_01.L": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "ring_01.R": ((0.0, 0.0, 0.0), (0.95372, 0.30071, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99939, -0.0349, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='THINKING_CHIN',
        label='Thinking / Hand-on-Chin',
        category='Action',
        description='Contemplative portrait: right hand to the chin with a supported forearm (0.365, deep bend), left arm crosses the torso to cradle the right elbow (0.472), head tilts down with a slight roll toward the chin hand. Asymmetric — both arms given. Index extended toward the jaw, other fingers curled.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99905, 0.0, 0.0, 0.04362)),
            "elbow_pole.L": ((0.2, -0.05, -0.2), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((-0.2, -0.1, -0.55), (1.0, 0.0, 0.0, 0.0)),
            "hand.R": ((0.0, 0.0, 0.0), (0.96146, 0.16953, -0.03758, -0.21315)),
            "hand_ik.L": ((-0.3, -0.85, -0.35), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.28, -0.9, 0.18), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99483, 0.05214, 0.00456, 0.08704)),
            "index_01.R": ((0.0, 0.0, 0.0), (0.99144, -0.13053, 0.0, 0.0)),
            "middle_01.R": ((0.0, 0.0, 0.0), (0.93969, 0.34202, 0.0, 0.0)),
            "neck": ((0.0, 0.0, 0.0), (0.99939, 0.0349, 0.0, 0.0)),
            "ring_01.R": ((0.0, 0.0, 0.0), (0.93969, 0.34202, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='DRAMATIC_REACH',
        label='Dramatic Reach',
        category='Action',
        description='One arm thrust forward-up reaching off-camera in a forward lunge; the other arm sweeps back as counterbalance. Reaching-hand CLAMPED to 0.711 (raw draft offset overshot 0.75 — the apparent extra reach comes from the big chest/spine forward lean, not the arm). Trailing hand 0.726. Front foot forward 0.937 (trimmed with a lift), rear foot trailing 0.918. Asymmetric — both sides given.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.98769, -0.15643, 0.0, 0.0)),
            "elbow_pole.L": ((0.0, 0.2, -0.1), (1.0, 0.0, 0.0, 0.0)),
            "elbow_pole.R": ((0.1, 0.2, 0.1), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.0, -0.3153, 0.02425), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.R": ((0.0, 0.27164, 0.15037), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((0.45, -0.3, -0.35), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((0.35, -0.15, 0.15), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.99452, -0.10453, 0.0, 0.0)),
            "knee_pole.R": ((0.0, 0.1, 0.0), (1.0, 0.0, 0.0, 0.0)),
            "pelvis": ((0.0, 0.0, 0.0), (0.99863, 0.05234, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99756, -0.06976, 0.0, 0.0)),
        },
    ),
    PoseSpec(
        name='HIT_REACT_FLINCH',
        label='Hit React (Flinch)',
        category='Action',
        description='Upper-body flinch from a frontal-left impact: torso recoils back and twists away, head snaps back+aside, near (L) hand flies up to guard the face (0.532), far (R) arm flails back, weight staggers onto the back foot (0.955). Root driven back+down. Best baked as a short snappy 1-frame extreme for an additive upper-body layer. Asymmetric — both sides given.',
        channels={
            "chest": ((0.0, 0.0, 0.0), (0.99377, -0.08694, -0.00608, 0.06949)),
            "elbow_pole.L": ((-0.05, 0.05, 0.1), (1.0, 0.0, 0.0, 0.0)),
            "foot_ik.L": ((0.06, -0.10186, -0.00485), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.L": ((-0.2, -0.3, 0.2), (1.0, 0.0, 0.0, 0.0)),
            "hand_ik.R": ((-0.15, -0.35, -0.15), (1.0, 0.0, 0.0, 0.0)),
            "head": ((0.0, 0.0, 0.0), (0.98393, -0.15584, -0.01363, 0.08608)),
            "neck": ((0.0, 0.0, 0.0), (0.99255, -0.12187, 0.0, 0.0)),
            "root": ((0.0, -0.03, 0.06), (1.0, 0.0, 0.0, 0.0)),
            "spine": ((0.0, 0.0, 0.0), (0.99027, -0.13917, 0.0, 0.0)),
        },
    ),
)
