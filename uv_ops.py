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


CHECKER_MAT_NAME = "PipeSculpt_UV_Checker"


def _build_checker_material():
    """Build a procedural UV checker material with a strong diagonal pattern.

    Uses two stacked Checker Texture nodes (UV-mapped, perpendicular scales)
    so the pattern reads even on heavily stretched islands. Output to Emission
    so shading-state doesn't affect what you see — it's a checker, not a
    rendering test.
    """
    mat = bpy.data.materials.get(CHECKER_MAT_NAME)
    if mat is not None:
        return mat

    mat = bpy.data.materials.new(CHECKER_MAT_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    # Wipe default nodes
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new('ShaderNodeOutputMaterial')
    emit = nt.nodes.new('ShaderNodeEmission')
    chk_a = nt.nodes.new('ShaderNodeTexChecker')
    chk_b = nt.nodes.new('ShaderNodeTexChecker')
    mix = nt.nodes.new('ShaderNodeMixRGB')
    uv = nt.nodes.new('ShaderNodeUVMap')

    chk_a.inputs['Scale'].default_value = 16.0
    chk_a.inputs['Color1'].default_value = (1.0, 1.0, 1.0, 1.0)
    chk_a.inputs['Color2'].default_value = (0.05, 0.05, 0.05, 1.0)

    chk_b.inputs['Scale'].default_value = 4.0
    chk_b.inputs['Color1'].default_value = (1.0, 0.3, 0.3, 1.0)  # red
    chk_b.inputs['Color2'].default_value = (0.3, 1.0, 0.3, 1.0)  # green

    mix.blend_type = 'MULTIPLY'
    mix.inputs['Fac'].default_value = 0.5

    nt.links.new(uv.outputs['UV'], chk_a.inputs['Vector'])
    nt.links.new(uv.outputs['UV'], chk_b.inputs['Vector'])
    nt.links.new(chk_a.outputs['Color'], mix.inputs['Color1'])
    nt.links.new(chk_b.outputs['Color'], mix.inputs['Color2'])
    nt.links.new(mix.outputs['Color'], emit.inputs['Color'])
    nt.links.new(emit.outputs['Emission'], out.inputs['Surface'])

    # Position nodes for tidy graph if user opens the shader editor
    out.location  = (400, 0)
    emit.location = (200, 0)
    mix.location  = (0, 0)
    chk_a.location = (-200, 100)
    chk_b.location = (-200, -100)
    uv.location   = (-400, 0)

    return mat


class PIPESCULPT_OT_uv_checker_toggle(Operator):
    bl_idname = "pipe_sculpt.uv_checker_toggle"
    bl_label = "Toggle UV Checker"
    bl_description = (
        "Add or remove a procedural UV checker material on the active mesh. "
        "Use it to spot stretched / squished UV islands at a glance — good "
        "checker squares should be visibly square in the 3D viewport"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        # Look for an existing checker slot
        existing_idx = next(
            (i for i, slot in enumerate(obj.material_slots)
             if slot.material is not None and slot.material.name == CHECKER_MAT_NAME),
            None,
        )
        if existing_idx is not None:
            # Toggle off: remove that slot only (preserves user's other materials)
            obj.active_material_index = existing_idx
            bpy.ops.object.material_slot_remove()
            self.report({'INFO'}, "UV checker removed")
            return {'FINISHED'}

        mat = _build_checker_material()
        obj.data.materials.append(mat)
        obj.active_material_index = len(obj.material_slots) - 1

        # Switch to Material Preview shading mode so the user actually sees the
        # checker. Solid mode hides procedural textures.
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                        break

        self.report({'INFO'}, "UV checker added — switch to Material Preview if hidden")
        return {'FINISHED'}


class PIPESCULPT_OT_uv_stretch_toggle(Operator):
    bl_idname = "pipe_sculpt.uv_stretch_toggle"
    bl_label = "Toggle UV Stretch Heatmap"
    bl_description = (
        "Toggle the UV editor's Display Stretch overlay on the first open UV "
        "editor. Red = stretched, blue = compressed, green = good. If no UV "
        "editor is open, opens one in a temporary split"
    )
    bl_options = {'REGISTER'}

    stretch_mode: EnumProperty(
        name="Stretch Mode",
        items=(
            ('ANGLE', "Angle", "Visualise UV angular distortion"),
            ('AREA',  "Area",  "Visualise UV area distortion"),
        ),
        default='ANGLE',
    )

    @classmethod
    def poll(cls, context):
        # We need either a UV editor in the screen or a 3D view we can split
        return any(a.type in {'IMAGE_EDITOR', 'VIEW_3D'} for a in context.screen.areas)

    def _find_uv_editor(self, context):
        for area in context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                for space in area.spaces:
                    if space.type == 'IMAGE_EDITOR' and space.mode == 'UV':
                        return space
        return None

    def execute(self, context):
        space = self._find_uv_editor(context)
        if space is None:
            self.report(
                {'WARNING'},
                "No UV editor open — open one (Shift+F10) and re-run, or "
                "use a UV-Editing workspace",
            )
            return {'CANCELLED'}

        ed = space.uv_editor
        # show_stretch is the master toggle; display_stretch_type chooses mode
        new_state = not ed.show_stretch
        ed.show_stretch = new_state
        if new_state:
            ed.display_stretch_type = self.stretch_mode

        msg = f"Stretch overlay {'ON' if new_state else 'OFF'}"
        if new_state:
            msg += f" ({self.stretch_mode.lower()})"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class PIPESCULPT_OT_uv_symmetry_mirror(Operator):
    bl_idname = "pipe_sculpt.uv_symmetry_mirror"
    bl_label = "Mirror UVs across X"
    bl_description = (
        "For X-symmetric meshes: copy UV coordinates from the +X half to the "
        "-X half so both halves share the same UV space. Texture painted on "
        "one side appears on both. Requires verts on the centerline (X≈0)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    epsilon: FloatProperty(
        name="Symmetry Tolerance",
        description=(
            "Maximum world-space distance considered the 'mirror match' for a "
            "vertex. Increase if your mesh isn't perfectly symmetric"
        ),
        default=0.001,
        min=1e-6,
        max=0.1,
        precision=4,
    )

    @classmethod
    def poll(cls, context):
        obj = _active_mesh(context)
        return obj is not None and bool(obj.data.uv_layers)

    def execute(self, context):
        import mathutils

        obj = _active_mesh(context)
        prior_mode = context.mode
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh = obj.data
        uv_layer = mesh.uv_layers.active
        if uv_layer is None:
            self.report({'ERROR'}, "Mesh has no active UV layer")
            return {'CANCELLED'}

        # Build KDTree of vertex positions on +X side, then for each -X vertex
        # find its mirror, and copy UVs loop-by-loop. Loops are per-corner so
        # we have to map vertices → loops on each side.
        positive_verts = [v for v in mesh.vertices if v.co.x > self.epsilon]
        negative_verts = [v for v in mesh.vertices if v.co.x < -self.epsilon]
        if not positive_verts or not negative_verts:
            self.report({'WARNING'}, "Mesh isn't X-symmetric (one side has no verts)")
            return {'CANCELLED'}

        kd = mathutils.kdtree.KDTree(len(positive_verts))
        for i, v in enumerate(positive_verts):
            kd.insert(v.co, i)
        kd.balance()

        # Loop indices grouped by vertex
        v_to_loops: dict = {}
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                v_to_loops.setdefault(vi, []).append(li)

        copied = 0
        for v_neg in negative_verts:
            # Mirror neg → pos by flipping X
            mirror_target = mathutils.Vector((-v_neg.co.x, v_neg.co.y, v_neg.co.z))
            _, src_kd_idx, dist = kd.find(mirror_target)
            if src_kd_idx is None or dist > self.epsilon * 2:
                continue
            v_pos = positive_verts[src_kd_idx]
            # Copy each loop UV from a source loop on v_pos to a loop on v_neg.
            # Vertices can have multiple loops (one per face corner) — we just
            # pair them in order. UV islands sharing the same vert get the same
            # mirrored UV, which is what we want for symmetric layouts.
            src_loops = v_to_loops.get(v_pos.index, [])
            dst_loops = v_to_loops.get(v_neg.index, [])
            for src_li, dst_li in zip(src_loops, dst_loops):
                src_uv = uv_layer.data[src_li].uv
                # Mirror in U axis around 0.5 so the mirrored island sits in
                # the same place as the source — both halves overlap.
                uv_layer.data[dst_li].uv = (1.0 - src_uv.x, src_uv.y)
                copied += 1

        mesh.update()
        if prior_mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')

        self.report(
            {'INFO'},
            f"Mirrored UVs on {len(negative_verts)} -X verts ({copied} loops); "
            "+X and -X halves now share UV space",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_uv_texel_density(Operator):
    bl_idname = "pipe_sculpt.uv_texel_density"
    bl_label = "Set Texel Density"
    bl_description = (
        "Compute the current average texel density and optionally scale UVs "
        "to match a target. Texel density = pixels per metre of mesh surface. "
        "Higher = sharper textures, more memory; AAA targets 512-1024 px/m"
    )
    bl_options = {'REGISTER', 'UNDO'}

    target_density: FloatProperty(
        name="Target Density (px/m)",
        description="Pixels per metre of mesh surface",
        default=1024.0,
        min=1.0,
        max=10000.0,
    )
    target_resolution: IntProperty(
        name="Texture Resolution",
        description="Texture dimension in pixels (assumes square)",
        default=2048,
        min=64,
        max=8192,
    )
    apply_scale: bpy.props.BoolProperty(
        name="Apply Scale",
        description="If on, scale UVs to match target. If off, only report current density",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = _active_mesh(context)
        return obj is not None and bool(obj.data.uv_layers)

    def _compute_density(self, obj, resolution: int) -> tuple[float, float, float]:
        """Returns (mesh_area_m2, uv_area_unit_sq, density_px_per_m).

        UV area is in [0,1]² space. Mesh area is in world-space metres².
        Density = sqrt(uv_area * res²) / sqrt(mesh_area).
        """
        import math

        mesh = obj.data
        uv_layer = mesh.uv_layers.active

        # Mesh area in world space (factoring obj.scale)
        scale_factor = (obj.scale.x * obj.scale.y * obj.scale.z) ** (1.0 / 3.0)
        mesh_area = sum(p.area for p in mesh.polygons) * scale_factor * scale_factor

        # UV area: triangulate each polygon's UV loop and sum
        uv_area = 0.0
        for poly in mesh.polygons:
            li_first = poly.loop_start
            n = poly.loop_total
            if n < 3:
                continue
            uv0 = uv_layer.data[li_first].uv
            for k in range(1, n - 1):
                uv1 = uv_layer.data[li_first + k].uv
                uv2 = uv_layer.data[li_first + k + 1].uv
                # Triangle area = 0.5 * |cross|
                cross = (uv1.x - uv0.x) * (uv2.y - uv0.y) - (uv2.x - uv0.x) * (uv1.y - uv0.y)
                uv_area += abs(cross) * 0.5

        if mesh_area < 1e-9 or uv_area < 1e-9:
            return mesh_area, uv_area, 0.0

        # density (px/m): sqrt(uv_area_in_pixels²) / sqrt(mesh_area_in_m²)
        density = math.sqrt(uv_area * resolution * resolution) / math.sqrt(mesh_area)
        return mesh_area, uv_area, density

    def execute(self, context):
        obj = _active_mesh(context)
        prior_mode = context.mode
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh_area, uv_area, current_density = self._compute_density(
            obj, self.target_resolution
        )
        if current_density <= 0:
            self.report(
                {'ERROR'},
                "Could not compute density (mesh or UV area too small)",
            )
            return {'CANCELLED'}

        if not self.apply_scale:
            self.report(
                {'INFO'},
                f"Current density: {current_density:.1f} px/m "
                f"(mesh {mesh_area:.3f} m², UV {uv_area:.3f} unit²) "
                f"@ {self.target_resolution}px",
            )
            return {'FINISHED'}

        scale = self.target_density / current_density
        uv_layer = obj.data.uv_layers.active

        # Scale around UV centroid so the layout stays centred-ish
        cx = sum(uv.uv.x for uv in uv_layer.data) / max(1, len(uv_layer.data))
        cy = sum(uv.uv.y for uv in uv_layer.data) / max(1, len(uv_layer.data))
        for uv in uv_layer.data:
            uv.uv = ((uv.uv.x - cx) * scale + cx, (uv.uv.y - cy) * scale + cy)

        if prior_mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')

        self.report(
            {'INFO'},
            f"Density {current_density:.1f} → {self.target_density:.1f} px/m "
            f"(scale ×{scale:.3f}). Pack Islands recommended after this",
        )
        return {'FINISHED'}


_classes = (
    PIPESCULPT_OT_uv_auto_seam,
    PIPESCULPT_OT_uv_smart_unwrap,
    PIPESCULPT_OT_uv_checker_toggle,
    PIPESCULPT_OT_uv_stretch_toggle,
    PIPESCULPT_OT_uv_symmetry_mirror,
    PIPESCULPT_OT_uv_texel_density,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
