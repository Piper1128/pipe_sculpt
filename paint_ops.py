"""Texture painting operators — one-click setup for albedo and PBR painting.

Strips the 5+ click setup that catches Blender beginners (material → image
texture node → new image → texture paint mode → active image → brush) into
single operators with sensible defaults.

Operators:
  - PIPESCULPT_OT_paint_setup        : single-channel albedo paint mode
  - PIPESCULPT_OT_paint_setup_pbr    : 4-channel PBR (albedo, normal, rough, metal)
  - PIPESCULPT_OT_paint_save         : save all dirty paint textures to disk
"""
from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator


PAINT_RESOLUTIONS = (
    ('1024', "1K (1024)", "1024×1024 — fast preview / mobile"),
    ('2048', "2K (2048)", "2048×2048 — standard hero asset"),
    ('4096', "4K (4096)", "4096×4096 — high detail"),
)


# (channel_id, suffix, colorspace, default_color, ui_label)
PBR_CHANNELS = (
    ('ALBEDO',    "_albedo",    'sRGB',      (0.5, 0.5, 0.5, 1.0), "Albedo / Base Color"),
    ('NORMAL',    "_normal",    'Non-Color', (0.5, 0.5, 1.0, 1.0), "Normal map"),
    ('ROUGHNESS', "_roughness", 'Non-Color', (0.5, 0.5, 0.5, 1.0), "Roughness"),
    ('METALLIC',  "_metallic",  'Non-Color', (0.0, 0.0, 0.0, 1.0), "Metallic"),
)


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _get_or_create_image(name: str, size: int, colorspace: str, default_color):
    img = bpy.data.images.get(name)
    if img is not None:
        if img.size[0] != size or img.size[1] != size:
            img.scale(size, size)
        return img
    img = bpy.data.images.new(
        name, width=size, height=size, alpha=False, float_buffer=False
    )
    img.colorspace_settings.name = colorspace
    img.generated_color = default_color
    return img


def _ensure_paint_material(low_obj):
    """Get or create a per-mesh paint material with a Principled BSDF."""
    mat_name = f"{low_obj.name}_PaintMat"
    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
    if mat.name not in [m.name for m in low_obj.data.materials if m]:
        low_obj.data.materials.append(mat)
    # Ensure index points at the paint material
    for i, slot in enumerate(low_obj.material_slots):
        if slot.material is mat:
            low_obj.active_material_index = i
            break
    return mat


def _find_principled(mat):
    nt = mat.node_tree
    return next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)


def _wire_image_to_principled(mat, img, channel_id: str):
    """Add an Image Texture node and link it to the appropriate BSDF input.

    For NORMAL we insert a Normal Map node between the image and the BSDF
    so the texture is read as tangent-space normal data, not as a colour.
    """
    nt = mat.node_tree
    bsdf = _find_principled(mat)
    if bsdf is None:
        return None

    # Re-use an existing Image Texture node bound to this image, or make one
    tex = next(
        (n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image is img),
        None,
    )
    if tex is None:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
    tex.label = f"PipeSculpt {channel_id}"

    # Link based on channel
    if channel_id == 'ALBEDO':
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    elif channel_id == 'NORMAL':
        nm = next(
            (n for n in nt.nodes if n.type == 'NORMAL_MAP'),
            None,
        )
        if nm is None:
            nm = nt.nodes.new('ShaderNodeNormalMap')
        nt.links.new(tex.outputs['Color'], nm.inputs['Color'])
        nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
    elif channel_id == 'ROUGHNESS':
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Roughness'])
    elif channel_id == 'METALLIC':
        nt.links.new(tex.outputs['Color'], bsdf.inputs['Metallic'])
    return tex


def _set_active_paint_canvas(mat, img):
    """Mark the Image Texture node bound to `img` as the active paint canvas."""
    nt = mat.node_tree
    tex = next(
        (n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.image is img),
        None,
    )
    if tex is not None:
        nt.nodes.active = tex
        tex.select = True


