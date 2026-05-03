import bpy
from bpy.types import Operator

from . import workflow_presets as presets_mod


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _max_bbox_dim(obj) -> float:
    dims = obj.dimensions
    return max(dims.x, dims.y, dims.z, 0.001)


def _selected_preset(context) -> presets_mod.Preset:
    pid = context.scene.sculpt_kit_preset
    return presets_mod.PRESETS_BY_ID.get(pid, presets_mod.PRESETS_BY_ID[presets_mod.DEFAULT_PRESET_ID])


class SCULPTKIT_OT_workflow_start(Operator):
    bl_idname = "sculpt_kit.workflow_start"
    bl_label = "Start Sculpt"
    bl_description = "Enter sculpt mode, set voxel size from bbox, apply symmetry, and run an initial voxel remesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "No active mesh object")
            return {'CANCELLED'}

        preset = _selected_preset(context)

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        voxel_size = _max_bbox_dim(obj) * preset.voxel_size_factor
        obj.data.remesh_voxel_size = voxel_size

        bpy.ops.object.mode_set(mode='SCULPT')

        ts = context.tool_settings.sculpt
        ts.use_symmetry_x = preset.use_symmetry_x
        ts.use_symmetry_y = preset.use_symmetry_y
        ts.use_symmetry_z = preset.use_symmetry_z

        try:
            bpy.ops.object.voxel_remesh()
        except RuntimeError as e:
            self.report({'WARNING'}, f"Initial voxel remesh failed: {e}")

        self.report(
            {'INFO'},
            f"Started '{preset.label}' sculpt — voxel {voxel_size:.4f}m, symmetry "
            f"X={preset.use_symmetry_x} Y={preset.use_symmetry_y} Z={preset.use_symmetry_z}",
        )
        return {'FINISHED'}


class SCULPTKIT_OT_workflow_add_detail(Operator):
    bl_idname = "sculpt_kit.workflow_add_detail"
    bl_label = "Add Detail"
    bl_description = "Convert to multires and subdivide to the preset's detail level"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        self.report({'INFO'}, "Add Detail — not implemented yet")
        return {'CANCELLED'}


class SCULPTKIT_OT_workflow_retopo(Operator):
    bl_idname = "sculpt_kit.workflow_retopo"
    bl_label = "Retopo"
    bl_description = "Duplicate the active mesh and run quadriflow with the preset's target face count"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        self.report({'INFO'}, "Retopo — not implemented yet")
        return {'CANCELLED'}


class SCULPTKIT_OT_workflow_bake(Operator):
    bl_idname = "sculpt_kit.workflow_bake"
    bl_label = "Bake Maps"
    bl_description = "Bake normal map from the high-poly source to the low-poly retopo target"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        self.report({'INFO'}, "Bake Maps — not implemented yet")
        return {'CANCELLED'}


_classes = (
    SCULPTKIT_OT_workflow_start,
    SCULPTKIT_OT_workflow_add_detail,
    SCULPTKIT_OT_workflow_retopo,
    SCULPTKIT_OT_workflow_bake,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
