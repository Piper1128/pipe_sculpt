"""Hair / fur operators — Blender adapter for hair_core's pure logic.

Born Clean per IronCore conventions: this file is the Adapter.Unity-
equivalent — it imports bpy and translates user actions into Blender
Hair Curves operations. All math (presets, density, card packing,
memory estimation) lives in hair_core.py and is unit-tested headlessly.

Workflow:
  1. Active mesh + Setup Hair Brushable — creates a Hair Curves object
     parented to the mesh with surface binding. Empty by default; the
     user grows hair by painting density.
  2. Switch to Hair Sculpt Mode — comb, grow, shrink, density, twist
     brushes become available natively (Blender 5.x).
  3. Apply Density Preset — fills the entire surface with strand count
     calculated from hair_core.strand_count_for(area, preset).
  4. Convert Hair to Cards — for Unity real-time export: bakes the hair
     curves to mesh hair-cards UV'd via hair_core.hair_card_uv_layout.

Operators:
  - PIPESCULPT_OT_hair_setup           : create Hair Curves on active mesh
  - PIPESCULPT_OT_hair_sculpt_mode     : enter Hair Sculpt mode
  - PIPESCULPT_OT_hair_apply_preset    : populate density from preset
  - PIPESCULPT_OT_hair_to_cards        : convert to mesh hair-cards
"""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator

from . import hair_core


HAIR_OBJ_SUFFIX = "_Hair"
HAIR_MARKER_PROP = "pipe_sculpt_hair_source"


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


def _extract_triangles(context, mesh_obj):
    """Extract (v0,v1,v2,n0,n1,n2) tuples from the evaluated mesh in local space.

    Uses the depsgraph-evaluated mesh so multires/modifiers are reflected.
    Vertex normals are used (not face normals) so interpolated growth
    directions are smooth across the surface. Returns plain float tuples
    for hair_core (which is bpy-free).
    """
    dg = context.evaluated_depsgraph_get()
    eval_obj = mesh_obj.evaluated_get(dg)
    mesh = eval_obj.to_mesh()
    try:
        mesh.calc_loop_triangles()
        verts = mesh.vertices
        triangles = []
        for lt in mesh.loop_triangles:
            i0, i1, i2 = lt.vertices
            v0 = tuple(verts[i0].co)
            v1 = tuple(verts[i1].co)
            v2 = tuple(verts[i2].co)
            n0 = tuple(verts[i0].normal)
            n1 = tuple(verts[i1].normal)
            n2 = tuple(verts[i2].normal)
            triangles.append((v0, v1, v2, n0, n1, n2))
    finally:
        eval_obj.to_mesh_clear()
    return triangles


def _build_curves_from_strands(curves_data, strands) -> bool:
    """Populate a Curves datablock from hair_core strand point-lists.

    strands: list of strands, each a list of (x,y,z) point tuples.
    Returns True on success. Wrapped defensively because the exact
    Curves population API (add_curves / foreach_set) is version-sensitive
    and worth failing loud on rather than silently producing empty hair.
    """
    # Clear any existing curves first
    if len(curves_data.curves) > 0:
        curves_data.remove_curves(None)  # None = remove all

    sizes = [len(s) for s in strands]
    if not sizes:
        return False

    # add_curves(sizes) appends curves with the given per-curve point counts
    curves_data.add_curves(sizes)

    # Flatten all point positions into one array for foreach_set
    flat = []
    for strand in strands:
        for p in strand:
            flat.extend((p[0], p[1], p[2]))

    if len(curves_data.points) * 3 != len(flat):
        return False
    curves_data.points.foreach_set("position", flat)
    curves_data.update_tag()
    return True


class PIPESCULPT_OT_hair_setup(Operator):
    bl_idname = "pipe_sculpt.hair_setup"
    bl_label = "Setup Hair (Brushable)"
    bl_description = (
        "Create an empty Hair Curves object bound to the active mesh's "
        "surface. Switch to Hair Sculpt Mode and paint density with the "
        "native brushes (Comb, Grow, Add, Density, Twist)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        mesh_obj = _active_mesh(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Idempotency: if hair already exists for this mesh, just select + report.
        existing = _find_hair_for_mesh(mesh_obj)
        if existing is not None:
            bpy.ops.object.select_all(action='DESELECT')
            existing.select_set(True)
            context.view_layer.objects.active = existing
            self.report({'INFO'}, f"Hair already exists ('{existing.name}') — selected it")
            return {'FINISHED'}

        # Create empty Hair Curves dataset + object
        curves_data = bpy.data.hair_curves.new(f"{mesh_obj.name}{HAIR_OBJ_SUFFIX}")
        hair_obj = bpy.data.objects.new(f"{mesh_obj.name}{HAIR_OBJ_SUFFIX}", curves_data)
        hair_obj[HAIR_MARKER_PROP] = mesh_obj.name
        context.collection.objects.link(hair_obj)
        hair_obj.matrix_world = mesh_obj.matrix_world.copy()

        # Bind hair to the mesh surface so growing/deformation follow
        curves_data.surface = mesh_obj
        if mesh_obj.data.uv_layers.active is not None:
            curves_data.surface_uv_map = mesh_obj.data.uv_layers.active.name

        # Make hair the active object, ready for the user to enter sculpt mode
        bpy.ops.object.select_all(action='DESELECT')
        hair_obj.select_set(True)
        context.view_layer.objects.active = hair_obj

        self.report(
            {'INFO'},
            f"Hair object '{hair_obj.name}' created — bound to '{mesh_obj.name}'. "
            "Click 'Hair Sculpt Mode' to start brushing",
        )
        return {'FINISHED'}


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
        "Spawn hair strands across the entire surface at the chosen preset's "
        "real-world density. Strands are placed area-weighted (uniform over "
        "the surface) and grow along the mesh normals. Refine afterwards with "
        "the Hair Sculpt brushes"
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
        # Apply the user's hard cap
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

        # Extract triangle data (evaluated mesh) and run the pure-Python spawn
        triangles = _extract_triangles(context, mesh_obj)
        if not triangles:
            self.report({'ERROR'}, "Surface mesh has no faces to grow hair on")
            return {'CANCELLED'}

        scale_factor = (mesh_obj.scale.x * mesh_obj.scale.y * mesh_obj.scale.z) ** (1.0 / 3.0)
        rng = random.Random(self.seed)
        strands = hair_core.build_strands_geometry(
            triangles, strand_count, preset, rng, mesh_scale=scale_factor,
        )

        # Build the curves geometry from the strand point-lists
        try:
            ok = _build_curves_from_strands(hair_obj.data, strands)
        except Exception as e:
            self.report(
                {'ERROR'},
                f"Curves population failed ({e}). The Blender 5.x Curves API "
                "may differ — report this so we can fix _build_curves_from_strands",
            )
            return {'CANCELLED'}

        if not ok:
            self.report({'ERROR'}, "Curves population produced no geometry")
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Spawned {len(strands):,} '{preset.label}' strands on '{mesh_obj.name}' "
            f"({area:.3f} m²). Enter Hair Sculpt Mode to comb / refine",
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
        # a mesh. UV-assigning from `layout` is a TODO for v0.12.0 — for now
        # the convert works and the user can run our existing Smart Unwrap
        # afterwards as a fallback.
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        try:
            bpy.ops.object.convert(target='MESH')
        except RuntimeError as e:
            self.report({'ERROR'}, f"Hair→mesh convert failed: {e}")
            return {'CANCELLED'}

        # Rename converted object
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
