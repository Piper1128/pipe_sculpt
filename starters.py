import bpy
from bpy.types import Operator, Panel

from . import rigging


def _enter_object_mode(context):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def _add_sphere(radius, location, scale=(1.0, 1.0, 1.0), segments=32, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments, ring_count=rings, radius=radius, location=location
    )
    obj = bpy.context.active_object
    obj.scale = scale
    return obj


def _join(active, *others):
    bpy.ops.object.select_all(action='DESELECT')
    active.select_set(True)
    for o in others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.ops.object.join()


def _finalize(obj, name):
    obj.name = name
    obj.data.name = name
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.shade_smooth()
    mod = obj.modifiers.new("Subsurf", 'SUBSURF')
    mod.levels = 1


class SCULPTKIT_OT_starter_sphere(Operator):
    bl_idname = "sculpt_kit.starter_sphere"
    bl_label = "Sphere"
    bl_description = "Add a subdivided UV sphere — universal block-out starter"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        loc = context.scene.cursor.location.copy()
        obj = _add_sphere(1.0, loc)
        _finalize(obj, "SculptKit_Sphere")
        return {'FINISHED'}


class SCULPTKIT_OT_starter_head(Operator):
    bl_idname = "sculpt_kit.starter_head"
    bl_label = "Head"
    bl_description = "Add an egg-shaped block ready for face sculpting"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        loc = context.scene.cursor.location.copy()
        obj = _add_sphere(1.0, loc, scale=(0.85, 0.95, 1.1))
        _finalize(obj, "SculptKit_Head")
        return {'FINISHED'}


class SCULPTKIT_OT_starter_bust(Operator):
    bl_idname = "sculpt_kit.starter_bust"
    bl_label = "Bust"
    bl_description = "Add a head + neck + shoulder block — voxel remesh fuses them when you Start Sculpt"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location

        head = _add_sphere(0.18, (cx, cy, cz + 0.78), scale=(0.85, 0.95, 1.10))
        neck = _add_sphere(0.07, (cx, cy, cz + 0.52))
        shoulders = _add_sphere(0.32, (cx, cy, cz + 0.10), scale=(1.60, 1.00, 0.80))

        _join(head, neck, shoulders)
        _finalize(head, "SculptKit_Bust")
        return {'FINISHED'}


class SCULPTKIT_OT_starter_humanoid(Operator):
    bl_idname = "sculpt_kit.starter_humanoid"
    bl_label = "Humanoid"
    bl_description = "Add a T-posed full-body humanoid block (arms outstretched) — voxel remesh fuses parts when you Start Sculpt; T-pose keeps arms separated from torso"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location

        head = _add_sphere(0.16, (cx, cy, cz + 0.78), scale=(0.85, 0.95, 1.10))
        rigging.tag_primitive(head, "head")
        neck = _add_sphere(0.075, (cx, cy, cz + 0.55))
        rigging.tag_primitive(neck, "neck")
        torso = _add_sphere(0.275, (cx, cy, cz + 0.20), scale=(1.10, 0.70, 1.40))
        rigging.tag_primitive(torso, "spine")
        pelvis = _add_sphere(0.21, (cx, cy, cz - 0.25), scale=(1.05, 0.85, 0.80))
        rigging.tag_primitive(pelvis, "pelvis")

        parts = [head, neck, torso, pelvis]

        shoulder_z = 0.40
        for side, suffix in ((1, "L"), (-1, "R")):
            clavicle = _add_sphere(
                0.06, (cx + side * 0.15, cy, cz + 0.475)
            )
            rigging.tag_primitive(clavicle, f"clavicle.{suffix}")
            upper_arm = _add_sphere(
                0.075, (cx + side * 0.475, cy, cz + shoulder_z), scale=(3.67, 1.0, 1.0)
            )
            rigging.tag_primitive(upper_arm, f"upper_arm.{suffix}")
            forearm = _add_sphere(
                0.065, (cx + side * 0.875, cy, cz + shoulder_z), scale=(3.46, 1.0, 1.0)
            )
            rigging.tag_primitive(forearm, f"forearm.{suffix}")
            hand = _add_sphere(
                0.05, (cx + side * 1.10, cy, cz + shoulder_z), scale=(2.0, 1.0, 0.4)
            )
            rigging.tag_primitive(hand, f"hand.{suffix}")
            parts.extend([clavicle, upper_arm, forearm, hand])

        for side, suffix in ((1, "L"), (-1, "R")):
            x_leg = side * 0.11
            thigh = _add_sphere(
                0.10, (cx + x_leg, cy, cz - 0.40), scale=(1.0, 1.0, 3.5)
            )
            rigging.tag_primitive(thigh, f"upper_leg.{suffix}")
            shin = _add_sphere(
                0.085, (cx + x_leg, cy, cz - 0.875), scale=(1.0, 1.0, 2.88)
            )
            rigging.tag_primitive(shin, f"lower_leg.{suffix}")
            foot = _add_sphere(
                0.075, (cx + x_leg, cy + 0.08, cz - 1.10), scale=(0.85, 1.8, 0.6)
            )
            rigging.tag_primitive(foot, f"foot.{suffix}")
            toes = _add_sphere(
                0.04, (cx + x_leg, cy + 0.25, cz - 1.10), scale=(1.5, 1.5, 0.5)
            )
            rigging.tag_primitive(toes, f"toes.{suffix}")
            parts.extend([thigh, shin, foot, toes])

        _join(torso, *(p for p in parts if p is not torso))
        rigging.store_bone_metadata(torso, 'HUMANOID')
        _finalize(torso, "SculptKit_Humanoid")
        return {'FINISHED'}


class SCULPTKIT_PT_starters(Panel):
    bl_idname = "SCULPTKIT_PT_starters"
    bl_label = "Starter Meshes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "SculptKit"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.label(text="Adds at 3D cursor location", icon='PIVOT_CURSOR')
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        grid.scale_y = 1.3
        grid.operator("sculpt_kit.starter_sphere", icon='SPHERE')
        grid.operator("sculpt_kit.starter_head", icon='USER')
        grid.operator("sculpt_kit.starter_bust", icon='OUTLINER_OB_ARMATURE')
        grid.operator("sculpt_kit.starter_humanoid", icon='ARMATURE_DATA')


_classes = (
    SCULPTKIT_OT_starter_sphere,
    SCULPTKIT_OT_starter_head,
    SCULPTKIT_OT_starter_bust,
    SCULPTKIT_OT_starter_humanoid,
    SCULPTKIT_PT_starters,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
