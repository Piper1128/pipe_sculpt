"""Quick color palette — bpy adapter for palette_core."""
from __future__ import annotations

import bpy
from bpy.props import FloatVectorProperty, IntProperty
from bpy.types import Operator, Panel

from . import palette_core


SCENE_PROP = "pipe_sculpt_palette_blob"


def _load_palette(scene) -> list[tuple[float, float, float]]:
    blob = scene.get(SCENE_PROP, "")
    return palette_core.deserialize_palette(blob)


def _save_palette(scene, palette: list[tuple[float, float, float]]) -> None:
    scene[SCENE_PROP] = palette_core.serialize_palette(palette)


class PIPESCULPT_OT_palette_set_slot(Operator):
    bl_idname = "pipe_sculpt.palette_set_slot"
    bl_label = "Set Palette Slot"
    bl_description = "Store the current brush colour in this palette slot"
    bl_options = {'REGISTER', 'UNDO'}

    slot_index: IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        # Available in texture paint mode where we have a brush colour
        return context.mode == 'PAINT_TEXTURE'

    def execute(self, context):
        # Read current brush colour via tool settings
        ts = context.tool_settings.image_paint
        brush = ts.brush
        if brush is None:
            self.report({'WARNING'}, "No active brush — pick one first")
            return {'CANCELLED'}
        col = brush.color
        palette = _load_palette(context.scene)
        palette = palette_core.update_slot(palette, self.slot_index, (col[0], col[1], col[2]))
        _save_palette(context.scene, palette)
        self.report({'INFO'}, f"Stored colour in slot {self.slot_index + 1}")
        return {'FINISHED'}


class PIPESCULPT_OT_palette_apply_slot(Operator):
    bl_idname = "pipe_sculpt.palette_apply_slot"
    bl_label = "Apply Palette Slot"
    bl_description = "Set the current brush colour from this palette slot"
    bl_options = {'REGISTER', 'UNDO'}

    slot_index: IntProperty(default=0, min=0)

    @classmethod
    def poll(cls, context):
        return context.mode == 'PAINT_TEXTURE'

    def execute(self, context):
        palette = _load_palette(context.scene)
        if self.slot_index < 0 or self.slot_index >= palette_core.MAX_SLOTS:
            self.report({'ERROR'}, f"Slot index {self.slot_index} out of range")
            return {'CANCELLED'}
        color = palette[self.slot_index]
        ts = context.tool_settings.image_paint
        brush = ts.brush
        if brush is None:
            self.report({'WARNING'}, "No active brush — pick one first")
            return {'CANCELLED'}
        brush.color = color
        self.report({'INFO'}, f"Brush colour set from slot {self.slot_index + 1}")
        return {'FINISHED'}


class PIPESCULPT_OT_palette_clear(Operator):
    bl_idname = "pipe_sculpt.palette_clear"
    bl_label = "Clear Palette"
    bl_description = "Reset the palette to all-neutral-grey"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _save_palette(context.scene, palette_core.empty_palette())
        self.report({'INFO'}, "Palette reset")
        return {'FINISHED'}


class PIPESCULPT_PT_palette(Panel):
    bl_idname = "PIPESCULPT_PT_palette"
    bl_label = "Quick Palette"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 20

    @classmethod
    def poll(cls, context):
        return context.mode == 'PAINT_TEXTURE'

    def draw(self, context):
        layout = self.layout
        palette = _load_palette(context.scene)

        # 4x4 grid of colour swatches; click sets, shift-click stores
        for row in range(4):
            row_layout = layout.row(align=True)
            row_layout.scale_y = 1.4
            for col in range(4):
                idx = row * 4 + col
                sub = row_layout.row(align=True)
                color = palette[idx]
                # Apply button (colored)
                op = sub.operator(
                    "pipe_sculpt.palette_apply_slot",
                    text=f"{idx + 1}",
                    icon='NONE',
                )
                op.slot_index = idx
                # Store button next to it
                store = sub.operator(
                    "pipe_sculpt.palette_set_slot",
                    text="",
                    icon='ADD',
                )
                store.slot_index = idx

        layout.separator()
        layout.operator("pipe_sculpt.palette_clear", icon='X')


_classes = (
    PIPESCULPT_OT_palette_set_slot,
    PIPESCULPT_OT_palette_apply_slot,
    PIPESCULPT_OT_palette_clear,
    PIPESCULPT_PT_palette,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
