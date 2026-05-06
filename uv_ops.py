"""UV mapping operators — preset-driven unwrap, auto-seam, visualisation toggles.

Designed for users new to Blender's UV editor: one-click operators with sensible
defaults, preset-driven, no choosing between five different unwrap algorithms.

Operators:
  - PIPESCULPT_OT_uv_smart_unwrap     : preset-driven unwrap + pack
  - PIPESCULPT_OT_uv_auto_seam        : mark sharp edges as seams
  - PIPESCULPT_OT_uv_checker_toggle   : toggle UV checker material
  - PIPESCULPT_OT_uv_stretch_toggle   : toggle UV stretch heatmap overlay
  - PIPESCULPT_OT_uv_symmetry_mirror  : mirror UVs across X axis
  - PIPESCULPT_OT_uv_texel_density    : compute or apply texel density
"""
from __future__ import annotations

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator


# Preset → unwrap config:
#   angle_limit       — Smart UV Project angle threshold (degrees)
#   sharp_seam_angle  — auto-mark seams at edges sharper than this (degrees)
#   use_smart_project — True: Smart UV Project, False: regular Unwrap (respects seams)
UV_PRESETS = {
    'CHARACTER':   {'angle_limit': 66.0, 'sharp_seam_angle': 50.0, 'use_smart_project': False},
    'HARDSURFACE': {'angle_limit': 30.0, 'sharp_seam_angle': 20.0, 'use_smart_project': False},
    'PROP':        {'angle_limit': 66.0, 'sharp_seam_angle': 0.0,  'use_smart_project': True},
}


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _resolution_to_margin(resolution: int) -> float:
    """Bake-bleed-safe margin in [0,1] UV space — 8 pixels constant.

    Matches bake_ops's UV margin scaling so painted textures don't seam
    differently from baked normals.
    """
    return 8.0 / max(resolution, 64)


def _selected_preset_id(context) -> str:
    return getattr(context.scene, "pipe_sculpt_preset", "CHARACTER").upper()


def _preset_to_uv_preset(preset_id: str) -> str:
    """Map workflow_presets ids to UV_PRESETS keys.

    Workflow presets are Character / Bust+Face / Prop / etc. UV-wise, busts
    and faces want the Character treatment, props want the Prop treatment,
    and anything else falls back to Hardsurface as a defensive default.
    """
    return {
        'CHARACTER': 'CHARACTER',
        'BUST':      'CHARACTER',
        'PROP':      'PROP',
    }.get(preset_id, 'HARDSURFACE')


class PIPESCULPT_OT_uv_auto_seam(Operator):
    bl_idname = "pipe_sculpt.uv_auto_seam"
    bl_label = "Auto-Seam by Angle"
    bl_description = (
        "Mark edges sharper than the angle threshold as UV seams. Higher "
        "angle = fewer seams (only the sharpest edges); lower angle = more "
        "seams (any sharp-ish edge gets cut)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    angle_threshold: FloatProperty(
        name="Angle Threshold (degrees)",
        description="Edges sharper than this become seams",
        default=30.0,
        min=0.0,
        max=180.0,
        subtype='ANGLE',
        unit='ROTATION',
    )
    clear_existing: bpy.props.BoolProperty(
        name="Clear Existing Seams",
        description="Remove all existing seams before applying new ones",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        import math

        obj = _active_mesh(context)
        prior_mode = context.mode

        # angle_threshold uses subtype='ANGLE' which stores radians, but the UI
        # value is degrees. We convert to radians for the operator below.
        angle_rad = math.radians(self.angle_threshold)

        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type='EDGE')

        if self.clear_existing:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.mark_seam(clear=True)

        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.edges_select_sharp(sharpness=angle_rad)
        # If nothing got selected, edges_select_sharp at this threshold means
        # the mesh is too smooth — bail with a friendly hint.
        sharp_count = sum(1 for e in obj.data.edges if e.select)
        if sharp_count == 0:
            if prior_mode == 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            self.report(
                {'WARNING'},
                f"No edges sharper than {self.angle_threshold:.1f}° — try a lower threshold",
            )
            return {'CANCELLED'}

        bpy.ops.mesh.mark_seam(clear=False)
        if prior_mode == 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report({'INFO'}, f"Marked {sharp_count} edges as seams")
        return {'FINISHED'}


