import bpy
from bpy.types import Operator

from . import rigging
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


def _target_faces(context, preset: presets_mod.Preset) -> int:
    addon = context.preferences.addons.get(__package__)
    if addon is not None:
        return getattr(addon.preferences, preset.target_faces_attr)
    return preset.target_faces_default


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
        if preset.max_voxel_size is not None:
            voxel_size = min(voxel_size, preset.max_voxel_size)
        obj.data.remesh_voxel_size = voxel_size

        bpy.ops.object.mode_set(mode='SCULPT')

        ts = context.tool_settings.sculpt
        ts.use_symmetry_x = preset.use_symmetry_x
        ts.use_symmetry_y = preset.use_symmetry_y
        ts.use_symmetry_z = preset.use_symmetry_z

        if not bpy.app.background:
            try:
                rigging.smart_voxel_remesh(obj)
            except RuntimeError as e:
                self.report({'WARNING'}, f"Initial voxel remesh failed: {e}")

        # Voxel remesh has baked the starter's subsurf-smoothed shape into mesh
        # data. A leftover Subsurf modifier would double-detail the sculpt base
        # and inflate Add Detail multires levels.
        for m in list(obj.modifiers):
            if m.type == 'SUBSURF':
                obj.modifiers.remove(m)

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
    bl_description = "Duplicate the active mesh and run retopology (quadriflow or decimate) with the preset's target face count"
    bl_options = {'REGISTER', 'UNDO'}

    method: bpy.props.EnumProperty(
        name="Method",
        items=(
            ('QUADRIFLOW', "Quadriflow",
             "Auto quad-retopology — best for organic shapes, slower"),
            ('DECIMATE', "Decimate (Collapse)",
             "Triangulating decimate modifier — fast, OK for static props, never for characters"),
        ),
        default='QUADRIFLOW',
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def _decimate_retopo(self, context, retopo, target_faces):
        # Use Decimate Collapse to a face-ratio that hits the target.
        current_faces = len(retopo.data.polygons)
        if current_faces == 0:
            return False, "Source mesh has no faces"
        ratio = max(0.0001, min(1.0, target_faces / current_faces))
        mod = retopo.modifiers.new(name="SculptKit Decimate", type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except RuntimeError as e:
            return False, f"Decimate apply failed: {e}"
        return True, None

    def _quadriflow_retopo(self, context, retopo, target_faces, use_sym):
        try:
            bpy.ops.object.quadriflow_remesh(
                target_faces=target_faces,
                use_mesh_symmetry=use_sym,
                use_preserve_sharp=False,
                use_preserve_boundary=False,
                smooth_normals=True,
                mode='FACES',
            )
        except RuntimeError as e:
            return False, f"Quadriflow failed: {e}"
        return True, None

    def execute(self, context):
        obj = _active_mesh(context)
        preset = _selected_preset(context)
        target_faces = _target_faces(context, preset)

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.duplicate(linked=False)
        retopo = context.active_object
        retopo.name = f"{obj.name}_retopo"

        # Apply Multires (preserves sculpt detail), drop Subsurf (would otherwise
        # sit on top of the new low-poly and double its visible polycount).
        for m in list(retopo.modifiers):
            if m.type == 'MULTIRES':
                try:
                    bpy.ops.object.modifier_apply(modifier=m.name)
                except RuntimeError:
                    retopo.modifiers.remove(m)
            elif m.type == 'SUBSURF':
                retopo.modifiers.remove(m)

        use_sym = preset.use_symmetry_x or preset.use_symmetry_y or preset.use_symmetry_z

        # Snapshot high-poly bone tags before remesh destroys the duplicate's
        # attribute. We restore via KDTree once the new mesh is built (GTR Ph3).
        gtr_source = obj  # original high-poly is the bone-tag source
        had_tags = rigging.VERTEX_ATTR in gtr_source.data.attributes

        if self.method == 'DECIMATE':
            ok, err = self._decimate_retopo(context, retopo, target_faces)
        else:
            ok, err = self._quadriflow_retopo(context, retopo, target_faces, use_sym)
        if not ok:
            # Clean up the orphaned duplicate so a re-run doesn't accumulate '_retopo.001's
            retopo_data = retopo.data
            bpy.data.objects.remove(retopo, do_unlink=True)
            if retopo_data.users == 0:
                bpy.data.meshes.remove(retopo_data, do_unlink=True)
            context.view_layer.objects.active = obj
            obj.select_set(True)
            self.report({'ERROR'}, err or "Retopo failed")
            return {'CANCELLED'}

        if had_tags:
            transferred = rigging.transfer_bone_tags_from_high(gtr_source, retopo)
            tag_msg = "GTR tags preserved" if transferred else "GTR transfer skipped"
        else:
            tag_msg = "no GTR tags"

        obj.hide_set(True)
        self.report(
            {'INFO'},
            f"Retopo'd '{obj.name}' → '{retopo.name}' "
            f"({self.method}, {target_faces} target, sym={use_sym}, {tag_msg})",
        )
        return {'FINISHED'}


_classes = (
    SCULPTKIT_OT_workflow_start,
    SCULPTKIT_OT_workflow_add_detail,
    SCULPTKIT_OT_workflow_retopo,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
