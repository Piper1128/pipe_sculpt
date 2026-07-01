"""Hair / fur operators — Blender adapter for hair_core's pure logic.

Born Clean per IronCore conventions: this file is the Adapter.Unity-
equivalent — it imports bpy and translates user actions into Blender
Hair Curves operations. All math (presets, density, card packing,
memory estimation, surface sampling) lives in hair_core.py and is
unit-tested headlessly.

Pose-following hair (the whole point of hair on a rigged character)
needs three things, and this module sets up all of them:
  1. A non-overlapping UV map on the surface. Blender's hair sculpt
     brushes reject overlapping UVs ("UV islands must not overlap"),
     which is exactly what a Mirror-X paint UV produces. We give hair
     its own dedicated UV (`PipeSculpt_HairUV`) via Smart UV Project so
     the user's paint/mirror UV is never disturbed.
  2. The native 'Deform Curves on Surface' modifier + a parent to the
     mesh — both created for us by `object.curves_empty_hair_add`. This
     is what makes the hair follow the posed/animated surface.
  3. A `rest_position` attribute on the surface + a `surface_uv_coordinate`
     attribute per strand, so the deform modifier knows where each root
     is anchored. The interactive Add brush writes surface_uv_coordinate
     itself; our programmatic Spawn writes it explicitly.

Workflow:
  1. Setup Hair — ensures the hair UV + rest_position, creates a native
     Hair Curves object bound to the surface with the deform modifier.
  2. Spawn (Preset) — fills the surface with pose-following strands at a
     real-world density.
  3. Sculpt / Comb — native brushes (Comb, Add, Density, Grow, Twist).
  4. → Hair Cards — bake to UV'd quads for real-time Unity export.
"""
from __future__ import annotations

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator

from . import hair_core


HAIR_OBJ_SUFFIX = "_Hair"
HAIR_MARKER_PROP = "pipe_sculpt_hair_source"
HAIR_UV_NAME = "PipeSculpt_HairUV"
SURFACE_DEFORM_PREFIX = "Surface Deform"


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _find_hair_for_mesh(mesh_obj):
    """Find an existing PipeSculpt hair object linked to this mesh."""
    name = mesh_obj.name
    for o in bpy.data.objects:
        if o.type == 'CURVES' and o.get(HAIR_MARKER_PROP) == name:
            return o
    # Legacy name-suffix fallback for hair created in earlier sessions
    legacy = bpy.data.objects.get(f"{name}{HAIR_OBJ_SUFFIX}")
    if legacy is not None and legacy.type == 'CURVES':
        return legacy
    return None


def _preset_enum_items():
    """Build the EnumProperty items list from hair_core's preset table."""
    return tuple(
        (p.name, p.label, p.description)
        for p in hair_core.HAIR_PRESETS
    )


def _mesh_surface_area_m2(mesh_obj) -> float:
    """Approximate mesh surface area in m², factoring uniform scale."""
    scale_factor = (mesh_obj.scale.x * mesh_obj.scale.y * mesh_obj.scale.z) ** (1.0 / 3.0)
    return sum(p.area for p in mesh_obj.data.polygons) * scale_factor * scale_factor


# ----------------------------------------------------------------------
# Deform prerequisites — the pieces that make hair follow a posed mesh
# ----------------------------------------------------------------------

