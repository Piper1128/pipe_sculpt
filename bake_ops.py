"""Multi-map baking — produces a Substance Painter / Unity-ready map set in one pass.

Industry-standard map set:
  - normal (tangent space, OpenGL Y+, MikkTSpace, R=+X G=+Y B=+Z)
  - ambient occlusion
  - position (worldspace XYZ for masking by location)

Curvature is intentionally not baked here: Cycles has no native curvature pass,
and Substance Painter generates a higher-quality curvature map from the baked
normal client-side. Adding a fake curvature pass produced misleading output.

Each pass routes to its own image; the user gets <name>_normal, <name>_ao, etc.
Saved to disk next to the .blend file when the file is saved, packed otherwise.
"""
from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy.types import Operator


BAKE_RESOLUTIONS = (
    ('1024', "1K (1024)", "1024x1024 — fast preview / mobile"),
    ('2048', "2K (2048)", "2048x2048 — standard hero asset"),
    ('4096', "4K (4096)", "4096x4096 — high-detail hero / film"),
    ('8192', "8K (8192)", "8192x8192 — VFX, very slow"),
)


# (id, suffix, colorspace, default_color, description)
# The cycles bake type is derived from the id at bake time — see _bake_one_pass.
BAKE_PASS_SPECS = (
    ('NORMAL',   "_normal",   'Non-Color', (0.5, 0.5, 1.0, 1.0), "Tangent-space normal map"),
    ('AO',       "_ao",       'sRGB',      (1.0, 1.0, 1.0, 1.0), "Ambient occlusion"),
    ('POSITION', "_position", 'Non-Color', (0.0, 0.0, 0.0, 1.0), "Worldspace position"),
)


def _get_or_create_image(name: str, size: int, colorspace: str, default_color):
    img = bpy.data.images.get(name)
    if img is not None:
        # Resize if needed
        if img.size[0] != size or img.size[1] != size:
            img.scale(size, size)
        return img
    img = bpy.data.images.new(
        name, width=size, height=size, alpha=False, float_buffer=False
    )
    img.colorspace_settings.name = colorspace
    img.generated_color = default_color
    return img


def _ensure_bake_material(low_obj):
    """Get or create a per-mesh bake material.

    Per-mesh naming (was a global 'PipeSculpt_Bake_Mat') so each baked
    low-poly keeps its own active texture node — multiple baked characters
    in one .blend don't stomp on each other's viewport-render preview.
    """
    mat_name = f"{low_obj.name}_BakeMat"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
    if mat.name not in [m.name for m in low_obj.data.materials if m]:
        low_obj.data.materials.append(mat)
    return mat


def _set_active_bake_target(mat, image):
    """Make sure an image-texture node bound to `image` exists and is active."""
    nodes = mat.node_tree.nodes
    tex_node = next(
        (n for n in nodes if n.type == 'TEX_IMAGE' and n.image == image), None
    )
    if tex_node is None:
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.image = image
    nodes.active = tex_node
    tex_node.select = True


def _save_image_next_to_blend(img, sub_dir="textures") -> tuple[str | None, bool]:
    """Save image to <blend_dir>/textures/<image>.png.

    Returns (path, overwrote_existing). overwrote_existing lets the operator
    surface a soft warning when a re-bake replaced a previous PNG, so the
    user knows their old file is gone.
    """
    blend_path = bpy.data.filepath
    if not blend_path:
        img.pack()
        return None, False
    blend_dir = os.path.dirname(blend_path)
    out_dir = os.path.join(blend_dir, sub_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{img.name}.png")
    overwrote = os.path.exists(out_path)
    img.filepath_raw = out_path
    img.file_format = 'PNG'
    img.save()
    return out_path, overwrote


def _build_cage_object(low_obj, extrusion: float):
    """Duplicate low_obj and offset each vertex outward by `extrusion`.

    A dedicated cage eliminates the artefacts simple cage_extrusion (a uniform
    offset at bake time) introduces on soft-curvature surfaces. We compute the
    displacement via bmesh so face-area-weighted vertex normals are guaranteed
    fresh, which matters when low_obj's mesh data was just replaced (e.g. by
    quadriflow_remesh) and `vertices[i].normal` may not yet be valid.
    """
    import bmesh

    cage_data = low_obj.data.copy()
    cage = bpy.data.objects.new(f"{low_obj.name}_bake_cage", cage_data)
    bpy.context.collection.objects.link(cage)
    cage.matrix_world = low_obj.matrix_world.copy()

    bm = bmesh.new()
    bm.from_mesh(cage_data)
    bm.normal_update()
    for v in bm.verts:
        v.co = v.co + v.normal * extrusion
    bm.to_mesh(cage_data)
    bm.free()
    cage_data.update()

    # Display as wireframe so the cage doesn't visually fight the low-poly
    # while bake runs. Can't use hide_viewport=True because that would remove
    # the object from the depsgraph and Cycles would fail to find the cage
    # for ray-casting. hide_select=True keeps the user from clicking it.
    cage.hide_render = True
    cage.hide_select = True
    cage.display_type = 'WIRE'
    return cage


def _resolve_high_poly(context, low):
    """Pair the active low-poly with a high-poly source.

    Priority:
      1. low.name == '<X>_retopo' -> object 'X'
      2. Any other selected mesh that isn't low
    """
    if low.name.endswith("_retopo"):
        base = low.name[: -len("_retopo")]
        obj = bpy.data.objects.get(base)
        if obj is not None and obj.type == 'MESH':
            return obj
    for o in context.selected_objects:
        if o is not low and o.type == 'MESH':
            return o
    return None


def _max_bbox_dim(obj) -> float:
    dims = obj.dimensions
    return max(dims.x, dims.y, dims.z, 0.001)


def _ensure_uvs(low_obj, context, bake_resolution: int):
    """Smart-project UVs if missing, with margin scaled to bake resolution.

    Industry-standard bake-bleed protection is ~8 pixels constant. Smart
    Project's island_margin is in 0..1 UV space, so 8 / resolution gives
    the right pixel margin regardless of 1K/2K/4K/8K target.
    """
    if low_obj.data.uv_layers:
        return
    margin = 8.0 / max(bake_resolution, 64)
    bpy.ops.object.select_all(action='DESELECT')
    low_obj.select_set(True)
    context.view_layer.objects.active = low_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=margin)
    bpy.ops.object.mode_set(mode='OBJECT')


