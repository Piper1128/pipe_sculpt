"""Genesis-Tracked Rigging — preserve primitive identity through the sculpt pipeline.

v0.5 adds clavicle + toes deform bones, IK control bones (hand_ik, elbow_pole,
foot_ik, knee_pole), and auto-IK constraints on arms and legs. Bone names use
Blender symmetry suffix (.L / .R) for compatibility with mirror/symmetrize tools.
"""
from __future__ import annotations

import json
import math

import bpy
import mathutils
from bpy.types import Operator


VERTEX_ATTR = "pipe_sculpt_bone"
META_PROP = "pipe_sculpt_bone_data"
RIG_TYPE_PROP = "pipe_sculpt_rig_type"


FINGER_NAMES: tuple[str, ...] = ("thumb", "index", "middle", "ring", "pinky")
# Y spacing increased to 30 mm between adjacent fingers so each phalanx
# remains distinct after voxel remesh at 25 mm voxel size.
FINGER_Y_OFFSETS = {
    "pinky":  -0.06,
    "ring":   -0.03,
    "middle":  0.00,
    "index":   0.03,
    "thumb":   0.06,
}
FINGER_PHALANX_LENGTH = 0.035  # 3.5 cm per phalanx; 10.5 cm total finger
FINGER_KNUCKLE_X = 1.20         # x where fingers begin (shared with hand bone tail)


def _finger_bone_name(finger: str, idx: int, suffix: str) -> str:
    """e.g. ('thumb', 1, 'L') -> 'thumb_01.L'"""
    return f"{finger}_{idx:02d}.{suffix}"


def _generate_finger_bone_names() -> tuple[str, ...]:
    out = []
    for suffix in ("L", "R"):
        for finger in FINGER_NAMES:
            for i in range(1, 4):
                out.append(_finger_bone_name(finger, i, suffix))
    return tuple(out)


def _generate_finger_bones() -> tuple:
    """Generate (id, parent, head, tail, kind) tuples for all 30 finger bones.

    Each finger has 3 phalanges chained from the hand bone. Phalanges connect
    head-to-tail so the chain rotates naturally for grip animation.
    """
    out = []
    for suffix, side in (("L", 1), ("R", -1)):
        for finger in FINGER_NAMES:
            y = FINGER_Y_OFFSETS[finger]
            for i in range(1, 4):
                head_x = side * (FINGER_KNUCKLE_X + (i - 1) * FINGER_PHALANX_LENGTH)
                tail_x = side * (FINGER_KNUCKLE_X + i * FINGER_PHALANX_LENGTH)
                head = (head_x, y, 0.40)
                tail = (tail_x, y, 0.40)
                if i == 1:
                    parent = f"hand.{suffix}"
                else:
                    parent = _finger_bone_name(finger, i - 1, suffix)
                bone_id = _finger_bone_name(finger, i, suffix)
                out.append((bone_id, parent, head, tail, 'D'))
    return tuple(out)


_FINGER_BONES_DATA = _generate_finger_bones()


# Deform bones — these get per-vertex weights via the bone-id attribute.
# Order is the canonical bone-index ordering; do not reorder without bumping
# the metadata schema.
DEFORM_BONE_NAMES: tuple[str, ...] = (
    "pelvis",
    "spine",
    "neck",
    "head",
    "clavicle.L",
    "upper_arm.L",
    "forearm.L",
    "hand.L",
    "clavicle.R",
    "upper_arm.R",
    "forearm.R",
    "hand.R",
    "upper_leg.L",
    "lower_leg.L",
    "foot.L",
    "toes.L",
    "upper_leg.R",
    "lower_leg.R",
    "foot.R",
    "toes.R",
) + _generate_finger_bone_names() + ("jaw", "ear.L", "ear.R")
BONE_NAME_TO_INDEX = {n: i for i, n in enumerate(DEFORM_BONE_NAMES)}


