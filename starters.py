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

        # Head — kept simple: cranium + jaw mass, with sub-voxel ear anchors
        # so the ear bones still get vertex weights without producing visible
        # ear-shaped bumps. Nose, brow, cheekbones removed: at fine voxel they
        # showed as discrete primitives ("doll-face artefacts") rather than
        # natural face features. Sculptor adds these manually.
        cranium = _add_sphere(0.14, (cx, cy, cz + 0.84), scale=(0.85, 0.95, 1.0))
        rigging.tag_primitive(cranium, "head")
        jaw_mass = _add_sphere(
            0.09, (cx, cy + 0.04, cz + 0.66), scale=(0.85, 1.15, 0.75)
        )
        rigging.tag_primitive(jaw_mass, "jaw")

        neck = _add_sphere(0.075, (cx, cy, cz + 0.55))
        rigging.tag_primitive(neck, "neck")
        torso = _add_sphere(0.275, (cx, cy, cz + 0.20), scale=(1.10, 0.70, 1.40))
        rigging.tag_primitive(torso, "spine")
        pelvis = _add_sphere(0.21, (cx, cy, cz - 0.25), scale=(1.05, 0.85, 0.80))
        rigging.tag_primitive(pelvis, "pelvis")

        parts = [cranium, jaw_mass, neck, torso, pelvis]

        # Sub-voxel ear anchors — invisible bumps that exist only to give the
        # ear.L/.R bones vertex-group weights. User sculpts the actual ears.
        for side, suffix in ((1, "L"), (-1, "R")):
            ear = _add_sphere(
                0.018, (cx + side * 0.118, cy - 0.02, cz + 0.78),
                scale=(0.8, 1.0, 1.0),
            )
            rigging.tag_primitive(ear, f"ear.{suffix}")
            parts.append(ear)

        shoulder_z = 0.40
        for side, suffix in ((1, "L"), (-1, "R")):
            # Subtle elongated bump along the bone direction so it reads as a
            # collar-bone ridge rather than a sphere lump on the neck.
            clavicle = _add_sphere(
                0.040, (cx + side * 0.15, cy, cz + 0.475), scale=(1.4, 0.8, 0.6)
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

        # ========== ANATOMICAL LANDMARKS ==========
        # Subtle bumps that protrude only ~1 voxel beyond the parent surface,
        # so they read as smooth muscle hints — not as distinct primitive plates.
        # Sternum + navel are skipped intentionally; at the new fine voxel scale
        # they showed as clearly-defined primitives, which sculptors prefer to
        # add manually.

        for side, suffix in ((1, "L"), (-1, "R")):
            # Pectoral major hint — pushed deep into torso so only ~1 cm protrudes.
            pec = _add_sphere(
                0.05, (cx + side * 0.13, cy + 0.18, cz + 0.30), scale=(1.8, 0.25, 1.0)
            )
            rigging.tag_primitive(pec, "spine")

            # Iliac crest — subtle hip-bone bump on pelvis.
            hip_bump = _add_sphere(
                0.040, (cx + side * 0.18, cy + 0.07, cz - 0.10), scale=(1.0, 1.0, 1.0)
            )
            rigging.tag_primitive(hip_bump, "pelvis")

            # Deltoid (shoulder cap) — slimmed to read as muscle, not pad
            deltoid = _add_sphere(
                0.07, (cx + side * 0.30, cy, cz + 0.43), scale=(1.0, 1.1, 0.7)
            )
            rigging.tag_primitive(deltoid, f"upper_arm.{suffix}")

            # Kneecap (patella)
            kneecap = _add_sphere(
                0.05, (cx + side * 0.11, cy + 0.10, cz - 0.62), scale=(1.0, 0.6, 1.2)
            )
            rigging.tag_primitive(kneecap, f"lower_leg.{suffix}")

            # Calf muscle (gastrocnemius) — bumps on back of lower leg
            calf = _add_sphere(
                0.06, (cx + side * 0.11, cy - 0.08, cz - 0.85), scale=(1.0, 1.0, 1.5)
            )
            rigging.tag_primitive(calf, f"lower_leg.{suffix}")

            parts.extend([pec, hip_bump, deltoid, kneecap, calf])

        # ========== FINGERS ==========
        # 5 fingers x 3 phalanges per hand = 30 finger primitives.
        # Each phalanx is a small sphere tagged with its own bone for individual
        # finger animation. They overlap so voxel remesh fuses fingers + hand
        # into one continuous mesh.
        for suffix, side in (("L", 1), ("R", -1)):
            for finger, y in rigging.FINGER_Y_OFFSETS.items():
                for i in range(1, 4):
                    cx_x = side * (
                        rigging.FINGER_KNUCKLE_X
                        + (i - 0.5) * rigging.FINGER_PHALANX_LENGTH
                    )
                    # Uniform radius so every phalanx survives voxel remesh
                    phalanx = _add_sphere(
                        0.022, (cx + cx_x, cy + y, cz + 0.40)
                    )
                    rigging.tag_primitive(
                        phalanx, rigging._finger_bone_name(finger, i, suffix)
                    )
                    parts.append(phalanx)

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