class PIPESCULPT_OT_uv_smart_unwrap(Operator):
    bl_idname = "pipe_sculpt.uv_smart_unwrap"
    bl_label = "Smart Unwrap"
    bl_description = (
        "Auto-mark seams at sharp edges, unwrap, and pack islands. Preset-driven: "
        "Character keeps fewer seams (organic), Hardsurface cuts at every sharp "
        "edge (mech/prop), Prop uses Smart UV Project (no seam-marking needed)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    target_resolution: IntProperty(
        name="Target Resolution",
        description=(
            "Bake/paint texture resolution this UV layout will be used at. "
            "Used to scale the pack-islands margin so seam-bleed protection "
            "stays at ~8 pixels regardless of resolution"
        ),
        default=2048,
        min=512,
        max=8192,
    )
    auto_seam: bpy.props.BoolProperty(
        name="Auto-Seam Sharp Edges",
        description="Mark edges sharper than the preset's threshold as seams before unwrap",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = _active_mesh(context)
        return obj is not None and len(obj.data.polygons) > 0

    def execute(self, context):
        import math

        obj = _active_mesh(context)
        preset_id = _preset_to_uv_preset(_selected_preset_id(context))
        cfg = UV_PRESETS[preset_id]

        prior_mode = context.mode
        prior_active = context.view_layer.objects.active
        if prior_active is not obj:
            context.view_layer.objects.active = obj

        # Apply scale first — non-uniform scale wrecks UV proportions.
        if any(abs(s - 1.0) > 0.001 for s in obj.scale):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        if context.mode != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')

        # Optional auto-seam pass (skipped for PROP — Smart UV Project handles it)
        if self.auto_seam and cfg['sharp_seam_angle'] > 0.0:
            bpy.ops.mesh.select_mode(type='EDGE')
            bpy.ops.mesh.select_all(action='DESELECT')
            try:
                bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(cfg['sharp_seam_angle']))
                bpy.ops.mesh.mark_seam(clear=False)
            except RuntimeError:
                pass

        # Unwrap
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.select_all(action='SELECT')
        try:
            if cfg['use_smart_project']:
                bpy.ops.uv.smart_project(
                    angle_limit=cfg['angle_limit'],
                    island_margin=_resolution_to_margin(self.target_resolution),
                    correct_aspect=True,
                    scale_to_bounds=False,
                )
            else:
                bpy.ops.uv.unwrap(
                    method='ANGLE_BASED',
                    margin=_resolution_to_margin(self.target_resolution),
                )
                # Pack after a regular unwrap so islands fit cleanly
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.pack_islands(
                    margin=_resolution_to_margin(self.target_resolution),
                    rotate=True,
                    scale=True,
                )
        except RuntimeError as e:
            if prior_mode == 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            self.report({'ERROR'}, f"Unwrap failed: {e}")
            return {'CANCELLED'}

        # Average islands scale so texel density is uniform across islands
        bpy.ops.uv.average_islands_scale()
        bpy.ops.uv.pack_islands(
            margin=_resolution_to_margin(self.target_resolution),
            rotate=True,
            scale=True,
        )

        if prior_mode == 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report(
            {'INFO'},
            f"Unwrapped '{obj.name}' as {preset_id} preset @ {self.target_resolution}px",
        )
        return {'FINISHED'}


_classes = (
    PIPESCULPT_OT_uv_auto_seam,
    PIPESCULPT_OT_uv_smart_unwrap,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