# Bone definition: (id, parent, head_offset, tail_offset, kind)
#   kind = 'D' deform, 'C' control (IK targets/poles, root)
# All offsets are CURSOR-RELATIVE; converted to mesh-local at metadata write
# (see HUMANOID_MESH_ORIGIN_OFFSET).
HUMANOID_BONES: tuple = (
    # Master root
    ("root",        None,           (0.00,  0.00,  0.00),  (0.00,  0.00,  0.20),  'C'),

    # Body chain
    ("pelvis",      "root",         (0.00,  0.00, -0.418), (0.00,  0.00, -0.082), 'D'),
    ("spine",       "pelvis",       (0.00,  0.00, -0.082), (0.00,  0.00,  0.585), 'D'),
    ("neck",        "spine",        (0.00,  0.00,  0.585), (0.00,  0.00,  0.625), 'D'),
    ("head",        "neck",         (0.00,  0.00,  0.625), (0.00,  0.00,  0.956), 'D'),

    # Left arm
    ("clavicle.L",  "spine",        (0.00,  0.00,  0.550), (0.30,  0.00,  0.400), 'D'),
    ("upper_arm.L", "clavicle.L",   (0.30,  0.00,  0.400), (0.70,  0.00,  0.400), 'D'),
    ("forearm.L",   "upper_arm.L",  (0.70,  0.00,  0.400), (1.05,  0.00,  0.400), 'D'),
    ("hand.L",      "forearm.L",    (1.05,  0.00,  0.400), (1.20,  0.00,  0.400), 'D'),

    # Right arm (mirror)
    ("clavicle.R",  "spine",        (0.00,  0.00,  0.550), (-0.30, 0.00,  0.400), 'D'),
    ("upper_arm.R", "clavicle.R",   (-0.30, 0.00,  0.400), (-0.70, 0.00,  0.400), 'D'),
    ("forearm.R",   "upper_arm.R",  (-0.70, 0.00,  0.400), (-1.05, 0.00,  0.400), 'D'),
    ("hand.R",      "forearm.R",    (-1.05, 0.00,  0.400), (-1.20, 0.00,  0.400), 'D'),

    # Left leg
    ("upper_leg.L", "pelvis",       (0.11,  0.00, -0.082), (0.11,  0.00, -0.650), 'D'),
    ("lower_leg.L", "upper_leg.L",  (0.11,  0.00, -0.650), (0.11,  0.00, -1.050), 'D'),
    ("foot.L",      "lower_leg.L",  (0.11,  0.00, -1.050), (0.11,  0.20, -1.100), 'D'),
    ("toes.L",      "foot.L",       (0.11,  0.20, -1.100), (0.11,  0.30, -1.100), 'D'),

    # Right leg (mirror)
    ("upper_leg.R", "pelvis",       (-0.11, 0.00, -0.082), (-0.11, 0.00, -0.650), 'D'),
    ("lower_leg.R", "upper_leg.R",  (-0.11, 0.00, -0.650), (-0.11, 0.00, -1.050), 'D'),
    ("foot.R",      "lower_leg.R",  (-0.11, 0.00, -1.050), (-0.11, 0.20, -1.100), 'D'),
    ("toes.R",      "foot.R",       (-0.11, 0.20, -1.100), (-0.11, 0.30, -1.100), 'D'),

    # IK targets and pole vectors (parented to root, no deformation)
    ("hand_ik.L",    "root", (1.05,  0.00,  0.400), (1.20,  0.00,  0.400), 'C'),
    ("elbow_pole.L", "root", (0.70, -0.30,  0.400), (0.70, -0.40,  0.400), 'C'),
    ("hand_ik.R",    "root", (-1.05, 0.00,  0.400), (-1.20, 0.00,  0.400), 'C'),
    ("elbow_pole.R", "root", (-0.70, -0.30, 0.400), (-0.70, -0.40, 0.400), 'C'),

    ("foot_ik.L",    "root", (0.11,  0.00, -1.050), (0.11,  0.20, -1.100), 'C'),
    ("knee_pole.L",  "root", (0.11,  0.30, -0.650), (0.11,  0.40, -0.650), 'C'),
    ("foot_ik.R",    "root", (-0.11, 0.00, -1.050), (-0.11, 0.20, -1.100), 'C'),
    ("knee_pole.R",  "root", (-0.11, 0.30, -0.650), (-0.11, 0.40, -0.650), 'C'),
) + _FINGER_BONES_DATA + (
    # Face bones (children of head)
    ("jaw",   "head", (0.00,  0.05, 0.625), (0.00,  0.13, 0.560), 'D'),
    ("ear.L", "head", (0.135, -0.02, 0.78), (0.165, -0.02, 0.78), 'D'),
    ("ear.R", "head", (-0.135, -0.02, 0.78), (-0.165, -0.02, 0.78), 'D'),
)