def _setup_selection_for_bake(context, high, low):
    """Snapshot the prior hide state of both objects so we can restore later."""
    bpy.ops.object.select_all(action='DESELECT')
    high_was_hidden = high.hide_get()
    low_was_hidden = low.hide_get()
    if high_was_hidden:
        high.hide_set(False)
    if low_was_hidden:
        low.hide_set(False)
    high.select_set(True)
    low.select_set(True)
    context.view_layer.objects.active = low
    return high_was_hidden, low_was_hidden


class PIPESCULPT_OT_bake_maps(Operator):
    bl_idname = "pipe_sculpt.bake_maps"
    bl_label = "Bake Maps"
    bl_description = (
        "Bake normal + AO (+ optional position) maps from the high-poly source to "
        "the active low-poly mesh. Auto-pairs '<name>_retopo' with '<name>'"
    )
    bl_options = {'REGISTER', 'UNDO'}

    resolution: EnumProperty(
        name="Resolution",
        items=BAKE_RESOLUTIONS,
        default='2048',
    )
    bake_normal: BoolProperty(name="Normal", default=True)
    bake_ao: BoolProperty(name="Ambient Occlusion", default=True)
    bake_position: BoolProperty(name="Position", default=False)
    samples_ao: IntProperty(name="AO Samples", default=64, min=8, max=512)
    save_to_disk: BoolProperty(
        name="Save next to .blend",
        description="Save PNGs in <blend_dir>/textures/. Packs into .blend if no save path",
        default=True,
    )
    use_cage: BoolProperty(
        name="Use Cage Object",
        description="Auto-generate a cage (low-poly + outward vertex-normal offset). "
                    "Eliminates ray-cast artefacts on soft surfaces",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def invoke(self, context, event):
        addon = context.preferences.addons.get(__package__)
        if addon is not None:
            prefs = addon.preferences
            self.resolution = prefs.default_bake_resolution
            self.save_to_disk = prefs.bake_save_to_disk
            self.use_cage = prefs.bake_use_cage
        # Show a properties dialog so the user can pick resolution / passes /
        # cage / save-to-disk before kicking off a multi-minute bake. Used to
        # call execute() directly, which forced people to undo + re-run if a
        # default was wrong.
        return context.window_manager.invoke_props_dialog(self, width=320)

    def _bake_one_pass(self, context, low, high, mat, pass_id, suffix, colorspace, default_color, size, ray_dist, cage_ext, cage_obj, base_samples):
        img_name = f"{low.name}{suffix}"
        img = _get_or_create_image(img_name, size, colorspace, default_color)
        _set_active_bake_target(mat, img)

        scene = context.scene
        scene.render.bake.use_selected_to_active = True
        scene.render.bake.cage_extrusion = cage_ext
        scene.render.bake.max_ray_distance = ray_dist
        scene.render.bake.use_clear = True
        # Tangent-space normal in Mikktspace orientation — the only normal-map
        # convention Unity 6 reads correctly without channel-flipping.
        scene.render.bake.normal_space = 'TANGENT'
        scene.render.bake.normal_r = 'POS_X'
        scene.render.bake.normal_g = 'POS_Y'
        scene.render.bake.normal_b = 'POS_Z'
        if cage_obj is not None:
            scene.render.bake.use_cage = True
            scene.render.bake.cage_object = cage_obj
        else:
            scene.render.bake.use_cage = False
            scene.render.bake.cage_object = None

        # Reset samples to the base each pass so AO's high sample count doesn't
        # leak into NORMAL/POSITION passes that come after it.
        scene.cycles.samples = base_samples
        if pass_id == 'AO':
            scene.cycles.samples = self.samples_ao
            scene.cycles.bake_type = 'AO'
        elif pass_id == 'POSITION':
            scene.cycles.bake_type = 'POSITION'
        else:
            scene.cycles.bake_type = 'NORMAL'

        try:
            bpy.ops.object.bake(type=scene.cycles.bake_type)
        except RuntimeError as e:
            self.report({'ERROR'}, f"Bake {pass_id} failed: {e}")
            return None

        if self.save_to_disk:
            saved, overwrote = _save_image_next_to_blend(img)
            if saved is None:
                img.pack()
            elif overwrote:
                self.report({'INFO'}, f"Replaced existing '{os.path.basename(saved)}'")
        else:
            img.pack()
        return img

    def execute(self, context):
        low = context.active_object
        if low is None or low.type != 'MESH':
            self.report({'ERROR'}, "Active object is not a mesh")
            return {'CANCELLED'}
        high = _resolve_high_poly(context, low)
        if high is None:
            self.report({'ERROR'}, "No high-poly source — name it '<low>_retopo' or select alongside")
            return {'CANCELLED'}

        # Sanity check: high-poly must actually have more geometry than low-poly,
        # otherwise we'd silently bake low→low and produce a flat blue normal map.
        high_verts = len(high.data.vertices)
        low_verts = len(low.data.vertices)
        if high_verts <= low_verts:
            self.report(
                {'ERROR'},
                f"High-poly ({high.name}, {high_verts} verts) is not denser than "
                f"low-poly ({low.name}, {low_verts} verts) — pick the right pair",
            )
            return {'CANCELLED'}

        # Multi-slot meshes only get bake output on faces using the bake mat;
        # other slots receive nothing. Warn so the user can fix or accept.
        bake_mat_name = f"{low.name}_BakeMat"
        non_bake_slots = [
            s for s in low.data.materials if s is not None and s.name != bake_mat_name
        ]
        if non_bake_slots:
            self.report(
                {'WARNING'},
                f"'{low.name}' has {len(non_bake_slots)} non-bake material slot(s). "
                f"Bake will only write to faces using '{bake_mat_name}'",
            )

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        size = int(self.resolution)
        _ensure_uvs(low, context, size)
        mat = _ensure_bake_material(low)

        scene = context.scene
        prior_engine = scene.render.engine
        prior_samples = scene.cycles.samples
        scene.render.engine = 'CYCLES'

        max_dim = _max_bbox_dim(high)
        ray_dist = max_dim * 0.05
        cage_ext = max_dim * 0.01

        passes_to_run = [
            spec for spec in BAKE_PASS_SPECS
            if (spec[0] == 'NORMAL' and self.bake_normal)
            or (spec[0] == 'AO' and self.bake_ao)
            or (spec[0] == 'POSITION' and self.bake_position)
        ]

        cage_obj = None
        if self.use_cage:
            try:
                cage_obj = _build_cage_object(low, cage_ext)
            except Exception as e:
                self.report({'WARNING'}, f"Cage build failed, falling back to extrusion only: {e}")
                cage_obj = None

        high_was_hidden, low_was_hidden = _setup_selection_for_bake(context, high, low)

        baked = []
        for pass_id, suffix, colorspace, default_color, _desc in passes_to_run:
            img = self._bake_one_pass(
                context, low, high, mat,
                pass_id, suffix, colorspace, default_color,
                size, ray_dist, cage_ext, cage_obj, prior_samples,
            )
            if img is not None:
                baked.append((pass_id, img.name, img.filepath_raw or "(packed)"))

        scene.render.engine = prior_engine
        scene.cycles.samples = prior_samples
        if high_was_hidden:
            high.hide_set(True)
        if low_was_hidden:
            low.hide_set(True)
        if cage_obj is not None:
            cage_data = cage_obj.data
            bpy.data.objects.remove(cage_obj, do_unlink=True)
            bpy.data.meshes.remove(cage_data, do_unlink=True)

        if not baked:
            self.report({'WARNING'}, "No passes baked")
            return {'CANCELLED'}

        summary = ", ".join(p[0] for p in baked)
        self.report({'INFO'}, f"Baked {summary} @ {size}px from '{high.name}' → '{low.name}'")
        return {'FINISHED'}


_classes = (PIPESCULPT_OT_bake_maps,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
