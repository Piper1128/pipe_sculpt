import bpy
from bpy.props import StringProperty
from bpy.types import Menu, Operator

from . import preferences as prefs_mod


class SCULPTKIT_OT_activate_brush(Operator):
    bl_idname = "sculpt_kit.activate_brush"
    bl_label = "Activate Brush"
    bl_options = {'INTERNAL'}

    asset_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return context.mode == 'SCULPT'

    def execute(self, context):
        if not self.asset_name:
            self.report({'WARNING'}, "No brush asset name provided")
            return {'CANCELLED'}
        try:
            bpy.ops.brush.asset_activate(
                asset_library_type=prefs_mod.ESSENTIALS_LIB,
                asset_library_identifier="",
                relative_asset_identifier=prefs_mod.brush_asset_id(self.asset_name),
            )
        except RuntimeError as e:
            self.report({'WARNING'}, f"Brush '{self.asset_name}' not found: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}


def _draw_pie(layout, slots):
    pie = layout.menu_pie()
    for slot in slots:
        label = slot.name if slot.name else "—"
        op = pie.operator("sculpt_kit.activate_brush", text=label)
        op.asset_name = slot.name


class SCULPTKIT_MT_pie_primary(Menu):
    bl_idname = "SCULPTKIT_MT_pie_primary"
    bl_label = "SculptKit — Primary"

    def draw(self, context):
        prefs = prefs_mod.get_prefs(context)
        _draw_pie(self.layout, prefs.primary_slots)


class SCULPTKIT_MT_pie_secondary(Menu):
    bl_idname = "SCULPTKIT_MT_pie_secondary"
    bl_label = "SculptKit — Secondary"

    def draw(self, context):
        prefs = prefs_mod.get_prefs(context)
        _draw_pie(self.layout, prefs.secondary_slots)


_classes = (
    SCULPTKIT_OT_activate_brush,
    SCULPTKIT_MT_pie_primary,
    SCULPTKIT_MT_pie_secondary,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