# IK constraints: (driven_bone, target_bone, pole_bone, chain_count)
# Pole angle is computed from bone geometry at rig-generation time.
HUMANOID_IK: tuple = (
    ("forearm.L",   "hand_ik.L", "elbow_pole.L", 2),
    ("forearm.R",   "hand_ik.R", "elbow_pole.R", 2),
    ("lower_leg.L", "foot_ik.L", "knee_pole.L",  2),
    ("lower_leg.R", "foot_ik.R", "knee_pole.R",  2),
)


def _signed_angle(u, v, normal):
    """Signed angle between u and v around normal."""
    a = u.angle(v, 0.0)
    if u.cross(v).dot(normal) < 0:
        a = -a
    return a


def _calc_pole_angle(base_bone, ik_bone, pole_pos):
    """Compute pole_angle so the chain's rest pose stays untwisted under IK.

    base_bone: top bone of the IK chain (e.g. upper_arm)
    ik_bone: bone the IK constraint is on (e.g. forearm)
    pole_pos: armature-space position of the pole target bone head

    Sign convention: Blender's IK measures pole_angle around -chain_dir
    (i.e. tip-to-root direction), not chain_dir. Empirically verified by
    pole-angle scan against rest-pose bbox preservation.
    """
    chain_dir = ik_bone.tail_local - base_bone.head_local
    pole_normal = chain_dir.cross(pole_pos - base_bone.head_local)
    if pole_normal.length < 1e-6:
        return 0.0
    projected_pole_axis = pole_normal.cross(base_bone.tail_local - base_bone.head_local)
    if projected_pole_axis.length < 1e-6:
        return 0.0
    base_x = base_bone.matrix_local.to_3x3().col[0]
    return _signed_angle(
        base_x, projected_pole_axis, -chain_dir
    )


# Mesh origin offset: torso primitive is the active mesh after _join, sits at
# cursor + (0, 0, 0.20). All bone coords need this subtracted to land in
# mesh-local space.
HUMANOID_MESH_ORIGIN_OFFSET = (0.0, 0.0, 0.20)


def tag_primitive(obj, bone_name: str) -> None:
    """Tag every vertex of a primitive object with its deform-bone index."""
    bone_index = BONE_NAME_TO_INDEX.get(bone_name, -1)
    attrs = obj.data.attributes
    if VERTEX_ATTR in attrs:
        attrs.remove(attrs[VERTEX_ATTR])
    attr = attrs.new(name=VERTEX_ATTR, type='INT', domain='POINT')
    for i in range(len(obj.data.vertices)):
        attr.data[i].value = bone_index


def _apply_offset(coord, offset):
    return [coord[0] - offset[0], coord[1] - offset[1], coord[2] - offset[2]]


def _serialize_bones(bones, mesh_origin_offset):
    return [
        {
            "id": b[0],
            "parent": b[1],
            "head": _apply_offset(b[2], mesh_origin_offset),
            "tail": _apply_offset(b[3], mesh_origin_offset),
            "kind": b[4],
        }
        for b in bones
    ]


def _serialize_ik(ik_specs):
    return [
        {
            "driven": s[0],
            "target": s[1],
            "pole": s[2],
            "chain": s[3],
        }
        for s in ik_specs
    ]


def store_bone_metadata(obj, rig_type: str) -> None:
    """Store the bone hierarchy + IK spec on the joined object as JSON in mesh-local coords."""
    if rig_type == 'HUMANOID':
        bones = _serialize_bones(HUMANOID_BONES, HUMANOID_MESH_ORIGIN_OFFSET)
        ik = _serialize_ik(HUMANOID_IK)
    else:
        bones = []
        ik = []
    obj[META_PROP] = json.dumps({"bones": bones, "ik": ik})
    obj[RIG_TYPE_PROP] = rig_type


