"""Genesis-Tracked Rigging — preserve primitive identity through the sculpt pipeline.

Each starter primitive carries a per-vertex bone-id integer attribute. The
identity survives voxel remesh via nearest-neighbour transfer (smart_voxel_remesh)
and is later read back by Generate Rig to build an armature plus initial skin
weights without manual rigging.
"""
from __future__ import annotations

import json

import bpy
import mathutils
from bpy.types import Operator


VERTEX_ATTR = "sculpt_kit_bone"
META_PROP = "sculpt_kit_bone_data"
RIG_TYPE_PROP = "sculpt_kit_rig_type"


# Bone hierarchy. Coordinates are CURSOR-RELATIVE — converted to mesh-local
# at the moment of metadata write (see HUMANOID_MESH_ORIGIN_OFFSET).
# Tuple shape: (id, parent, head_offset, tail_offset)
HUMANOID_BONES: tuple[tuple[str, str | None, tuple[float, float, float], tuple[float, float, float]], ...] = (
    ("pelvis",      None,            (0.00,  0.00, -0.418), (0.00,  0.00, -0.082)),
    ("spine",       "pelvis",        (0.00,  0.00, -0.082), (0.00,  0.00,  0.585)),
    ("neck",        "spine",         (0.00,  0.00,  0.585), (0.00,  0.00,  0.625)),
    ("head",        "neck",          (0.00,  0.00,  0.625), (0.00,  0.00,  0.956)),
    ("L_upper_arm", "spine",         (0.30,  0.00,  0.400), (0.70,  0.00,  0.400)),
    ("L_forearm",   "L_upper_arm",   (0.70,  0.00,  0.400), (1.05,  0.00,  0.400)),
    ("L_hand",      "L_forearm",     (1.05,  0.00,  0.400), (1.20,  0.00,  0.400)),
    ("R_upper_arm", "spine",         (-0.30, 0.00,  0.400), (-0.70, 0.00,  0.400)),
    ("R_forearm",   "R_upper_arm",   (-0.70, 0.00,  0.400), (-1.05, 0.00,  0.400)),
    ("R_hand",      "R_forearm",     (-1.05, 0.00,  0.400), (-1.20, 0.00,  0.400)),
    ("L_thigh",     "pelvis",        (0.11,  0.00, -0.082), (0.11,  0.00, -0.650)),
    ("L_shin",      "L_thigh",       (0.11,  0.00, -0.650), (0.11,  0.00, -1.050)),
    ("L_foot",      "L_shin",        (0.11,  0.00, -1.050), (0.11,  0.20, -1.100)),
    ("R_thigh",     "pelvis",        (-0.11, 0.00, -0.082), (-0.11, 0.00, -0.650)),
    ("R_shin",      "R_thigh",       (-0.11, 0.00, -0.650), (-0.11, 0.00, -1.050)),
    ("R_foot",      "R_shin",        (-0.11, 0.00, -1.050), (-0.11, 0.20, -1.100)),
)

BONE_NAME_TO_INDEX = {b[0]: i for i, b in enumerate(HUMANOID_BONES)}

# The torso primitive sits at cursor + (0, 0, 0.20); after _join it becomes the
# joined object's origin, so mesh-local coords = cursor-relative - this offset.
HUMANOID_MESH_ORIGIN_OFFSET = (0.0, 0.0, 0.20)


def tag_primitive(obj, bone_name: str) -> None:
    """Tag every vertex of a primitive object with its bone index."""
    bone_index = BONE_NAME_TO_INDEX.get(bone_name, -1)
    attrs = obj.data.attributes
    if VERTEX_ATTR in attrs:
        attrs.remove(attrs[VERTEX_ATTR])
    attr = attrs.new(name=VERTEX_ATTR, type='INT', domain='POINT')
    for i in range(len(obj.data.vertices)):
        attr.data[i].value = bone_index


def _bones_to_mesh_local(bones, mesh_origin_offset):
    ox, oy, oz = mesh_origin_offset
    return [
        {
            "id": b[0],
            "parent": b[1],
            "head": [b[2][0] - ox, b[2][1] - oy, b[2][2] - oz],
            "tail": [b[3][0] - ox, b[3][1] - oy, b[3][2] - oz],
        }
        for b in bones
    ]


