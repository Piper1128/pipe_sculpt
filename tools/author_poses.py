"""Author the standard-pose catalog by capturing channels off the live rig.

Run:  blender --background --python tools/author_poses.py -- <catalog.json> <out.py>

The catalog JSON is a list of pose specs (name/label/category/description/
symmetric/fk/controls) as produced by the pose-catalog design step. For each
pose this:
  1. builds a fresh humanoid + rig,
  2. sets the IK CONTROL bones to (rest head + offset) world targets and the
     FK bones to their euler rotations,
  3. lets the IK solver settle, then captures the non-rest channels of every
     capturable bone (never the 8 IK-solved bones),
  4. expands symmetric poses to a full L+R channel set,
  5. verifies geometry (no NaN, no IK overstretch, symmetry) and
  6. emits a POSE_LIBRARY tuple of PoseSpec(...) literals for
     pose_library_core.py.

Why capture instead of hand-writing numbers: the IK-solved limb channels are
meaningless (identity); the pose lives in the controls + FK, and capturing
replays to the micron (verified in spikes).
"""
import os
import sys
import json
import math

import bpy
import mathutils

ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ADDON, os.path.dirname(ADDON)):
    if p not in sys.path:
        sys.path.insert(0, p)

# One clean scene + one source-copy register, up front. Rebuilding the scene
# per pose re-cycles addon enable/disable and clashes with any installed copy.
bpy.ops.wm.read_factory_settings(use_empty=True)
import pipe_sculpt  # noqa: E402
pipe_sculpt.register()
from pipe_sculpt import pose_library_core as plc  # noqa: E402
from pipe_sculpt import anim_core  # noqa: E402

EPS = 1e-4


def _argv_after_dashes():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def _build_rig():
    bpy.ops.pipe_sculpt.starter_humanoid()
    bpy.ops.pipe_sculpt.generate_rig()
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    return arm


