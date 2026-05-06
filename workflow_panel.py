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

        layout.prop(context.scene, _SCENE_PROP, text="Preset")

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("pipe_sculpt.workflow_start", icon='SCULPTMODE_HLT')
        col.operator("pipe_sculpt.workflow_add_detail", icon='MOD_MULTIRES')
        col.operator("pipe_sculpt.workflow_retopo", icon='MOD_REMESH')
        col.operator("pipe_sculpt.bake_maps", icon='RENDER_STILL')

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.label(text="Manual Retopo", icon='MESH_GRID')
        col.operator("pipe_sculpt.retopo_manual_setup", icon='MOD_SHRINKWRAP')
        col.operator("pipe_sculpt.retopo_relax", icon='BRUSHES_ALL')
        col.operator("pipe_sculpt.retopo_manual_finish", icon='CHECKMARK')
        col.operator("pipe_sculpt.retopo_manual_cancel", icon='X')

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
