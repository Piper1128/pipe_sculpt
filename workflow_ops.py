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
    bl_description = "Step the multires modifier up by one level, toward the preset's target"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        preset = _selected_preset(context)
        target_levels = preset.multires_levels

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.shade_smooth()

        mod = next((m for m in obj.modifiers if m.type == 'MULTIRES'), None)
        if mod is None:
            mod = obj.modifiers.new(name="SculptKit Multires", type='MULTIRES')

        if mod.total_levels >= target_levels:
            self.report({'INFO'}, f"Already at preset target level {target_levels}")
            bpy.ops.object.mode_set(mode='SCULPT')
            return {'CANCELLED'}

        try:
            bpy.ops.object.multires_subdivide(modifier=mod.name, mode='CATMULL_CLARK')
        except RuntimeError as e:
            self.report({'ERROR'}, f"Multires subdivide failed: {e}")
            return {'CANCELLED'}

        mod.levels = mod.total_levels
        mod.sculpt_levels = mod.total_levels
        mod.render_levels = mod.total_levels

        bpy.ops.object.mode_set(mode='SCULPT')
        self.report({'INFO'}, f"Multires {mod.total_levels} / {target_levels}")
        return {'FINISHED'}


class SCULPTKIT_OT_workflow_retopo(Operator):
    bl_idname = "sculpt_kit.workflow_retopo"
    bl_label = "Retopo"
    bl_description = "Duplicate the active mesh and run quadriflow with the preset's target face count"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        preset = _selected_preset(context)
        prefs = context.preferences.addons[__package__].preferences
        target_faces = getattr(prefs, preset.target_faces_attr)

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.duplicate(linked=False)
        retopo = context.active_object
        retopo.name = f"{obj.name}_retopo"

        for m in list(retopo.modifiers):
            if m.type == 'MULTIRES':
                try:
                    bpy.ops.object.modifier_apply(modifier=m.name)
                except RuntimeError:
                    retopo.modifiers.remove(m)

        sym_axes = set()
        if preset.use_symmetry_x:
            sym_axes.add('X')
        if preset.use_symmetry_y:
            sym_axes.add('Y')
        if preset.use_symmetry_z:
            sym_axes.add('Z')

        try:
            bpy.ops.object.quadriflow_remesh(
                target_faces=target_faces,
                use_mesh_symmetry=bool(sym_axes),
                mesh_symmetry_axes=sym_axes,
                use_preserve_sharp=False,
                use_preserve_boundary=False,
                smooth_normals=True,
                mode='FACES',
            )
        except RuntimeError as e:
            self.report({'ERROR'}, f"Quadriflow failed: {e}")
            return {'CANCELLED'}

        obj.hide_set(True)
        self.report(
            {'INFO'},
            f"Retopo'd '{obj.name}' → '{retopo.name}' ({target_faces} faces, sym={sorted(sym_axes) or 'none'})",
        )
        return {'FINISHED'}


class SCULPTKIT_OT_workflow_bake(Operator):
    bl_idname = "sculpt_kit.workflow_bake"
    bl_label = "Bake Maps"
    bl_description = (
        "Bake a normal map from the high-poly source to the active low-poly mesh. "
        "Auto-pairs '<name>_retopo' with '<name>'; otherwise uses any other selected mesh as source"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def _resolve_high_poly(self, context, low):
        if low.name.endswith("_retopo"):
            base = low.name[: -len("_retopo")]
            obj = bpy.data.objects.get(base)
            if obj is not None and obj.type == 'MESH':
                return obj
        for o in context.selected_objects:
            if o is not low and o.type == 'MESH':
                return o
        return None

    def execute(self, context):
        low = _active_mesh(context)
        high = self._resolve_high_poly(context, low)
        if high is None:
            self.report({'ERROR'}, "No high-poly source — name it '<low>_retopo' or select it alongside")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if not low.data.uv_layers:
            bpy.ops.object.select_all(action='DESELECT')
            low.select_set(True)
            context.view_layer.objects.active = low
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.005)
            bpy.ops.object.mode_set(mode='OBJECT')

        img_name = f"{low.name}_normal"
        img = bpy.data.images.get(img_name)
        if img is None:
            img = bpy.data.images.new(
                img_name, width=2048, height=2048, alpha=False, float_buffer=False
            )
            img.colorspace_settings.name = 'Non-Color'

        mat_name = f"{low.name}_bake_mat"
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(mat_name)
            mat.use_nodes = True
        if mat.name not in [m.name for m in low.data.materials if m]:
            low.data.materials.append(mat)

        nodes = mat.node_tree.nodes
        tex_node = next(
            (n for n in nodes if n.type == 'TEX_IMAGE' and n.image == img), None
        )
        if tex_node is None:
            tex_node = nodes.new('ShaderNodeTexImage')
            tex_node.image = img
        nodes.active = tex_node

        scene = context.scene
        prior_engine = scene.render.engine
        scene.render.engine = 'CYCLES'

        max_dim = _max_bbox_dim(high)
        scene.render.bake.use_selected_to_active = True
        scene.render.bake.cage_extrusion = max_dim * 0.01
        scene.render.bake.max_ray_distance = max_dim * 0.05
        scene.cycles.bake_type = 'NORMAL'

        bpy.ops.object.select_all(action='DESELECT')
        was_hidden = high.hide_get()
        if was_hidden:
            high.hide_set(False)
        high.select_set(True)
        low.hide_set(False)
        low.select_set(True)
        context.view_layer.objects.active = low

        try:
            bpy.ops.object.bake(type='NORMAL')
        except RuntimeError as e:
            scene.render.engine = prior_engine
            if was_hidden:
                high.hide_set(True)
            self.report({'ERROR'}, f"Bake failed: {e}")
            return {'CANCELLED'}

        scene.render.engine = prior_engine
        if was_hidden:
            high.hide_set(True)
        img.pack()

        self.report(
            {'INFO'},
            f"Baked '{img.name}' 2048² from '{high.name}' → '{low.name}'",
        )
        return {'FINISHED'}


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
