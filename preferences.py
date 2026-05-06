import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
    CollectionProperty,
)
from bpy.types import AddonPreferences, Operator, PropertyGroup


ESSENTIALS_LIB = "ESSENTIALS"
ESSENTIALS_BRUSH_FILE = "brushes/essentials_brushes-mesh_sculpt.blend"


def brush_asset_id(name: str) -> str:
    return f"{ESSENTIALS_BRUSH_FILE}/Brush/{name}"


CURRENT_DEFAULTS_VERSION = 3

PRIMARY_DEFAULTS = (
    "Draw",
    "Clay Strips",
    "Grab",
    "Smooth",
    "Crease Sharp",
    "Inflate/Deflate",
    "Flatten/Contrast",
    "Mask",
)

SECONDARY_DEFAULTS = (
    "Clay",
    "Blob",
    "Snake Hook",
    "Pinch/Magnify",
    "Scrape/Fill",
    "Fill/Deepen",
    "Elastic Grab",
    "Draw Sharp",
)


class PIPESCULPT_PG_pie_slot(PropertyGroup):
    name: StringProperty(
        name="Brush Asset Name",
        description="Name of the brush asset inside the essentials brush library",
        default="",
    )


class PIPESCULPT_OT_reset_slots(Operator):
    bl_idname = "pipe_sculpt.reset_slots"
    bl_label = "Reset Brush Slots to Defaults"
    bl_description = "Discard all custom slot names and restore PipeSculpt's default brush mappings"
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        _rebuild_slots(prefs)
        self.report({'INFO'}, "Brush slots reset to defaults")
        return {'FINISHED'}


class PIPESCULPT_Preferences(AddonPreferences):
    bl_idname = __package__

    defaults_version: IntProperty(default=0)
    primary_slots: CollectionProperty(type=PIPESCULPT_PG_pie_slot)
    secondary_slots: CollectionProperty(type=PIPESCULPT_PG_pie_slot)

    target_faces_character: IntProperty(
        name="Character",
        description="Quadriflow target face count for full-body characters",
        default=22000,
        min=1000,
        max=200000,
    )
    target_faces_bust: IntProperty(
        name="Bust / Face",
        description="Quadriflow target face count for busts and faces",
        default=14000,
        min=1000,
        max=200000,
    )
    target_faces_prop: IntProperty(
        name="Prop",
        description="Quadriflow target face count for generic props",
        default=8000,
        min=500,
        max=200000,
    )

    # Bake settings
    default_bake_resolution: EnumProperty(
        name="Default Bake Resolution",
        items=(
            ('1024', "1K", ""),
            ('2048', "2K", ""),
            ('4096', "4K", ""),
            ('8192', "8K", ""),
        ),
        default='2048',
    )
    bake_save_to_disk: BoolProperty(
        name="Save bakes to disk",
        description="Save baked PNGs to <blend_dir>/textures/. Pack into .blend if no save path",
        default=True,
    )
    bake_use_cage: BoolProperty(
        name="Use cage object",
        description="Auto-generate a cage object for bake (eliminates ray-cast artefacts)",
        default=True,
    )

    # Export settings
    export_axis_mode: EnumProperty(
        name="Axis mode",
        description=(
            "How Blender Z-up is converted to Unity Y-up. BAKED = bake -90° X "
            "into mesh data, no Unity importer tweak required. DECLARED = "
            "declare Y-up in FBX header, requires 'Bake Axis Conversion' = ON "
            "on the Unity 6 importer"
        ),
        items=(
            ('BAKED', "Baked (default Unity importer)", ""),
            ('DECLARED', "Declared (Bake Axis Conversion ON)", ""),
        ),
        default='BAKED',
    )
    export_triangulate: BoolProperty(
        name="Triangulate before export",
        description="Add a sticky Triangulate modifier so Unity does not re-triangulate post-import",
        default=True,
    )
    export_apply_modifiers: BoolProperty(
        name="Apply modifiers on export",
        description="Bake all modifiers into mesh data (Armature stays as deformer)",
        default=True,
    )

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Quadriflow Targets", icon='MOD_REMESH')
        col = box.column(align=True)
        col.prop(self, "target_faces_character")
        col.prop(self, "target_faces_bust")
        col.prop(self, "target_faces_prop")

        box = layout.box()
        box.label(text="Bake", icon='RENDER_STILL')
        col = box.column(align=True)
        col.prop(self, "default_bake_resolution")
        col.prop(self, "bake_save_to_disk")
        col.prop(self, "bake_use_cage")

        box = layout.box()
        box.label(text="Unity FBX Export", icon='EXPORT')
        col = box.column(align=True)
        col.prop(self, "export_axis_mode")
        col.prop(self, "export_triangulate")
        col.prop(self, "export_apply_modifiers")

        box = layout.box()
        header = box.row(align=True)
        header.label(text=f"Brush Slots (defaults v{self.defaults_version})", icon='BRUSH_DATA')
        header.operator("pipe_sculpt.reset_slots", text="Reset to Defaults", icon='LOOP_BACK')

        sub = box.box()
        sub.label(text="Primary Pie (Q)")
        for i, slot in enumerate(self.primary_slots):
            row = sub.row(align=True)
            row.label(text=f"Slot {i + 1}")
            row.prop(slot, "name", text="")

        sub = box.box()
        sub.label(text="Secondary Pie (Shift+Q)")
        for i, slot in enumerate(self.secondary_slots):
            row = sub.row(align=True)
            row.label(text=f"Slot {i + 1}")
            row.prop(slot, "name", text="")


def _rebuild_slots(prefs):
    prefs.primary_slots.clear()
    for n in PRIMARY_DEFAULTS:
        prefs.primary_slots.add().name = n
    prefs.secondary_slots.clear()
    for n in SECONDARY_DEFAULTS:
        prefs.secondary_slots.add().name = n
    prefs.defaults_version = CURRENT_DEFAULTS_VERSION


def _ensure_slots(prefs):
    # Only seed slots when the user has none yet (first install) or when slot
    # counts diverge from the defaults (impossible to render the pies). A
    # version bump alone must NOT wipe a user's customised slot names — they
    # can opt in via the explicit "Reset to Defaults" button in preferences.
    needs_initial_seed = (
        len(prefs.primary_slots) != len(PRIMARY_DEFAULTS)
        or len(prefs.secondary_slots) != len(SECONDARY_DEFAULTS)
    )
    if needs_initial_seed:
        _rebuild_slots(prefs)


def get_prefs(context=None):
    ctx = context or bpy.context
    prefs = ctx.preferences.addons[__package__].preferences
    _ensure_slots(prefs)
    return prefs


_classes = (
    PIPESCULPT_PG_pie_slot,
    PIPESCULPT_OT_reset_slots,
    PIPESCULPT_Preferences,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
