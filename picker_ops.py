"""Bone-picker operators + panel — Phase 2 of the animation module.

Born Clean: layout logic lives in picker_core.py (headless-tested); this
file only reads the live armature's bone names, asks picker_core how to
arrange them, and draws clickable buttons. Clicking selects the pose bone
(Shift-click extends the selection), removing the viewport hunt for small
bones.

Works on any armature — picker_core classifies by bone-name pattern, so
PipeSculpt's humanoid / quadruped / bird / mech rigs all get a body-shaped
picker with zero manual setup.
"""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel

from . import picker_core


def _armature_in_pose(context):
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE':
        return None
    if context.mode != 'POSE':
        return None
    return obj


class PIPESCULPT_OT_pick_bone(Operator):
    bl_idname = "pipe_sculpt.pick_bone"
    bl_label = "Pick Bone"
    bl_description = "Select this pose bone. Shift-click to add to the current selection"
    bl_options = {'REGISTER', 'UNDO'}

    bone: StringProperty()
    extend: BoolProperty(default=False)

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        arm = _armature_in_pose(context)
        if arm is None:
            return {'CANCELLED'}
        pb = arm.pose.bones.get(self.bone)
        if pb is None:
            self.report({'WARNING'}, f"No bone '{self.bone}'")
            return {'CANCELLED'}
        if not self.extend:
            for b in arm.pose.bones:
                b.select = False
        pb.select = True
        # Set active bone (drives context.active_pose_bone)
        arm.data.bones.active = pb.bone
        return {'FINISHED'}


class PIPESCULPT_OT_pick_side(Operator):
    bl_idname = "pipe_sculpt.pick_side"
    bl_label = "Select Side"
    bl_description = "Select all bones on a side (or all / none)"
    bl_options = {'REGISTER', 'UNDO'}

    side: EnumProperty(
        items=(
            ('ALL', "All", "Select every bone"),
            ('NONE', "None", "Deselect everything"),
            ('L', "Left", "Select all left-side bones"),
            ('R', "Right", "Select all right-side bones"),
        ),
        default='ALL',
    )

    def execute(self, context):
        arm = _armature_in_pose(context)
        if arm is None:
            return {'CANCELLED'}
        n = 0
        for pb in arm.pose.bones:
            col = picker_core._column_of(pb.name)
            if self.side == 'ALL':
                sel = True
            elif self.side == 'NONE':
                sel = False
            else:
                sel = (col == self.side)
            pb.select = sel
            if sel:
                n += 1
        self.report({'INFO'}, f"Selected {n} bone(s)")
        return {'FINISHED'}


class PIPESCULPT_PT_bone_picker(Panel):
    bl_idname = "PIPESCULPT_PT_bone_picker"
    bl_label = "Bone Picker"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 16  # right after Animate (15)

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def draw(self, context):
        layout = self.layout
        arm = _armature_in_pose(context)
        names = [pb.name for pb in arm.pose.bones]
        slots = picker_core.build_picker_layout(names)

        # Quick select row
        row = layout.row(align=True)
        row.operator("pipe_sculpt.pick_side", text="All").side = 'ALL'
        row.operator("pipe_sculpt.pick_side", text="L").side = 'L'
        row.operator("pipe_sculpt.pick_side", text="R").side = 'R'
        row.operator("pipe_sculpt.pick_side", text="None").side = 'NONE'

        layout.label(text="Shift-click to add", icon='INFO')

        # Body grid — render row by row so L/C/R align like a silhouette
        cols = picker_core.body_columns(slots)
        all_rows = sorted({s.row for col in cols.values() for s in col})
        body = layout.column(align=True)
        for r in all_rows:
            grid = body.row(align=True)
            for ckey in ('L', 'C', 'R'):
                cell = grid.column(align=True)
                here = [s for s in cols[ckey] if s.row == r]
                if not here:
                    cell.label(text="")  # spacer keeps columns aligned
                    continue
                for s in here:
                    cell.operator("pipe_sculpt.pick_bone", text=s.label).bone = s.bone

        # Controls (IK targets / poles)
        ctrls = picker_core.control_slots(slots)
        if ctrls:
            layout.separator()
            layout.label(text="Controls", icon='CON_KINEMATIC')
            grid = layout.grid_flow(row_major=True, columns=3, align=True)
            for s in ctrls:
                side = "" if s.column == 'C' else f" {s.column}"
                grid.operator("pipe_sculpt.pick_bone", text=f"{s.label}{side}").bone = s.bone

        # Fingers (collapsible-feel: only drawn if present)
        fingers = picker_core.finger_slots(slots)
        if fingers:
            layout.separator()
            layout.label(text="Fingers", icon='HAND')
            for side_key, side_label in (('L', "Left"), ('R', "Right")):
                side_fingers = [s for s in fingers if s.column == side_key]
                if not side_fingers:
                    continue
                box = layout.box()
                box.label(text=side_label)
                grid = box.grid_flow(row_major=True, columns=3, align=True)
                for s in side_fingers:
                    grid.operator("pipe_sculpt.pick_bone", text=s.label).bone = s.bone


_classes = (
    PIPESCULPT_OT_pick_bone,
    PIPESCULPT_OT_pick_side,
    PIPESCULPT_PT_bone_picker,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
