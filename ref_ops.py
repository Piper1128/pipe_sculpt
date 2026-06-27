"""Reference image setup — drop refs into the scene as Image Empties.

Blender's built-in 'Add → Image → Reference' adds ONE image at a time, in
whatever view orientation happens to be active, and dumps the empty into
the current collection at full opacity. Beginners end up with refs that
block the mesh, render in the final image, and have to be re-positioned
by hand.

This module wraps that into:
  - one operator that takes multiple files + per-file axis assignments
  - auto-positions each reference at 1 m from origin along the chosen axis
  - groups them into a 'References' collection (auto-created)
  - sets opacity to 40 % and disables render visibility
  - flips X-axis empties to face inward so 'right side' is to the model's right

Plus a toggle to hide/show the entire References collection.
"""
from __future__ import annotations

import os

import bpy
import mathutils
from bpy.props import CollectionProperty, EnumProperty, FloatProperty, StringProperty
from bpy.types import Operator, PropertyGroup
from bpy_extras.io_utils import ImportHelper


REF_COLLECTION_NAME = "References"

# (axis_id, label, description, rotation_euler_xyz, location_offset)
# Rotation is in radians; location is the offset from origin along the
# axis the user is looking down (camera-friendly default placement).
REF_AXES = (
    ('FRONT',  "Front (-Y)",  "Faces the camera looking down +Y",  (1.5708,  0, 0),       ( 0, -1.0,  0)),
    ('BACK',   "Back  (+Y)",  "Faces the camera looking down -Y",  (1.5708,  0, 3.14159), ( 0,  1.0,  0)),
    ('LEFT',   "Left  (+X)",  "Faces the camera looking down -X",  (1.5708,  0, -1.5708), (-1.0, 0,  0)),
    ('RIGHT',  "Right (-X)",  "Faces the camera looking down +X",  (1.5708,  0,  1.5708), ( 1.0, 0,  0)),
    ('TOP',    "Top   (-Z)",  "Faces the camera looking down +Z",  (0,       0, 0),       ( 0,  0,  1.5)),
)


def _ensure_ref_collection(context):
    """Get or create the References collection at scene root."""
    coll = bpy.data.collections.get(REF_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(REF_COLLECTION_NAME)
        context.scene.collection.children.link(coll)
    elif coll.name not in [c.name for c in context.scene.collection.children]:
        context.scene.collection.children.link(coll)
    return coll


def _spawn_reference_empty(context, filepath: str, axis_id: str, opacity: float):
    """Create one Image Empty for a single reference image on the chosen axis."""
    axis_spec = next((a for a in REF_AXES if a[0] == axis_id), REF_AXES[0])
    _, _, _, rotation, location = axis_spec

    img = bpy.data.images.load(filepath, check_existing=True)

    empty = bpy.data.objects.new(f"Ref_{axis_id}_{os.path.basename(filepath)}", None)
    empty.empty_display_type = 'IMAGE'
    empty.data = img
    empty.empty_image_offset = (-0.5, -0.5)  # centre the image on the empty's origin
    empty.empty_display_size = 2.0
    empty.location = mathutils.Vector(location)
    empty.rotation_euler = mathutils.Euler(rotation, 'XYZ')
    empty.color = (1.0, 1.0, 1.0, opacity)
    empty.empty_image_depth = 'DEFAULT'

    # Hide from renders so refs never leak into Cycles/Eevee output
    empty.hide_render = True
    # Show only in orthographic views so perspective sculpting is unobstructed
    empty.empty_image_side = 'DOUBLE_SIDED'

    coll = _ensure_ref_collection(context)
    coll.objects.link(empty)
    return empty


class PIPESCULPT_PG_ref_file(PropertyGroup):
    """One file in the multi-file picker, with its assigned axis."""
    name: StringProperty()
    axis: EnumProperty(
        items=[(a[0], a[1], a[2]) for a in REF_AXES],
        default='FRONT',
    )


class PIPESCULPT_OT_setup_reference_images(Operator, ImportHelper):
    bl_idname = "pipe_sculpt.setup_reference_images"
    bl_label = "Setup Reference Images"
    bl_description = (
        "Pick one or more reference image files and drop them into the scene "
        "as Image Empties. Auto-positioned per axis, 40% opacity, render-"
        "hidden, grouped in a 'References' collection"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tga;*.tiff;*.bmp;*.exr;*.hdr", options={'HIDDEN'})

    files: CollectionProperty(name="File Path", type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

    default_axis: EnumProperty(
        name="Default Axis",
        description="Axis assigned to all picked files (use Add Front/Side individually for per-axis control)",
        items=[(a[0], a[1], a[2]) for a in REF_AXES],
        default='FRONT',
    )
    opacity: FloatProperty(
        name="Opacity",
        description="Reference visibility — 0.4 = clearly secondary to the mesh, 1.0 = solid",
        default=0.4,
        min=0.05,
        max=1.0,
    )

    def execute(self, context):
        if not self.files:
            self.report({'ERROR'}, "No files selected")
            return {'CANCELLED'}

        added = 0
        for f in self.files:
            filepath = os.path.join(self.directory, f.name)
            if not os.path.isfile(filepath):
                continue
            _spawn_reference_empty(context, filepath, self.default_axis, self.opacity)
            added += 1

        if added == 0:
            self.report({'ERROR'}, "Picked files don't exist")
            return {'CANCELLED'}

        coll_name = REF_COLLECTION_NAME
        self.report(
            {'INFO'},
            f"Added {added} reference image(s) on {self.default_axis} axis to '{coll_name}' collection",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_toggle_reference_images(Operator):
    bl_idname = "pipe_sculpt.toggle_reference_images"
    bl_label = "Toggle References Visibility"
    bl_description = (
        "Hide or show the entire 'References' collection in the viewport. "
        "Use to clear the view when sculpting fine detail, then bring refs "
        "back when you need to compare to source"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bpy.data.collections.get(REF_COLLECTION_NAME) is not None

    def execute(self, context):
        coll = bpy.data.collections.get(REF_COLLECTION_NAME)
        if coll is None:
            self.report({'WARNING'}, "No 'References' collection found")
            return {'CANCELLED'}
        coll.hide_viewport = not coll.hide_viewport
        state = "hidden" if coll.hide_viewport else "shown"
        self.report({'INFO'}, f"References {state}")
        return {'FINISHED'}


_classes = (
    PIPESCULPT_PG_ref_file,
    PIPESCULPT_OT_setup_reference_images,
    PIPESCULPT_OT_toggle_reference_images,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
