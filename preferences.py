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


class SCULPTKIT_PG_pie_slot(PropertyGroup):
    name: StringProperty(
        name="Brush Asset Name",
        description="Name of the brush asset inside the essentials brush library",
        default="",
    )


class SCULPTKIT_OT_reset_slots(Operator):
    bl_idname = "sculpt_kit.reset_slots"
    bl_label = "Reset Brush Slots to Defaults"
    bl_description = "Discard all custom slot names and restore SculptKit's default brush mappings"
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        _rebuild_slots(prefs)
        self.report({'INFO'}, "Brush slots reset to defaults")
        return {'FINISHED'}


class SCULPTKIT_Preferences(AddonPreferences):
    bl_idname = __package__

    defaults_version: IntProperty(default=0)
    primary_slots: CollectionProperty(type=SCULPTKIT_PG_pie_slot)
    secondary_slots: CollectionProperty(type=SCULPTKIT_PG_pie_slot)

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
        col.prop(self, "export_triangulate")
        col.prop(self, "export_apply_modifiers")

        box = layout.box()
        header = box.row(align=True)
        header.label(text=f"Brush Slots (defaults v{self.defaults_version})", icon='BRUSH_DATA')
        header.operator("sculpt_kit.reset_slots", text="Reset to Defaults", icon='LOOP_BACK')

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
    needs_rebuild = (
        prefs.defaults_version < CURRENT_DEFAULTS_VERSION
        or len(prefs.primary_slots) != len(PRIMARY_DEFAULTS)
        or len(prefs.secondary_slots) != len(SECONDARY_DEFAULTS)
    )
    if needs_rebuild:
        _rebuild_slots(prefs)


def get_prefs(context=None):
    ctx = context or bpy.context
    prefs = ctx.preferences.addons[__package__].preferences
    _ensure_slots(prefs)
    return prefs


_classes = (
    SCULPTKIT_PG_pie_slot,
    SCULPTKIT_OT_reset_slots,
    SCULPTKIT_Preferences,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
