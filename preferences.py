import bpy
from bpy.props import IntProperty, StringProperty, CollectionProperty
from bpy.types import AddonPreferences, PropertyGroup


ESSENTIALS_LIB = "ESSENTIALS"
ESSENTIALS_BRUSH_FILE = "brushes/essentials_brushes-mesh_sculpt.blend"


def brush_asset_id(name: str) -> str:
    return f"{ESSENTIALS_BRUSH_FILE}/Brush/{name}"


PRIMARY_DEFAULTS = (
    "Draw",
    "Clay Strips",
    "Grab",
    "Smooth",
    "Crease",
    "Inflate",
    "Flatten",
    "Mask",
)

SECONDARY_DEFAULTS = (
    "Clay",
    "Blob",
    "Snake Hook",
    "Pinch",
    "Scrape",
    "Fill",
    "Elastic Deform",
    "Draw Sharp",
)


class SCULPTKIT_PG_pie_slot(PropertyGroup):
    name: StringProperty(
        name="Brush Asset Name",
        description="Name of the brush asset inside the essentials brush library",
        default="",
    )


class SCULPTKIT_Preferences(AddonPreferences):
    bl_idname = __package__

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

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Quadriflow Targets", icon='MOD_REMESH')
        col = box.column(align=True)
        col.prop(self, "target_faces_character")
        col.prop(self, "target_faces_bust")
        col.prop(self, "target_faces_prop")

        box = layout.box()
        box.label(text="Primary Pie (Q)", icon='BRUSH_DATA')
        for i, slot in enumerate(self.primary_slots):
            row = box.row(align=True)
            row.label(text=f"Slot {i + 1}")
            row.prop(slot, "name", text="")

        box = layout.box()
        box.label(text="Secondary Pie (Shift+Q)", icon='BRUSHES_ALL')
        for i, slot in enumerate(self.secondary_slots):
            row = box.row(align=True)
            row.label(text=f"Slot {i + 1}")
            row.prop(slot, "name", text="")


def _ensure_slots(prefs):
    if len(prefs.primary_slots) != len(PRIMARY_DEFAULTS):
        prefs.primary_slots.clear()
        for default_name in PRIMARY_DEFAULTS:
            slot = prefs.primary_slots.add()
            slot.name = default_name

    if len(prefs.secondary_slots) != len(SECONDARY_DEFAULTS):
        prefs.secondary_slots.clear()
        for default_name in SECONDARY_DEFAULTS:
            slot = prefs.secondary_slots.add()
            slot.name = default_name


def get_prefs(context=None):
    ctx = context or bpy.context
    prefs = ctx.preferences.addons[__package__].preferences
    _ensure_slots(prefs)
    return prefs


_classes = (
    SCULPTKIT_PG_pie_slot,
    SCULPTKIT_Preferences,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
