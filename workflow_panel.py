import bpy
from bpy.props import EnumProperty
from bpy.types import Panel

from . import workflow_presets as presets_mod


_SCENE_PROP = "sculpt_kit_preset"


class SCULPTKIT_PT_workflow(Panel):
    bl_idname = "SCULPTKIT_PT_workflow"
    bl_label = "Workflow Pipeline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "SculptKit"

    def draw(self, context):
        layout = self.layout

        layout.prop(context.scene, _SCENE_PROP, text="Preset")

        col = layout.column(align=True)
        col.scale_y = 1.4
        col.operator("sculpt_kit.workflow_start", icon='SCULPTMODE_HLT')
        col.operator("sculpt_kit.workflow_add_detail", icon='MOD_MULTIRES')
        col.operator("sculpt_kit.workflow_retopo", icon='MOD_REMESH')
        col.operator("sculpt_kit.workflow_bake", icon='RENDER_STILL')


_classes = (SCULPTKIT_PT_workflow,)


def register():
    setattr(
        bpy.types.Scene,
        _SCENE_PROP,
        EnumProperty(
            name="SculptKit Preset",
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