def _reset(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.location = (0.0, 0.0, 0.0)
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def _set_fk(arm, bone, euler_deg):
    pb = arm.pose.bones.get(bone)
    if pb is None:
        return f"FK bone '{bone}' missing"
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = mathutils.Euler(
        [math.radians(d) for d in euler_deg], 'XYZ').to_quaternion()
    return None


def _set_control(arm, bone, offset, rot_euler_deg=None):
    pb = arm.pose.bones.get(bone)
    if pb is None:
        return f"control bone '{bone}' missing"
    if rot_euler_deg is not None:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = mathutils.Euler(
            [math.radians(d) for d in rot_euler_deg], 'XYZ').to_quaternion()
        bpy.context.view_layer.update()
    target = pb.bone.head_local + mathutils.Vector(offset)
    mat = pb.matrix.copy()
    mat.translation = target
    pb.matrix = mat
    return None


def _capture(arm):
    """Non-rest channels of capturable bones -> {bone: (loc, quat)}."""
    out = {}
    for pb in arm.pose.bones:
        if pb.name in plc.IK_SOLVED_BONES:
            continue
        loc = tuple(round(v, 5) for v in pb.location)
        q = pb.matrix_basis.to_quaternion()
        quat = (round(q.w, 5), round(q.x, 5), round(q.y, 5), round(q.z, 5))
        if any(abs(v) > EPS for v in loc) or abs(quat[0] - 1.0) > EPS \
                or any(abs(v) > EPS for v in quat[1:]):
            out[pb.name] = (loc, quat)
    return out


def _verify(arm, spec_name, symmetric):
    """Geometry sanity: no NaN, and no IK control placed beyond limb reach.

    NB: Blender's IK solver does NOT fully converge in --background, so we
    must NOT check "did the deform hand reach the target" (it never does
    headless). Instead we check pure geometry: the distance from the limb-root
    joint to the IK control target vs the rest bone lengths. Both endpoints are
    FK/control (not IK-solved output), so this is reliable headless. In the GUI
    the solver bends the limb to the control — as long as it's within reach.
    """
    issues = []
    for pb in arm.pose.bones:
        for v in list(pb.location) + list(pb.rotation_quaternion):
            if math.isnan(v) or math.isinf(v):
                issues.append(f"{spec_name}: NaN/inf on {pb.name}")
                break
    # (control, upper_bone, lower_bone) — reach = sum of the two rest lengths.
    limbs = [
        ('hand_ik.L', 'upper_arm.L', 'forearm.L'),
        ('hand_ik.R', 'upper_arm.R', 'forearm.R'),
        ('foot_ik.L', 'upper_leg.L', 'lower_leg.L'),
        ('foot_ik.R', 'upper_leg.R', 'lower_leg.R'),
    ]
    for ctrl, upper, lower in limbs:
        cb = arm.pose.bones.get(ctrl)
        ub = arm.pose.bones.get(upper)
        lb = arm.pose.bones.get(lower)
        if not (cb and ub and lb):
            continue
        reach = ub.bone.length + lb.bone.length
        # root joint = the upper bone's LIVE head (shoulder / hip). A chain-root
        # head is anchored by its FK parent, not the IK solve, so it's reliable
        # headless AND it follows a root-drop (sit/crouch) correctly. dist ~=
        # reach just means a straight standing limb (fine); only > reach by a
        # margin is a genuine can't-reach overstretch.
        root = ub.head
        dist = (cb.head - root).length
        if dist > reach * 1.03:
            issues.append(
                f"{spec_name}: {ctrl} target is {dist:.3f} from {upper} root "
                f"but reach is {reach:.3f} ({dist / reach:.2f}x) — overstretch, pull the target in")
    return issues


def _set_fk_quat(arm, bone, quat):
    pb = arm.pose.bones.get(bone)
    if pb is None:
        return f"FK twin '{bone}' missing"
    pb.rotation_mode = 'QUATERNION'
    pb.rotation_quaternion = quat
    return None


def _mirror_quat(q):
    return mathutils.Quaternion((q.w, q.x, -q.y, -q.z))


def author_one(arm, spec):
    """Apply the spec to the live rig (mirroring symmetric poses to BOTH sides
    so the reach check is valid on both), then capture the non-rest channels."""
    _reset(arm)
    warns = []
    symmetric = spec.get('symmetric', False)

    for fk in spec.get('fk', []):
        e = _set_fk(arm, fk['bone'], fk['euler_deg'])
        if e:
            warns.append(e)
        if symmetric:
            twin = anim_core.mirror_bone_name(fk['bone'])
            if twin is not None:
                q = mathutils.Euler(
                    [math.radians(d) for d in fk['euler_deg']], 'XYZ').to_quaternion()
                _set_fk_quat(arm, twin, _mirror_quat(q))
    bpy.context.view_layer.update()

    for c in spec.get('controls', []):
        e = _set_control(arm, c['bone'], c['offset'], c.get('rot_euler_deg'))
        if e:
            warns.append(e)
        if symmetric:
            twin = anim_core.mirror_bone_name(c['bone'])
            if twin is not None:
                off = c['offset']
                m_off = (-off[0], off[1], off[2])
                rot = c.get('rot_euler_deg')
                m_rot = ([rot[0], -rot[1], -rot[2]] if rot else None)
                _set_control(arm, twin, m_off, m_rot)
    bpy.context.view_layer.update()

    warns += _verify(arm, spec['name'], symmetric)
    channels = _capture(arm)  # both sides already posed — capture is complete

    tmp = plc.PoseSpec(spec['name'], spec['label'], spec['category'],
                       spec['description'], channels=channels)
    warns += plc.validate_pose(tmp)
    return channels, warns


def _clean(t):
    # Normalise -0.0 -> 0.0 so the frozen data reads cleanly.
    return tuple(0.0 if v == 0 else v for v in t)


def _fmt_channels(channels):
    if not channels:
        return "{}"
    lines = ["{"]
    for bone in sorted(channels):
        loc, quat = channels[bone]
        lines.append(f'            "{bone}": ({_clean(loc)!r}, {_clean(quat)!r}),')
    lines.append("        }")
    return "\n".join(lines)


def main():
    args = _argv_after_dashes()
    catalog_path = args[0] if args else os.path.join(ADDON, "tools", "pose_catalog.json")
    out_path = args[1] if len(args) > 1 else os.path.join(ADDON, "tools", "pose_library_data.py")

    with open(catalog_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    poses = catalog["poses"] if isinstance(catalog, dict) else catalog

    entries = []
    all_warns = []
    # Always ship a clean T_POSE first (empty channels).
    if not any(p['name'] == 'T_POSE' for p in poses):
        poses = [{'name': 'T_POSE', 'label': 'T-Pose', 'category': 'Stance',
                  'description': 'Reference rest pose — arms out, legs down.',
                  'symmetric': True, 'fk': [], 'controls': []}] + poses

    arm = _build_rig()
    for spec in poses:
        channels, warns = author_one(arm, spec)
        for w in warns:
            print("AUTHOR-WARN", w)
        all_warns += warns
        entries.append(
            f'    PoseSpec(\n'
            f'        name={spec["name"]!r},\n'
            f'        label={spec["label"]!r},\n'
            f'        category={spec["category"]!r},\n'
            f'        description={spec["description"]!r},\n'
            f'        channels={_fmt_channels(channels)},\n'
            f'    ),'
        )
        print(f"AUTHOR-OK {spec['name']}: {len(channels)} channels")

    body = "POSE_LIBRARY: tuple = (\n" + "\n".join(entries) + "\n)\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"AUTHOR-WROTE {out_path} ({len(poses)} poses, {len(all_warns)} warnings)")


main()