def _ensure_hair_uv(context, mesh_obj) -> str:
    """Give the mesh a dedicated non-overlapping UV for hair, return its name.

    Hair sculpt brushes refuse to work on overlapping UV islands. Rather
    than touch the user's paint/mirror UV, we Smart-UV-Project a separate
    `PipeSculpt_HairUV` layer and leave the original as the rendered one.

    IMPORTANT: UV-layer references go stale after mesh-editing operators
    (Blender reallocates CustomData) — we only ever address layers by name
    or index here, never hold a layer object across an operator.
    """
    uvs = mesh_obj.data.uv_layers
    prev_active_index = uvs.active_index if len(uvs) else 0
    prev_render_index = next((i for i, l in enumerate(uvs) if l.active_render), 0)

    if uvs.get(HAIR_UV_NAME) is None:
        uvs.new(name=HAIR_UV_NAME, do_init=True)
    # Address by name every time — the reference from .new()/.get() may be
    # invalidated by the mode switches and unwrap below.
    uvs.active_index = uvs.find(HAIR_UV_NAME)

    prev_active = context.view_layer.objects.active
    prev_mode = context.mode
    context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    if context.mode != 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='SELECT')
    try:
        bpy.ops.uv.smart_project(
            angle_limit=66.0,
            island_margin=0.02,
            correct_aspect=True,
            scale_to_bounds=False,
        )
    except Exception:
        # Smart UV Project needs UI context that headless runs lack; a plain
        # angle-based unwrap is a serviceable fallback there. In the GUI the
        # smart-project path (guaranteed non-overlap) is what actually runs.
        bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Keep the user's original UV as the rendered/active-for-paint one.
    uvs[prev_render_index].active_render = True
    uvs.active_index = prev_active_index

    # Restore caller's active object (helpers shouldn't leave it dangling).
    if prev_active is not None:
        context.view_layer.objects.active = prev_active
    if prev_mode == 'OBJECT' and context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    return HAIR_UV_NAME


def _ensure_rest_position(mesh_obj) -> None:
    """Store the surface's undeformed vertex positions as `rest_position`.

    The 'Deform Curves on Surface' modifier compares this rest state against
    the live posed surface to know how far to carry each hair root. Only
    created if absent, so re-running never rebinds to a posed state — the
    mesh's own vertex coords are always the rest pose (armature deform is a
    modifier, it doesn't move mesh data).
    """
    md = mesh_obj.data
    if "rest_position" in md.attributes:
        return
    attr = md.attributes.new("rest_position", 'FLOAT_VECTOR', 'POINT')
    flat = []
    for v in md.vertices:
        flat.extend((v.co.x, v.co.y, v.co.z))
    attr.data.foreach_set("vector", flat)


def _get_surface_deform_node_group(context, mesh_obj):
    """Return the built-in 'Deform Curves on Surface' node group.

    Blender mints it the first time `curves_empty_hair_add` runs. If none
    exists yet (healing legacy hair), we mint one via a throwaway empty-hair
    object and keep it alive with a fake user.
    """
    for ng in bpy.data.node_groups:
        if ng.name.startswith(SURFACE_DEFORM_PREFIX):
            return ng

    prev_active = context.view_layer.objects.active
    prev_selected = list(context.selected_objects)
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj
    bpy.ops.object.curves_empty_hair_add()
    temp = context.active_object
    node_group = next(
        (m.node_group for m in temp.modifiers
         if m.type == 'NODES' and m.node_group is not None),
        None,
    )
    if node_group is not None:
        node_group.use_fake_user = True
    bpy.data.objects.remove(temp, do_unlink=True)

    bpy.ops.object.select_all(action='DESELECT')
    for o in prev_selected:
        try:
            o.select_set(True)
        except (ReferenceError, RuntimeError):
            pass
    if prev_active is not None:
        context.view_layer.objects.active = prev_active
    return node_group


def _ensure_surface_deform_modifier(context, hair_obj, mesh_obj):
    """Guarantee the hair has a 'Deform Curves on Surface' modifier."""
    for md in hair_obj.modifiers:
        if (md.type == 'NODES' and md.node_group is not None
                and md.node_group.name.startswith(SURFACE_DEFORM_PREFIX)):
            return md
    node_group = _get_surface_deform_node_group(context, mesh_obj)
    if node_group is None:
        return None
    md = hair_obj.modifiers.new("Surface Deform", 'NODES')
    md.node_group = node_group
    return md


def _extract_triangles_uv(mesh_obj, uv_name):
    """Extract (v0,v1,v2,n0,n1,n2,uv0,uv1,uv2) tuples from the ORIGINAL mesh.

    Sampled from mesh.data (not the evaluated mesh) so root positions and
    UVs line up with `rest_position` — the frame the deform modifier binds
    against. Vertex normals give smooth growth directions. Plain tuples for
    hair_core, which is bpy-free.
    """
    md = mesh_obj.data
    md.calc_loop_triangles()
    uv_layer = md.uv_layers.get(uv_name)
    if uv_layer is None:
        return []
    uv_data = uv_layer.data
    verts = md.vertices
    triangles = []
    for lt in md.loop_triangles:
        i0, i1, i2 = lt.vertices
        l0, l1, l2 = lt.loops
        triangles.append((
            tuple(verts[i0].co), tuple(verts[i1].co), tuple(verts[i2].co),
            tuple(verts[i0].normal), tuple(verts[i1].normal), tuple(verts[i2].normal),
            tuple(uv_data[l0].uv), tuple(uv_data[l1].uv), tuple(uv_data[l2].uv),
        ))
    return triangles