def smart_voxel_remesh(obj) -> bool:
    """Voxel remesh while preserving the bone-id attribute via KDTree nearest-neighbour transfer."""
    attrs = obj.data.attributes
    src_attr = attrs.get(VERTEX_ATTR)
    if src_attr is None:
        bpy.ops.object.voxel_remesh()
        return False

    snapshot = [
        (obj.data.vertices[i].co.copy(), src_attr.data[i].value)
        for i in range(len(obj.data.vertices))
    ]
    if not snapshot:
        # Degenerate input — voxel_remesh would produce nothing anyway, and a
        # later kd.find() on an empty tree returns (None, None, None) which
        # would then crash on snapshot[None]. Bail out cleanly.
        bpy.ops.object.voxel_remesh()
        return False

    bpy.ops.object.voxel_remesh()

    kd = mathutils.kdtree.KDTree(len(snapshot))
    for i, (co, _) in enumerate(snapshot):
        kd.insert(co, i)
    kd.balance()

    if VERTEX_ATTR in attrs:
        attrs.remove(attrs[VERTEX_ATTR])
    new_attr = attrs.new(name=VERTEX_ATTR, type='INT', domain='POINT')
    for i in range(len(obj.data.vertices)):
        _, src_idx, _ = kd.find(obj.data.vertices[i].co)
        if src_idx is None:
            continue
        new_attr.data[i].value = snapshot[src_idx][1]
    return True


def transfer_bone_tags_from_high(high_obj, low_obj) -> bool:
    """Copy the per-vertex bone-id attribute from high_obj to low_obj via KDTree.

    Used after retopology (Quadriflow / Decimate / manual) so the new low-poly
    mesh inherits the high-poly's tags, allowing Generate Rig to skin the
    low-poly directly. Both objects must be in the same world frame.

    Uses the evaluated high-poly mesh (with multires applied if present), not
    the base mesh. Without this, nearest-neighbour matches BASE-mesh positions
    against EVALUATED low-poly vertices — when the user has sculpted on a
    multires modifier, the multires displacement can push surface verts
    further than the base-vertex spacing, and tags land on wrong bones.

    Returns True on success.
    """
    if VERTEX_ATTR not in high_obj.data.attributes:
        return False

    # Get the evaluated mesh so multires displacements are reflected in the
    # vertex positions we KDTree against.
    dg = bpy.context.evaluated_depsgraph_get()
    high_eval = high_obj.evaluated_get(dg)
    high_mesh = high_eval.to_mesh()
    try:
        eval_attr = high_mesh.attributes.get(VERTEX_ATTR)
        if eval_attr is None:
            # Attribute didn't survive evaluation (rare) — fall back to base.
            base_attr = high_obj.data.attributes[VERTEX_ATTR]
            kd = mathutils.kdtree.KDTree(len(high_obj.data.vertices))
            for i, v in enumerate(high_obj.data.vertices):
                kd.insert(v.co, i)
            kd.balance()
            tag_values = [base_attr.data[i].value for i in range(len(high_obj.data.vertices))]
        else:
            kd = mathutils.kdtree.KDTree(len(high_mesh.vertices))
            for i, v in enumerate(high_mesh.vertices):
                kd.insert(v.co, i)
            kd.balance()
            # Cache attribute values before to_mesh_clear() invalidates eval_attr.
            tag_values = [eval_attr.data[i].value for i in range(len(high_mesh.vertices))]
    finally:
        high_eval.to_mesh_clear()

    low_attrs = low_obj.data.attributes
    if VERTEX_ATTR in low_attrs:
        low_attrs.remove(low_attrs[VERTEX_ATTR])
    new_attr = low_attrs.new(name=VERTEX_ATTR, type='INT', domain='POINT')
    for i, v in enumerate(low_obj.data.vertices):
        _, src_idx, _ = kd.find(v.co)
        new_attr.data[i].value = tag_values[src_idx]

    # Copy the JSON metadata too so Generate Rig can read bone hierarchy
    if META_PROP in high_obj:
        low_obj[META_PROP] = high_obj[META_PROP]
    if RIG_TYPE_PROP in high_obj:
        low_obj[RIG_TYPE_PROP] = high_obj[RIG_TYPE_PROP]
    return True


