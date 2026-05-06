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


def _add_quad_sphere(radius, location, scale=(1.0, 1.0, 1.0), subdivisions=4):
    """Cube-based quad sphere — uniform quad topology, no poles.

    Built by subdividing a cube N times then projecting verts to a sphere.
    The standard sculpting base mesh: brushes behave evenly across the entire
    surface, no pole-pinching, multires subdivides cleanly.

    subdivisions=4 gives 1536 faces / 1538 verts; level-1 subsurf in _finalize
    raises that to ~6144 faces — enough to sculpt a head on.
    """
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location)
    obj = bpy.context.active_object

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    for _ in range(subdivisions):
        bpy.ops.mesh.subdivide()
    bpy.ops.transform.tosphere(value=1.0)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Empirically, transform.tosphere(1.0) on a 4x-subdivided cube of size 2
    # produces radius ~1.28 (uses average distance, not max corner radius).
    # Scale so the user's `radius` parameter reflects actual world size.
    s = radius / 1.28
    obj.scale = (s * scale[0], s * scale[1], s * scale[2])
    return obj


def _join(active, *others):
    bpy.ops.object.select_all(action='DESELECT')
    active.select_set(True)
    for o in others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active
    bpy.ops.object.join()


def _finalize(obj, name, subsurf_levels=0):
    """Finalise a starter: rename, apply scale, shade smooth.

    subsurf_levels defaults to 0. Earlier versions added a level-1 Subsurf
    to Bust/Humanoid so the joined sphere primitives appeared visually
    fused, but that was deceptive — the primitives stay separate inside
    the joined mesh until Start Sculpt's voxel_remesh fuses them, and
    sculpting on a Subsurf-smoothed-but-not-fused mesh produced broken
    brush behaviour at primitive boundaries. The honest visual is now
    "starter is a cluster of spheres until you click Start Sculpt".
    """
    obj.name = name
    obj.data.name = name
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.shade_smooth()
    if subsurf_levels > 0:
        mod = obj.modifiers.new("Subsurf", 'SUBSURF')
        mod.levels = subsurf_levels


class PIPESCULPT_OT_starter_sphere(Operator):
    bl_idname = "pipe_sculpt.starter_sphere"
    bl_label = "Sphere"
    bl_description = "Add a quad-sphere (cube + tosphere) — uniform topology, no poles, ideal for sculpting"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        loc = context.scene.cursor.location.copy()
        obj = _add_quad_sphere(1.0, loc)
        _finalize(obj, "PipeSculpt_Sphere", subsurf_levels=0)
        return {'FINISHED'}