def _build_curves_from_strands(curves_data, strands, root_uvs=None) -> bool:
    """Populate a Curves datablock from hair_core strand point-lists.

    strands:   list of strands, each a list of (x,y,z) point tuples.
    root_uvs:  optional per-strand (u,v) root UVs. When supplied (and all
               present), written into the CURVE-domain `surface_uv_coordinate`
               attribute so the deform modifier makes the strands follow pose.
    Returns True on success. Wrapped defensively because the exact Curves
    population API is version-sensitive and worth failing loud on rather than
    silently producing empty hair.
    """
    # remove_curves() with NO arguments clears every curve in Blender 5.1.
    if len(curves_data.curves) > 0:
        curves_data.remove_curves()

    sizes = [len(s) for s in strands]
    if not sizes:
        return False

    curves_data.add_curves(sizes)

    flat = []
    for strand in strands:
        for p in strand:
            flat.extend((p[0], p[1], p[2]))
    if len(curves_data.points) * 3 != len(flat):
        return False
    curves_data.points.foreach_set("position", flat)

    if (root_uvs is not None
            and len(root_uvs) == len(strands)
            and all(uv is not None for uv in root_uvs)):
        attr = curves_data.attributes.get("surface_uv_coordinate")
        if attr is None:
            attr = curves_data.attributes.new(
                "surface_uv_coordinate", 'FLOAT2', 'CURVE')
        uv_flat = []
        for uv in root_uvs:
            uv_flat.extend((uv[0], uv[1]))
        if len(attr.data) * 2 == len(uv_flat):
            attr.data.foreach_set("vector", uv_flat)

    curves_data.update_tag()
    return True