def _enter_texture_paint_mode(context, obj):
    """Switch to Texture Paint mode on the given mesh."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    if context.mode != 'PAINT_TEXTURE':
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')


class PIPESCULPT_OT_paint_setup(Operator):
    bl_idname = "pipe_sculpt.paint_setup"
    bl_label = "Setup Paint Mode (Albedo)"
    bl_description = (
        "Single-click setup for texture painting: creates a base-color image, "
        "wires it into a new paint material, sets it as the active canvas, "
        "and switches the mesh into Texture Paint mode. Requires UVs"
    )
    bl_options = {'REGISTER', 'UNDO'}

    resolution: EnumProperty(
        name="Resolution",
        items=PAINT_RESOLUTIONS,
        default='2048',
    )

    @classmethod
    def poll(cls, context):
        obj = _active_mesh(context)
        return obj is not None and bool(obj.data.uv_layers)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def execute(self, context):
        obj = _active_mesh(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        size = int(self.resolution)
        img_name = f"{obj.name}_albedo"
        img = _get_or_create_image(img_name, size, 'sRGB', (0.5, 0.5, 0.5, 1.0))

        mat = _ensure_paint_material(obj)
        _wire_image_to_principled(mat, img, 'ALBEDO')
        _set_active_paint_canvas(mat, img)

        _enter_texture_paint_mode(context, obj)

        self.report(
            {'INFO'},
            f"Paint mode ready on '{obj.name}' — albedo {size}×{size}px. "
            "Save with 'Save Painted Textures' before closing the file",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_paint_setup_pbr(Operator):
    bl_idname = "pipe_sculpt.paint_setup_pbr"
    bl_label = "Setup PBR Channels"
    bl_description = (
        "Set up all four PBR channels (albedo, normal, roughness, metallic) "
        "with correct color spaces and BSDF wiring. Albedo becomes the active "
        "paint canvas; switch to other channels via the Image Editor's image "
        "selector or the Active Texture in the Texture panel"
    )
    bl_options = {'REGISTER', 'UNDO'}

    resolution: EnumProperty(
        name="Resolution",
        items=PAINT_RESOLUTIONS,
        default='2048',
    )

    @classmethod
    def poll(cls, context):
        obj = _active_mesh(context)
        return obj is not None and bool(obj.data.uv_layers)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def execute(self, context):
        obj = _active_mesh(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        size = int(self.resolution)
        mat = _ensure_paint_material(obj)
        bsdf = _find_principled(mat)
        if bsdf is None:
            self.report({'ERROR'}, "Paint material has no Principled BSDF — recreate the material")
            return {'CANCELLED'}

        created_imgs = []
        for channel_id, suffix, colorspace, default_color, _label in PBR_CHANNELS:
            img_name = f"{obj.name}{suffix}"
            img = _get_or_create_image(img_name, size, colorspace, default_color)
            _wire_image_to_principled(mat, img, channel_id)
            created_imgs.append((channel_id, img))

        # Albedo is the default paint canvas — most users start there
        albedo_img = next(img for cid, img in created_imgs if cid == 'ALBEDO')
        _set_active_paint_canvas(mat, albedo_img)
        _enter_texture_paint_mode(context, obj)

        self.report(
            {'INFO'},
            f"PBR channels set up on '{obj.name}' — {size}×{size}px each. "
            "Active canvas = albedo; switch via the Texture panel",
        )
        return {'FINISHED'}


def _iter_paint_images(obj):
    """Yield all Image data-blocks referenced by the mesh's paint material."""
    seen: set = set()
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        for n in mat.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image is not None and n.image.name not in seen:
                seen.add(n.image.name)
                yield n.image


class PIPESCULPT_OT_paint_save(Operator):
    bl_idname = "pipe_sculpt.paint_save"
    bl_label = "Save Painted Textures"
    bl_description = (
        "Save all paint textures on the active mesh to <blend_dir>/textures/. "
        "Textures only live in RAM until saved — run this before closing the "
        "file or you lose your paint work"
    )
    bl_options = {'REGISTER'}

    save_clean_too: BoolProperty(
        name="Save Untouched Textures Too",
        description=(
            "Off (default): only save dirty (modified) textures. On: save "
            "every paint texture even if you haven't painted on it yet — "
            "useful for shipping a complete PBR set"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        blend_path = bpy.data.filepath
        if not blend_path:
            self.report(
                {'ERROR'},
                "Blend file isn't saved yet — save the .blend first so we know where to write textures",
            )
            return {'CANCELLED'}

        out_dir = os.path.join(os.path.dirname(blend_path), "textures")
        os.makedirs(out_dir, exist_ok=True)

        saved = 0
        overwritten = 0
        skipped = 0
        for img in _iter_paint_images(obj):
            if not (self.save_clean_too or img.is_dirty or img.packed_file is not None):
                skipped += 1
                continue
            out_path = os.path.join(out_dir, f"{img.name}.png")
            existed = os.path.exists(out_path)
            img.filepath_raw = out_path
            img.file_format = 'PNG'
            try:
                img.save()
                saved += 1
                if existed:
                    overwritten += 1
            except RuntimeError as e:
                self.report({'WARNING'}, f"Failed to save '{img.name}': {e}")
                continue

        if saved == 0:
            self.report({'WARNING'}, "No textures saved (nothing dirty / no paint images found)")
            return {'CANCELLED'}

        msg = f"Saved {saved} texture(s) to {out_dir}"
        if overwritten:
            msg += f" ({overwritten} overwrote existing)"
        if skipped:
            msg += f"; {skipped} clean texture(s) skipped"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


_classes = (
    PIPESCULPT_OT_paint_setup,
    PIPESCULPT_OT_paint_setup_pbr,
    PIPESCULPT_OT_paint_save,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