class PIPESCULPT_OT_generate_rig(Operator):
    bl_idname = "pipe_sculpt.generate_rig"
    bl_label = "Generate Rig"
    bl_description = (
        "Build an armature, IK setup, and initial skin weights from preserved "
        "primitive bone metadata (Genesis-Tracked Rigging)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and META_PROP in obj
            and VERTEX_ATTR in obj.data.attributes
        )

    def execute(self, context):
        mesh_obj = context.active_object
        # Snapshot the user's prior mode so we can restore it. Generate Rig
        # bounces through OBJECT → EDIT → OBJECT → WEIGHT_PAINT → OBJECT →
        # POSE → OBJECT, which silently broke the user's session if they
        # were in SCULPT mode on a different object.
        prior_active = context.view_layer.objects.active
        prior_mode = context.mode
        try:
            payload = json.loads(mesh_obj[META_PROP])
            bone_data = payload["bones"]
            ik_data = payload.get("ik", [])
        except (KeyError, ValueError) as e:
            self.report({'ERROR'}, f"Bone metadata missing or corrupt: {e}")
            return {'CANCELLED'}
        if not bone_data:
            self.report({'ERROR'}, "No bone data on mesh")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Idempotency: if mesh already has a GTR Armature modifier pointing at
        # an armature object, we're regenerating an existing rig — nuke the old
        # one cleanly so the scene doesn't end up with `name_Armature.001` and
        # an orphaned previous build.
        existing_arm_mod = mesh_obj.modifiers.get("GTR Armature")
        if existing_arm_mod is not None and existing_arm_mod.object is not None:
            old_arm = existing_arm_mod.object
            old_arm_data = old_arm.data
            mesh_obj.modifiers.remove(existing_arm_mod)
            if mesh_obj.parent is old_arm:
                # Preserve world transform when un-parenting
                world = mesh_obj.matrix_world.copy()
                mesh_obj.parent = None
                mesh_obj.matrix_world = world
            bpy.data.objects.remove(old_arm, do_unlink=True)
            if old_arm_data is not None and old_arm_data.users == 0:
                bpy.data.armatures.remove(old_arm_data, do_unlink=True)

        arm_data = bpy.data.armatures.new(f"{mesh_obj.name}_Armature")
        arm_obj = bpy.data.objects.new(f"{mesh_obj.name}_Armature", arm_data)
        context.collection.objects.link(arm_obj)
        arm_obj.matrix_world = mesh_obj.matrix_world.copy()

        # --- Build edit bones ---
        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = arm_data.edit_bones
        bones_by_id = {}
        for b in bone_data:
            eb = edit_bones.new(b["id"])
            eb.head = b["head"]
            eb.tail = b["tail"]
            eb.use_deform = (b["kind"] == 'D')
            # _calc_pole_angle uses base_bone.matrix_local.to_3x3().col[0] as
            # the reference axis. Roll defaults to whatever Blender computes
            # from bone orientation, which is platform-stable but unintuitive.
            # Pin roll=0 so the X-axis is predictable and IK pole math is too.
            eb.roll = 0.0
            bones_by_id[b["id"]] = eb

        for b in bone_data:
            if b["parent"]:
                child = bones_by_id[b["id"]]
                parent = bones_by_id[b["parent"]]
                child.parent = parent
                if (parent.tail - child.head).length < 0.001:
                    child.use_connect = True

        bpy.ops.object.mode_set(mode='OBJECT')

        # --- Vertex groups + initial weights for deform bones ---
        deform_names = [b["id"] for b in bone_data if b["kind"] == 'D']
        for name in deform_names:
            if name not in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups.new(name=name)

        attr = mesh_obj.data.attributes[VERTEX_ATTR]
        # Map storage-order index -> bone name (DEFORM_BONE_NAMES is the canonical order)
        for vi in range(len(mesh_obj.data.vertices)):
            bi = attr.data[vi].value
            if 0 <= bi < len(DEFORM_BONE_NAMES):
                vg_name = DEFORM_BONE_NAMES[bi]
                if vg_name in mesh_obj.vertex_groups:
                    mesh_obj.vertex_groups[vg_name].add([vi], 1.0, 'REPLACE')

        # --- Parent + Armature modifier ---
        mesh_obj.parent = arm_obj
        mesh_obj.matrix_parent_inverse = arm_obj.matrix_world.inverted()

        arm_mod = mesh_obj.modifiers.get("GTR Armature")
        if arm_mod is None:
            arm_mod = mesh_obj.modifiers.new(name="GTR Armature", type='ARMATURE')
        arm_mod.object = arm_obj
        arm_mod.use_vertex_groups = True
        arm_mod.use_bone_envelopes = False

        # --- Smooth weights ---
        if not bpy.app.background:
            context.view_layer.objects.active = mesh_obj
            try:
                bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
                bpy.ops.object.vertex_group_smooth(
                    group_select_mode='ALL', factor=0.5, repeat=3
                )
                bpy.ops.object.mode_set(mode='OBJECT')
            except RuntimeError as e:
                self.report({'WARNING'}, f"Weight smoothing skipped: {e}")

        # --- IK constraints ---
        if ik_data:
            context.view_layer.objects.active = arm_obj
            bpy.ops.object.mode_set(mode='POSE')
            for spec in ik_data:
                pb = arm_obj.pose.bones.get(spec["driven"])
                if pb is None:
                    continue
                ik_bone = pb.bone
                base_bone = ik_bone
                for _ in range(spec["chain"] - 1):
                    if base_bone.parent is not None:
                        base_bone = base_bone.parent
                pole_bone = arm_obj.data.bones.get(spec["pole"])
                if pole_bone is None:
                    continue
                pole_angle = _calc_pole_angle(
                    base_bone, ik_bone, pole_bone.head_local
                )
                ik = pb.constraints.new('IK')
                ik.target = arm_obj
                ik.subtarget = spec["target"]
                ik.pole_target = arm_obj
                ik.pole_subtarget = spec["pole"]
                ik.chain_count = spec["chain"]
                ik.pole_angle = pole_angle
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        mesh_obj.select_set(True)
        context.view_layer.objects.active = arm_obj

        # Restore the user's prior mode if we disrupted it. context.mode strings
        # ('SCULPT', 'EDIT_MESH', 'POSE', ...) don't map 1:1 to mode_set args
        # ('SCULPT', 'EDIT', 'POSE', ...). Translate the common cases; if it
        # fails (e.g. prior_active was deleted), silently stay in OBJECT.
        if prior_active is not None and prior_active.name in bpy.data.objects:
            mode_translation = {
                'OBJECT': 'OBJECT',
                'EDIT_MESH': 'EDIT',
                'EDIT_ARMATURE': 'EDIT',
                'SCULPT': 'SCULPT',
                'POSE': 'POSE',
                'PAINT_WEIGHT': 'WEIGHT_PAINT',
                'PAINT_VERTEX': 'VERTEX_PAINT',
                'PAINT_TEXTURE': 'TEXTURE_PAINT',
            }
            target_mode = mode_translation.get(prior_mode)
            if target_mode and target_mode != 'OBJECT' and prior_active is not arm_obj:
                try:
                    context.view_layer.objects.active = prior_active
                    bpy.ops.object.mode_set(mode=target_mode)
                except RuntimeError:
                    context.view_layer.objects.active = arm_obj

        n_deform = len(deform_names)
        n_total = len(bone_data)
        n_ik = len(ik_data)
        self.report(
            {'INFO'},
            f"Generated rig '{arm_obj.name}': {n_total} bones ({n_deform} deform), {n_ik} IK chains.",
        )
        return {'FINISHED'}


_classes = (PIPESCULPT_OT_generate_rig,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