def store_bone_metadata(obj, rig_type: str) -> None:
    """Store the bone hierarchy on the joined object as JSON in mesh-local coords."""
    if rig_type == 'HUMANOID':
        bones = _bones_to_mesh_local(HUMANOID_BONES, HUMANOID_MESH_ORIGIN_OFFSET)
    else:
        bones = []
    obj[META_PROP] = json.dumps(bones)
    obj[RIG_TYPE_PROP] = rig_type


def smart_voxel_remesh(obj) -> bool:
    """Voxel remesh while preserving the bone-id attribute via KDTree nearest-neighbour transfer.

    Returns True if the attribute existed and was transferred; False otherwise.
    """
    attrs = obj.data.attributes
    src_attr = attrs.get(VERTEX_ATTR)
    if src_attr is None:
        bpy.ops.object.voxel_remesh()
        return False

    snapshot = [
        (obj.data.vertices[i].co.copy(), src_attr.data[i].value)
        for i in range(len(obj.data.vertices))
    ]

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
        new_attr.data[i].value = snapshot[src_idx][1]
    return True


class SCULPTKIT_OT_generate_rig(Operator):
    bl_idname = "sculpt_kit.generate_rig"
    bl_label = "Generate Rig"
    bl_description = (
        "Build an armature and initial skin weights from preserved primitive bone "
        "metadata (Genesis-Tracked Rigging). Requires a SculptKit starter mesh"
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
        try:
            bone_data = json.loads(mesh_obj[META_PROP])
        except (KeyError, ValueError) as e:
            self.report({'ERROR'}, f"Bone metadata missing or corrupt: {e}")
            return {'CANCELLED'}
        if not bone_data:
            self.report({'ERROR'}, "No bone data on mesh")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        arm_data = bpy.data.armatures.new(f"{mesh_obj.name}_Armature")
        arm_obj = bpy.data.objects.new(f"{mesh_obj.name}_Armature", arm_data)
        context.collection.objects.link(arm_obj)
        arm_obj.matrix_world = mesh_obj.matrix_world.copy()

        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')

        bones = {}
        for b in bone_data:
            eb = arm_data.edit_bones.new(b["id"])
            eb.head = b["head"]
            eb.tail = b["tail"]
            bones[b["id"]] = eb
        for b in bone_data:
            if b["parent"]:
                child = bones[b["id"]]
                parent = bones[b["parent"]]
                child.parent = parent
                if (parent.tail - child.head).length < 0.001:
                    child.use_connect = True

        bpy.ops.object.mode_set(mode='OBJECT')

        bone_names = [b["id"] for b in bone_data]
        for name in bone_names:
            if name not in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups.new(name=name)

        attr = mesh_obj.data.attributes[VERTEX_ATTR]
        for vi in range(len(mesh_obj.data.vertices)):
            bi = attr.data[vi].value
            if 0 <= bi < len(bone_names):
                mesh_obj.vertex_groups[bone_names[bi]].add([vi], 1.0, 'REPLACE')

        mesh_obj.parent = arm_obj
        mesh_obj.matrix_parent_inverse = arm_obj.matrix_world.inverted()

        arm_mod = mesh_obj.modifiers.get("GTR Armature")
        if arm_mod is None:
            arm_mod = mesh_obj.modifiers.new(name="GTR Armature", type='ARMATURE')
        arm_mod.object = arm_obj
        arm_mod.use_vertex_groups = True
        arm_mod.use_bone_envelopes = False

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

        bpy.ops.object.select_all(action='DESELECT')
        arm_obj.select_set(True)
        mesh_obj.select_set(True)
        context.view_layer.objects.active = arm_obj

        self.report(
            {'INFO'},
            f"Generated rig '{arm_obj.name}' with {len(bone_data)} bones; mesh skinned.",
        )
        return {'FINISHED'}


_classes = (SCULPTKIT_OT_generate_rig,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
