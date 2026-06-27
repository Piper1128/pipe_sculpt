import bpy
from bpy.props import EnumProperty
from bpy.types import Panel

from . import workflow_presets as presets_mod


_SCENE_PROP = "pipe_sculpt_preset"


class PIPESCULPT_PT_workflow(Panel):
    bl_idname = "PIPESCULPT_PT_workflow"
    bl_label = "Workflow Pipeline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        is_mesh = obj is not None and obj.type == 'MESH'
        has_subsurf = is_mesh and any(m.type == 'SUBSURF' for m in obj.modifiers)

        layout.prop(context.scene, _SCENE_PROP, text="Preset")

        # Stage indicator strip — tells the user where they are in the pipeline.
        # Walking through 5+ workflow scenarios showed this was the most-asked
        # "is it broken or did I skip a step" UX gap.
        if not is_mesh:
            layout.label(text="Select a mesh to begin", icon='INFO')
        elif has_subsurf:
            layout.label(text="Stage 1: click Start Sculpt", icon='SCULPTMODE_HLT')
        elif any(m.type == 'MULTIRES' for m in obj.modifiers):
            layout.label(text="Stage 2/3: sculpt + retopo", icon='OUTLINER_OB_MESH')
        else:
            layout.label(text="Stage 3/4: retopo + bake", icon='RENDER_STILL')

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("pipe_sculpt.workflow_start", text="1. Start Sculpt", icon='SCULPTMODE_HLT')
        col.operator("pipe_sculpt.workflow_add_detail", text="2. Add Detail", icon='MOD_MULTIRES')
        col.operator("pipe_sculpt.workflow_retopo", text="3. Retopo (auto)", icon='MOD_REMESH')
        col.operator("pipe_sculpt.bake_maps", text="4. Bake Maps", icon='RENDER_STILL')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Manual Retopo (alternative to step 3)", icon='MESH_GRID')
        col.operator("pipe_sculpt.retopo_manual_setup", icon='MOD_SHRINKWRAP')
        col.operator("pipe_sculpt.retopo_manual_finish", icon='CHECKMARK')
        col.operator("pipe_sculpt.retopo_manual_cancel", icon='X')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Mesh Tools", icon='BRUSHES_ALL')
        # Relax works on any mesh, not specifically retopo — moved out of the
        # "Manual Retopo" section so it's not labelled as a retopo-only tool.
        col.operator("pipe_sculpt.retopo_relax", text="Relax (any mesh)")

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="UV & Paint", icon='UV')
        col.operator("pipe_sculpt.uv_smart_unwrap", icon='MOD_UVPROJECT')
        row = col.row(align=True)
        row.operator("pipe_sculpt.uv_auto_seam", text="Auto-Seam", icon='EDGESEL')
        row.operator("pipe_sculpt.uv_symmetry_mirror", text="Mirror X", icon='MOD_MIRROR')
        row = col.row(align=True)
        row.operator("pipe_sculpt.uv_checker_toggle", text="Checker", icon='TEXTURE')
        row.operator("pipe_sculpt.uv_stretch_toggle", text="Stretch", icon='OVERLAY')
        col.operator("pipe_sculpt.uv_texel_density", icon='DRIVER_DISTANCE')
        col.separator()
        col.operator("pipe_sculpt.paint_setup", icon='BRUSH_DATA')
        col.operator("pipe_sculpt.paint_setup_pbr", icon='NODE_TEXTURE')
        col.operator("pipe_sculpt.paint_save", icon='FILE_TICK')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Hair & Fur", icon='CURVES_DATA')
        col.operator("pipe_sculpt.hair_setup", icon='OUTLINER_OB_CURVES')
        col.operator("pipe_sculpt.hair_sculpt_mode", icon='BRUSH_DATA')
        col.operator("pipe_sculpt.hair_apply_preset", icon='PRESET')
        col.operator("pipe_sculpt.hair_to_cards", icon='MESH_PLANE')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Genesis-Tracked Rigging", icon='ARMATURE_DATA')
        col.operator("pipe_sculpt.generate_rig", icon='OUTLINER_OB_ARMATURE')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Export", icon='EXPORT')
        col.operator("pipe_sculpt.export_unity_fbx", icon='OUTLINER_OB_MESH')
        col.operator("pipe_sculpt.export_axis_calibration", text="Verify Axis Mode", icon='ORIENTATION_GIMBAL')


_classes = (PIPESCULPT_PT_workflow,)


def register():
    setattr(
        bpy.types.Scene,
        _SCENE_PROP,
        EnumProperty(
            name="PipeSculpt Preset",
            description="Workflow preset for sculpting and retopology",
            items=presets_mod.preset_enum_items(),
            default=presets_mod.DEFAULT_PRESET_ID,
        ),
    )
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types.Scene, _SCENE_PROP):
        delattr(bpy.types.Scene, _SCENE_PROP)
