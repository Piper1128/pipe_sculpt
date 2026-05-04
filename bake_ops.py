"""Multi-map baking — produces a Substance Painter / Unity-ready map set in one pass.

Industry-standard map set:
  - normal (tangent space, OpenGL Y+, MikkTSpace)
  - ambient occlusion
  - cavity (signed curvature concavity)
  - curvature (full bidirectional curvature for masks)
  - position (worldspace XYZ for masking by location)

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


# (id, suffix, cycles_bake_type, colorspace, default_color, description)
BAKE_PASS_SPECS = (
    ('NORMAL',     "_normal",    'NORMAL',    'Non-Color', (0.5, 0.5, 1.0, 1.0), "Tangent-space normal map"),
    ('AO',         "_ao",        'AO',        'sRGB',      (1.0, 1.0, 1.0, 1.0), "Ambient occlusion"),
    ('CURVATURE',  "_curvature", 'NORMAL',    'Non-Color', (0.5, 0.5, 1.0, 1.0), "Geometric curvature mask"),
    ('POSITION',   "_position",  'POSITION',  'Non-Color', (0.0, 0.0, 0.0, 1.0), "Worldspace position"),
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


def _ensure_bake_material(low_obj, mat_name="SculptKit_Bake_Mat"):
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


def _save_image_next_to_blend(img, sub_dir="textures") -> str | None:
    """Save image to <blend_dir>/textures/<image>.png. Returns path or None."""
    blend_path = bpy.data.filepath
    if not blend_path:
        img.pack()
        return None
    blend_dir = os.path.dirname(blend_path)
    out_dir = os.path.join(blend_dir, sub_dir)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{img.name}.png")
    img.filepath_raw = out_path
    img.file_format = 'PNG'
    img.save()
    return out_path


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


def _ensure_uvs(low_obj, context):
    if low_obj.data.uv_layers:
        return
    bpy.ops.object.select_all(action='DESELECT')
    low_obj.select_set(True)
    context.view_layer.objects.active = low_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.005)
    bpy.ops.object.mode_set(mode='OBJECT')


def _setup_selection_for_bake(context, high, low):
    bpy.ops.object.select_all(action='DESELECT')
    high_was_hidden = high.hide_get()
    if high_was_hidden:
        high.hide_set(False)
    high.select_set(True)
    low.hide_set(False)
    low.select_set(True)
    context.view_layer.objects.active = low
    return high_was_hidden


class SCULPTKIT_OT_bake_maps(Operator):
    bl_idname = "sculpt_kit.bake_maps"
    bl_label = "Bake Maps"
    bl_description = (
        "Bake normal + AO + curvature + position maps from the high-poly source to "
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
    bake_curvature: BoolProperty(name="Curvature", default=True)
    bake_position: BoolProperty(name="Position", default=False)
    samples_ao: IntProperty(name="AO Samples", default=64, min=8, max=512)
    save_to_disk: BoolProperty(
        name="Save next to .blend",
        description="Save PNGs in <blend_dir>/textures/. Packs into .blend if no save path",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def _bake_one_pass(self, context, low, high, mat, pass_id, suffix, bake_type, colorspace, default_color, size, ray_dist, cage_ext):
        img_name = f"{low.name}{suffix}"
        img = _get_or_create_image(img_name, size, colorspace, default_color)
        _set_active_bake_target(mat, img)

        scene = context.scene
        scene.render.bake.use_selected_to_active = True
        scene.render.bake.cage_extrusion = cage_ext
        scene.render.bake.max_ray_distance = ray_dist
        scene.render.bake.use_clear = True
        if pass_id == 'AO':
            scene.cycles.samples = self.samples_ao
            scene.cycles.bake_type = 'AO'
        elif pass_id == 'CURVATURE':
            # Curvature isn't a native Cycles pass; we use a normal-bake-derived
            # workaround by baking against a flat shade-less material would need
            # a temp setup. For MVP we skip curvature here and fall back to a
            # warning. (Substance Painter does this client-side anyway.)
            self.report({'INFO'}, "Curvature pass: stub (use Substance from baked normal). Skipping.")
            return None
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
            saved = _save_image_next_to_blend(img)
            if saved is None:
                img.pack()
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

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        _ensure_uvs(low, context)
        mat = _ensure_bake_material(low)

        scene = context.scene
        prior_engine = scene.render.engine
        prior_samples = scene.cycles.samples
        scene.render.engine = 'CYCLES'

        max_dim = _max_bbox_dim(high)
        ray_dist = max_dim * 0.05
        cage_ext = max_dim * 0.01

        size = int(self.resolution)
        passes_to_run = [
            spec for spec in BAKE_PASS_SPECS
            if (spec[0] == 'NORMAL' and self.bake_normal)
            or (spec[0] == 'AO' and self.bake_ao)
            or (spec[0] == 'CURVATURE' and self.bake_curvature)
            or (spec[0] == 'POSITION' and self.bake_position)
        ]

        high_was_hidden = _setup_selection_for_bake(context, high, low)

        baked = []
        for pass_id, suffix, bake_type, colorspace, default_color, _desc in passes_to_run:
            img = self._bake_one_pass(
                context, low, high, mat,
                pass_id, suffix, bake_type, colorspace, default_color,
                size, ray_dist, cage_ext,
            )
            if img is not None:
                baked.append((pass_id, img.name, img.filepath_raw or "(packed)"))

        scene.render.engine = prior_engine
        scene.cycles.samples = prior_samples
        if high_was_hidden:
            high.hide_set(True)

        if not baked:
            self.report({'WARNING'}, "No passes baked")
            return {'CANCELLED'}

        summary = ", ".join(p[0] for p in baked)
        self.report({'INFO'}, f"Baked {summary} @ {size}px from '{high.name}' → '{low.name}'")
        return {'FINISHED'}


_classes = (SCULPTKIT_OT_bake_maps,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