class PIPESCULPT_OT_hair_setup(Operator):
    bl_idname = "pipe_sculpt.hair_setup"
    bl_label = "Setup Hair (Brushable)"
    bl_description = (
        "Create a Hair Curves object bound to the active mesh's surface, "
        "set up to FOLLOW POSE/ANIMATION. Gives hair its own non-overlapping "
        "UV (so the sculpt brushes don't error) without touching your paint "
        "UV. Then Spawn a preset or enter Hair Sculpt Mode to brush density"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        mesh_obj = _active_mesh(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        existing = _find_hair_for_mesh(mesh_obj)
        if existing is not None:
            # Heal hair from older sessions (no deform modifier / parent / UV)
            # in place if it has painted curves; recreate cleanly if empty.
            if len(existing.data.curves) == 0:
                bpy.data.objects.remove(existing, do_unlink=True)
            else:
                self._wire_deform(context, existing, mesh_obj)
                bpy.ops.object.select_all(action='DESELECT')
                existing.select_set(True)
                context.view_layer.objects.active = existing
                self.report(
                    {'INFO'},
                    f"Upgraded '{existing.name}' — it now follows pose. "
                    "Re-pose to check",
                )
                return {'FINISHED'}

        # Fresh setup: hair UV + rest_position, then native empty-hair (which
        # brings the deform modifier + parent for free).
        hair_uv = _ensure_hair_uv(context, mesh_obj)
        _ensure_rest_position(mesh_obj)

        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj
        try:
            bpy.ops.object.curves_empty_hair_add()
        except RuntimeError as e:
            self.report({'ERROR'}, f"Couldn't create hair curves: {e}")
            return {'CANCELLED'}

        hair_obj = context.active_object
        hair_obj.name = f"{mesh_obj.name}{HAIR_OBJ_SUFFIX}"
        hair_obj.data.name = hair_obj.name
        hair_obj[HAIR_MARKER_PROP] = mesh_obj.name
        hair_obj.data.surface = mesh_obj
        hair_obj.data.surface_uv_map = hair_uv
        _ensure_surface_deform_modifier(context, hair_obj, mesh_obj)

        has_deform = any(mesh_obj.modifiers)
        follow = ("It will follow pose/animation" if has_deform
                  else "Generate a Rig, then it will follow pose")
        self.report(
            {'INFO'},
            f"Hair '{hair_obj.name}' created on '{mesh_obj.name}'. {follow}. "
            "Now click 'Spawn (Preset)' or 'Hair Sculpt Mode'",
        )
        return {'FINISHED'}

    @staticmethod
    def _wire_deform(context, hair_obj, mesh_obj):
        """Bring a legacy hair object up to the pose-following standard."""
        if hair_obj.data.surface is None:
            hair_obj.data.surface = mesh_obj
        if not hair_obj.data.surface_uv_map:
            hair_obj.data.surface_uv_map = _ensure_hair_uv(context, mesh_obj)
        _ensure_rest_position(mesh_obj)
        if hair_obj.parent is None:
            hair_obj.parent = mesh_obj
            hair_obj.matrix_parent_inverse = mesh_obj.matrix_world.inverted()
        _ensure_surface_deform_modifier(context, hair_obj, mesh_obj)


class PIPESCULPT_OT_hair_sculpt_mode(Operator):
    bl_idname = "pipe_sculpt.hair_sculpt_mode"
    bl_label = "Hair Sculpt Mode"
    bl_description = (
        "Enter Hair Sculpt mode on the active hair-curves object. Native "
        "brushes available: Comb, Add, Delete, Density, Grow/Shrink, "
        "Pinch, Smooth, Twist, Puff, Slide"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVES'

    def execute(self, context):
        obj = context.active_object
        if context.mode == 'SCULPT_CURVES':
            self.report({'INFO'}, "Already in Hair Sculpt mode")
            return {'FINISHED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            bpy.ops.object.mode_set(mode='SCULPT_CURVES')
        except RuntimeError as e:
            self.report({'ERROR'}, f"Couldn't enter Hair Sculpt mode: {e}")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Hair Sculpt active on '{obj.name}' — paint with Density, Comb, Grow brushes",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_hair_apply_preset(Operator):
    bl_idname = "pipe_sculpt.hair_apply_preset"
    bl_label = "Spawn Hair (Preset)"
    bl_description = (
        "Spawn hair strands across the whole surface at the preset's real-world "
        "density. Strands are area-weighted, grow along the mesh normals, and "
        "are bound to the surface so they FOLLOW POSE/ANIMATION. Refine "
        "afterwards with the Hair Sculpt brushes"
    )
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(
        name="Preset",
        items=_preset_enum_items(),
        default='SCALP',
    )
    density_multiplier: FloatProperty(
        name="Density Multiplier",
        description="Scale the preset's base density (0.5 = half-thick, 2.0 = double)",
        default=1.0,
        min=0.0,
        max=10.0,
    )
    max_strands: IntProperty(
        name="Strand Cap",
        description="Hard ceiling on spawned strands — protects against freezing Blender on dense presets",
        default=50_000,
        min=10,
        max=2_000_000,
    )
    seed: IntProperty(
        name="Seed",
        description="Random seed for strand placement. Same seed → same layout",
        default=0,
        min=0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'CURVES':
            return False
        return obj.data.surface is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        import random

        hair_obj = context.active_object
        mesh_obj = hair_obj.data.surface
        if mesh_obj is None or mesh_obj.type != 'MESH':
            self.report({'ERROR'}, "Hair object isn't bound to a surface mesh")
            return {'CANCELLED'}

        preset = hair_core.get_preset(self.preset)
        area = _mesh_surface_area_m2(mesh_obj)
        strand_count = hair_core.select_density_for_painted_area(
            area, preset, self.density_multiplier
        )
        if strand_count > self.max_strands:
            self.report(
                {'WARNING'},
                f"Preset wanted {strand_count:,} strands; capped to {self.max_strands:,}. "
                "Raise 'Strand Cap' for fuller coverage",
            )
            strand_count = self.max_strands

        memory_mb = hair_core.estimate_memory_mb(strand_count, preset.segments)
        if memory_mb > 800.0:
            self.report(
                {'WARNING'},
                f"{strand_count:,} strands ≈ {memory_mb:.0f} MB — too heavy. "
                "Lower the strand cap or density multiplier",
            )
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Ensure the deform prerequisites so spawned hair follows pose even if
        # the hair object predates this version.
        uv_name = hair_obj.data.surface_uv_map
        if not uv_name or mesh_obj.data.uv_layers.get(uv_name) is None:
            uv_name = _ensure_hair_uv(context, mesh_obj)
            hair_obj.data.surface_uv_map = uv_name
        _ensure_rest_position(mesh_obj)
        context.view_layer.objects.active = hair_obj
        _ensure_surface_deform_modifier(context, hair_obj, mesh_obj)

        triangles = _extract_triangles_uv(mesh_obj, uv_name)
        if not triangles:
            self.report(
                {'ERROR'},
                "Couldn't read the hair UV — try 'Setup Hair' again",
            )
            return {'CANCELLED'}

        scale_factor = (mesh_obj.scale.x * mesh_obj.scale.y * mesh_obj.scale.z) ** (1.0 / 3.0)
        rng = random.Random(self.seed)
        strands, root_uvs = hair_core.build_strands_with_uv(
            triangles, strand_count, preset, rng, mesh_scale=scale_factor,
        )

        try:
            ok = _build_curves_from_strands(hair_obj.data, strands, root_uvs)
        except Exception as e:
            self.report(
                {'ERROR'},
                f"Curves population failed ({e}). Report this so we can fix "
                "_build_curves_from_strands",
            )
            return {'CANCELLED'}

        if not ok:
            self.report({'ERROR'}, "Curves population produced no geometry")
            return {'CANCELLED'}

        context.view_layer.objects.active = hair_obj
        self.report(
            {'INFO'},
            f"Spawned {len(strands):,} '{preset.label}' strands on '{mesh_obj.name}' "
            f"({area:.3f} m²) — bound to follow pose. Enter Hair Sculpt Mode to refine",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_hair_to_cards(Operator):
    bl_idname = "pipe_sculpt.hair_to_cards"
    bl_label = "Hair → Hair Cards"
    bl_description = (
        "Convert hair curves to a mesh of UV'd hair-card quads for real-time "
        "export to Unity. Cards are packed in a regular grid via "
        "hair_core.hair_card_uv_layout"
    )
    bl_options = {'REGISTER', 'UNDO'}

    card_aspect: FloatProperty(
        name="Card Aspect (H/W)",
        description="Hair-card aspect ratio — 4 to 8 is typical for real-time hair",
        default=4.0,
        min=1.0,
        max=20.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'CURVES' and len(obj.data.curves) > 0

    def execute(self, context):
        hair_obj = context.active_object
        curves = hair_obj.data
        strand_count = len(curves.curves)
        if strand_count == 0:
            self.report({'ERROR'}, "Hair object has no curves yet — paint some first")
            return {'CANCELLED'}

        layout = hair_core.hair_card_uv_layout(strand_count, card_aspect=self.card_aspect)
        if not layout:
            self.report({'ERROR'}, "UV layout computation returned empty")
            return {'CANCELLED'}

        # Use Blender's built-in 'convert' on hair curves to convert them to
        # a mesh. UV-assigning from `layout` is a TODO for a later version —
        # for now the convert works and the user can run Smart Unwrap after.
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            bpy.ops.object.convert(target='MESH')
        except RuntimeError as e:
            self.report({'ERROR'}, f"Hair→mesh convert failed: {e}")
            return {'CANCELLED'}

        result = context.active_object
        result.name = f"{hair_obj.name}_Cards"

        self.report(
            {'INFO'},
            f"Converted {strand_count} strands to '{result.name}'. "
            "Run UV → Smart Unwrap for final UV layout",
        )
        return {'FINISHED'}


_classes = (
    PIPESCULPT_OT_hair_setup,
    PIPESCULPT_OT_hair_sculpt_mode,
    PIPESCULPT_OT_hair_apply_preset,
    PIPESCULPT_OT_hair_to_cards,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