class PIPESCULPT_OT_starter_head(Operator):
    bl_idname = "pipe_sculpt.starter_head"
    bl_label = "Head"
    bl_description = (
        "Add an egg-shaped quad-sphere with GTR head tag. Generate Rig "
        "produces a 2-bone rig (root + head pivot). Use Bust if you also "
        "want jaw + ear bones"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        loc = context.scene.cursor.location.copy()
        obj = _add_quad_sphere(1.0, loc, scale=(0.85, 0.95, 1.1))
        # Tag the entire egg as 'head' so Generate Rig produces a single
        # head bone that follows the whole mesh. HEAD rig (root + head)
        # is for portrait sculpts where you want a pivot, not a full face rig.
        rigging.tag_primitive(obj, "head")
        rigging.store_bone_metadata(obj, 'HEAD')
        _finalize(obj, "PipeSculpt_Head", subsurf_levels=0)
        return {'FINISHED'}


class PIPESCULPT_OT_starter_bust(Operator):
    bl_idname = "pipe_sculpt.starter_bust"
    bl_label = "Bust"
    bl_description = (
        "Add a head + neck + shoulder block with GTR tags. Voxel remesh fuses "
        "the parts on Start Sculpt; Generate Rig builds 7 bones (root, spine, "
        "neck, head, jaw, ears) for portrait animation"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location

        head = _add_sphere(0.18, (cx, cy, cz + 0.78), scale=(0.85, 0.95, 1.10))
        rigging.tag_primitive(head, "head")
        neck = _add_sphere(0.07, (cx, cy, cz + 0.52))
        rigging.tag_primitive(neck, "neck")
        shoulders = _add_sphere(0.32, (cx, cy, cz + 0.10), scale=(1.60, 1.00, 0.80))
        rigging.tag_primitive(shoulders, "spine")

        parts = [head, neck, shoulders]

        # Sub-voxel anchors for jaw + ears — invisible bumps that exist only
        # to give the corresponding bones their vertex-group weights post
        # voxel-remesh. User sculpts the actual jawline / ears manually.
        jaw_anchor = _add_sphere(0.025, (cx, cy + 0.040, cz + 0.71))
        rigging.tag_primitive(jaw_anchor, "jaw")
        parts.append(jaw_anchor)

        for side, suffix in ((1, "L"), (-1, "R")):
            ear = _add_sphere(
                0.018, (cx + side * 0.135, cy - 0.02, cz + 0.78),
                scale=(0.8, 1.0, 1.0),
            )
            rigging.tag_primitive(ear, f"ear.{suffix}")
            parts.append(ear)

        _join(head, *(p for p in parts if p is not head))
        rigging.store_bone_metadata(head, 'BUST')
        _finalize(head, "PipeSculpt_Bust")
        return {'FINISHED'}


class PIPESCULPT_OT_starter_humanoid(Operator):
    bl_idname = "pipe_sculpt.starter_humanoid"
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

        # ========== JOINT LANDMARKS ==========
        # Only landmarks tagged with a DIFFERENT bone than their parent torso /
        # pelvis remain — they actually contribute to rig deformation. Pec and
        # hip-bump primitives were tagged "spine"/"pelvis" (same as parent), so
        # removing them costs nothing rig-wise but eliminates the breast-shaped
        # bumps on the chest at fine voxel sizes.
        for side, suffix in ((1, "L"), (-1, "R")):
            # Deltoid (shoulder cap) — tagged upper_arm.L/R (own bone)
            deltoid = _add_sphere(
                0.07, (cx + side * 0.30, cy, cz + 0.43), scale=(1.0, 1.1, 0.7)
            )
            rigging.tag_primitive(deltoid, f"upper_arm.{suffix}")

            # Kneecap (patella) — tagged lower_leg.L/R, anatomical knee bump
            kneecap = _add_sphere(
                0.05, (cx + side * 0.11, cy + 0.10, cz - 0.62), scale=(1.0, 0.6, 1.2)
            )
            rigging.tag_primitive(kneecap, f"lower_leg.{suffix}")

            # Calf muscle (gastrocnemius) — back of lower leg
            calf = _add_sphere(
                0.06, (cx + side * 0.11, cy - 0.08, cz - 0.85), scale=(1.0, 1.0, 1.5)
            )
            rigging.tag_primitive(calf, f"lower_leg.{suffix}")

            parts.extend([deltoid, kneecap, calf])

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
        _finalize(torso, "PipeSculpt_Humanoid")
        return {'FINISHED'}


class PIPESCULPT_OT_starter_quadruped(Operator):
    bl_idname = "pipe_sculpt.starter_quadruped"
    bl_label = "Quadruped"
    bl_description = (
        "Add a four-legged animal block (dog/wolf-like proportions). Voxel "
        "remesh fuses parts on Start Sculpt; Generate Rig builds 17 bones "
        "(spine, neck, head, tail, 4 legs × 3 segments)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location
        # Mesh origin will land on torso center (cx, cy, cz + 0.50).
        # All primitive locations use absolute cursor coords.
        z_body = cz + 0.50  # back center

        # Body — elongated spine block running along Y
        torso = _add_sphere(0.18, (cx, cy + 0.0, z_body), scale=(1.0, 3.0, 1.0))
        rigging.tag_primitive(torso, "spine")
        parts = [torso]

        # Neck + head, sloping up and forward
        neck = _add_sphere(0.07, (cx, cy + 0.35, z_body + 0.05))
        rigging.tag_primitive(neck, "neck")
        parts.append(neck)
        head = _add_sphere(0.10, (cx, cy + 0.48, z_body + 0.10), scale=(1.0, 1.4, 1.0))
        rigging.tag_primitive(head, "head")
        parts.append(head)

        # Tail trailing back-down
        tail = _add_sphere(0.05, (cx, cy - 0.42, z_body - 0.05), scale=(1.0, 2.5, 1.0))
        rigging.tag_primitive(tail, "tail")
        parts.append(tail)

        # Four legs — front pair forward, back pair behind
        for side, suffix in ((1, "L"), (-1, "R")):
            x = cx + side * 0.10
            # Front leg
            fu = _add_sphere(0.05, (x, cy + 0.30, z_body - 0.10), scale=(1.0, 1.0, 2.5))
            rigging.tag_primitive(fu, f"foreleg_upper.{suffix}")
            fl = _add_sphere(0.04, (x, cy + 0.30, z_body - 0.32), scale=(1.0, 1.0, 2.0))
            rigging.tag_primitive(fl, f"foreleg_lower.{suffix}")
            fp = _add_sphere(0.05, (x, cy + 0.34, z_body - 0.48), scale=(1.0, 1.5, 0.6))
            rigging.tag_primitive(fp, f"forepaw.{suffix}")
            # Back leg
            hu = _add_sphere(0.06, (x, cy - 0.30, z_body - 0.10), scale=(1.0, 1.0, 2.5))
            rigging.tag_primitive(hu, f"hindleg_upper.{suffix}")
            hl = _add_sphere(0.04, (x, cy - 0.30, z_body - 0.32), scale=(1.0, 1.0, 2.0))
            rigging.tag_primitive(hl, f"hindleg_lower.{suffix}")
            hp = _add_sphere(0.05, (x, cy - 0.26, z_body - 0.48), scale=(1.0, 1.5, 0.6))
            rigging.tag_primitive(hp, f"hindpaw.{suffix}")
            parts.extend([fu, fl, fp, hu, hl, hp])

        _join(torso, *(p for p in parts if p is not torso))
        rigging.store_bone_metadata(torso, 'QUADRUPED')
        _finalize(torso, "PipeSculpt_Quadruped")
        return {'FINISHED'}


class PIPESCULPT_OT_starter_bird(Operator):
    bl_idname = "pipe_sculpt.starter_bird"
    bl_label = "Bird"
    bl_description = (
        "Add a bird block with spread wings. Voxel remesh fuses parts on "
        "Start Sculpt; Generate Rig builds 16 bones (spine, neck, head, "
        "beak, tail, 2 wings × 3 segments, 2 legs × 2 segments)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location
        z_body = cz + 0.30  # body center, scaled smaller than mammal

        # Compact ovoid body
        torso = _add_sphere(0.10, (cx, cy + 0.0, z_body), scale=(1.0, 1.8, 1.0))
        rigging.tag_primitive(torso, "spine")
        parts = [torso]

        neck = _add_sphere(0.04, (cx, cy + 0.13, z_body + 0.02))
        rigging.tag_primitive(neck, "neck")
        parts.append(neck)
        head = _add_sphere(0.05, (cx, cy + 0.18, z_body + 0.05))
        rigging.tag_primitive(head, "head")
        parts.append(head)
        beak = _add_sphere(0.025, (cx, cy + 0.24, z_body + 0.04), scale=(0.7, 1.5, 0.7))
        rigging.tag_primitive(beak, "beak")
        parts.append(beak)

        tail = _add_sphere(0.04, (cx, cy - 0.18, z_body), scale=(1.5, 2.0, 0.4))
        rigging.tag_primitive(tail, "tail")
        parts.append(tail)

        # Wings — spread sideways along X, three segments each
        for side, suffix in ((1, "L"), (-1, "R")):
            wu = _add_sphere(0.04, (cx + side * 0.13, cy + 0.05, z_body + 0.05), scale=(2.0, 1.0, 0.6))
            rigging.tag_primitive(wu, f"wing_upper.{suffix}")
            wl = _add_sphere(0.035, (cx + side * 0.27, cy + 0.05, z_body + 0.05), scale=(2.0, 1.0, 0.5))
            rigging.tag_primitive(wl, f"wing_lower.{suffix}")
            wt = _add_sphere(0.025, (cx + side * 0.40, cy + 0.05, z_body + 0.05), scale=(1.5, 1.0, 0.4))
            rigging.tag_primitive(wt, f"wingtip.{suffix}")
            parts.extend([wu, wl, wt])

        # Legs — short, two segments
        for side, suffix in ((1, "L"), (-1, "R")):
            x = cx + side * 0.04
            lu = _add_sphere(0.025, (x, cy - 0.05, z_body - 0.10), scale=(1.0, 1.0, 2.0))
            rigging.tag_primitive(lu, f"bird_leg_upper.{suffix}")
            ll = _add_sphere(0.020, (x, cy - 0.05, z_body - 0.25), scale=(1.0, 1.0, 2.0))
            rigging.tag_primitive(ll, f"bird_leg_lower.{suffix}")
            parts.extend([lu, ll])

        _join(torso, *(p for p in parts if p is not torso))
        rigging.store_bone_metadata(torso, 'BIRD')
        _finalize(torso, "PipeSculpt_Bird")
        return {'FINISHED'}


class PIPESCULPT_OT_starter_mech(Operator):
    bl_idname = "pipe_sculpt.starter_mech"
    bl_label = "Mech"
    bl_description = (
        "Add a humanoid robot block — like Humanoid but no fingers, jaw, "
        "ears, or clavicle wrap. Generate Rig builds 17 bones (spine + "
        "head + 4 limb segments × 4 limbs) + 8 IK control bones"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _enter_object_mode(context)
        cx, cy, cz = context.scene.cursor.location
        # Same coordinate system as Humanoid (mesh origin = torso = cz + 0.20)

        # Head, neck, torso, pelvis — block-like, no facial detail
        head_block = _add_sphere(0.13, (cx, cy, cz + 0.84), scale=(0.85, 0.85, 1.0))
        rigging.tag_primitive(head_block, "head")
        neck = _add_sphere(0.07, (cx, cy, cz + 0.55))
        rigging.tag_primitive(neck, "neck")
        torso = _add_sphere(0.275, (cx, cy, cz + 0.20), scale=(1.10, 0.70, 1.40))
        rigging.tag_primitive(torso, "spine")
        pelvis = _add_sphere(0.21, (cx, cy, cz - 0.25), scale=(1.05, 0.85, 0.80))
        rigging.tag_primitive(pelvis, "pelvis")
        parts = [head_block, neck, torso, pelvis]

        # Arms — no clavicle, rigid shoulder
        for side, suffix in ((1, "L"), (-1, "R")):
            ua = _add_sphere(0.075, (cx + side * 0.50, cy, cz + 0.40), scale=(3.0, 1.0, 1.0))
            rigging.tag_primitive(ua, f"upper_arm.{suffix}")
            fa = _add_sphere(0.065, (cx + side * 0.875, cy, cz + 0.40), scale=(3.0, 1.0, 1.0))
            rigging.tag_primitive(fa, f"forearm.{suffix}")
            hand = _add_sphere(0.06, (cx + side * 1.13, cy, cz + 0.40), scale=(1.5, 1.0, 0.8))
            rigging.tag_primitive(hand, f"hand.{suffix}")
            parts.extend([ua, fa, hand])

        # Legs — same structure as Humanoid but no toes
        for side, suffix in ((1, "L"), (-1, "R")):
            x = cx + side * 0.11
            ul = _add_sphere(0.10, (x, cy, cz - 0.40), scale=(1.0, 1.0, 3.5))
            rigging.tag_primitive(ul, f"upper_leg.{suffix}")
            ll = _add_sphere(0.085, (x, cy, cz - 0.875), scale=(1.0, 1.0, 2.88))
            rigging.tag_primitive(ll, f"lower_leg.{suffix}")
            foot = _add_sphere(0.08, (x, cy + 0.08, cz - 1.10), scale=(0.85, 1.8, 0.6))
            rigging.tag_primitive(foot, f"foot.{suffix}")
            parts.extend([ul, ll, foot])

        _join(torso, *(p for p in parts if p is not torso))
        rigging.store_bone_metadata(torso, 'MECH')
        _finalize(torso, "PipeSculpt_Mech")
        return {'FINISHED'}


class PIPESCULPT_PT_starters(Panel):
    bl_idname = "PIPESCULPT_PT_starters"
    bl_label = "Starter Meshes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 0

    def draw(self, context):
        layout = self.layout
        layout.label(text="Adds at 3D cursor location", icon='PIVOT_CURSOR')

        layout.label(text="Generic")
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        grid.scale_y = 1.3
        grid.operator("pipe_sculpt.starter_sphere", icon='SPHERE')
        grid.operator("pipe_sculpt.starter_head", icon='USER')

        layout.label(text="Tagged (GTR — Generate Rig works)")
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        grid.scale_y = 1.3
        grid.operator("pipe_sculpt.starter_bust", icon='OUTLINER_OB_ARMATURE')
        grid.operator("pipe_sculpt.starter_humanoid", icon='ARMATURE_DATA')
        grid.operator("pipe_sculpt.starter_quadruped", icon='ANIM_DATA')
        grid.operator("pipe_sculpt.starter_bird", icon='FORCE_WIND')
        grid.operator("pipe_sculpt.starter_mech", icon='MOD_ARMATURE')


_classes = (
    PIPESCULPT_OT_starter_sphere,
    PIPESCULPT_OT_starter_head,
    PIPESCULPT_OT_starter_bust,
    PIPESCULPT_OT_starter_humanoid,
    PIPESCULPT_OT_starter_quadruped,
    PIPESCULPT_OT_starter_bird,
    PIPESCULPT_OT_starter_mech,
    PIPESCULPT_PT_starters,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
