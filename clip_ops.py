"""Clip manager — Phase 3 §E. Manage a character's animation clips (Actions).

Built on the established Action + NLA model (the Q2 spike confirmed the new
layered-action API allows only one layer per action, so multi-clip stays on
Actions). Naming logic lives in clip_core.py (headless-tested); this file is
the bpy layer: list / activate / new / duplicate / rename / push-to-NLA /
delete.

A "clip" here is a bpy Action. Manager-created clips get use_fake_user so
they survive a save even while not the active action.
"""
from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from . import clip_core


def _armature(context):
    obj = context.active_object
    return obj if (obj is not None and obj.type == 'ARMATURE') else None


def _ensure_anim_data(arm):
    if arm.animation_data is None:
        arm.animation_data_create()
    return arm.animation_data


def _bind_slot(ad, action):
    """Bind a compatible slot so the action actually drives the armature.

    Slotted actions (4.4+/5.x): assigning ad.action doesn't always pick a
    slot. If the action already has one (it was keyed before), select it; a
    fresh empty action has none and gets a slot on the first keyframe.
    """
    if action is None:
        return
    if getattr(ad, "action_slot", None) is None and len(action.slots) > 0:
        try:
            ad.action_slot = action.slots[0]
        except (TypeError, RuntimeError):
            pass


class PIPESCULPT_OT_clip_new(Operator):
    bl_idname = "pipe_sculpt.clip_new"
    bl_label = "New Clip"
    bl_description = "Create a new empty animation clip (Action) and make it active"
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name="Name", default="Clip")

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=260)

    def execute(self, context):
        arm = _armature(context)
        ad = _ensure_anim_data(arm)
        existing = {a.name for a in bpy.data.actions}
        act = bpy.data.actions.new(clip_core.unique_name(self.name, existing))
        act.use_fake_user = True
        ad.action = act
        _bind_slot(ad, act)
        self.report({'INFO'}, f"New clip '{act.name}' (active)")
        return {'FINISHED'}


class PIPESCULPT_OT_clip_activate(Operator):
    bl_idname = "pipe_sculpt.clip_activate"
    bl_label = "Activate Clip"
    bl_description = "Make this clip the armature's active action"
    bl_options = {'REGISTER', 'UNDO'}

    clip: StringProperty()

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        act = bpy.data.actions.get(self.clip)
        if act is None:
            self.report({'WARNING'}, f"No clip '{self.clip}'")
            return {'CANCELLED'}
        ad = _ensure_anim_data(arm)
        ad.action = act
        _bind_slot(ad, act)
        self.report({'INFO'}, f"Activated '{act.name}'")
        return {'FINISHED'}


class PIPESCULPT_OT_clip_duplicate(Operator):
    bl_idname = "pipe_sculpt.clip_duplicate"
    bl_label = "Duplicate Clip"
    bl_description = "Duplicate the active clip under a new name and make the copy active"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return arm is not None and arm.animation_data and arm.animation_data.action

    def execute(self, context):
        arm = _armature(context)
        ad = arm.animation_data
        src = ad.action
        existing = {a.name for a in bpy.data.actions}
        dup = src.copy()
        dup.name = clip_core.next_duplicate_name(src.name, existing)
        dup.use_fake_user = True
        ad.action = dup
        _bind_slot(ad, dup)
        self.report({'INFO'}, f"Duplicated → '{dup.name}'")
        return {'FINISHED'}


class PIPESCULPT_OT_clip_rename(Operator):
    bl_idname = "pipe_sculpt.clip_rename"
    bl_label = "Rename Clip"
    bl_description = "Rename the active clip"
    bl_options = {'REGISTER', 'UNDO'}

    new_name: StringProperty(name="New Name")

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return arm is not None and arm.animation_data and arm.animation_data.action

    def invoke(self, context, event):
        self.new_name = _armature(context).animation_data.action.name
        return context.window_manager.invoke_props_dialog(self, width=260)

    def execute(self, context):
        arm = _armature(context)
        act = arm.animation_data.action
        existing = {a.name for a in bpy.data.actions if a is not act}
        act.name = clip_core.unique_name(self.new_name, existing)
        self.report({'INFO'}, f"Renamed to '{act.name}'")
        return {'FINISHED'}


class PIPESCULPT_OT_clip_push_nla(Operator):
    bl_idname = "pipe_sculpt.clip_push_nla"
    bl_label = "Push to NLA"
    bl_description = (
        "Push the active clip down to a new NLA track and clear the active "
        "slot, so you can start a fresh clip while keeping this one"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return arm is not None and arm.animation_data and arm.animation_data.action

    def execute(self, context):
        arm = _armature(context)
        ad = arm.animation_data
        act = ad.action
        start = int(act.frame_range[0])
        track = ad.nla_tracks.new()
        track.name = act.name
        try:
            track.strips.new(act.name, start, act)
        except RuntimeError as e:
            ad.nla_tracks.remove(track)
            self.report({'ERROR'}, f"Push failed: {e}")
            return {'CANCELLED'}
        ad.action = None
        self.report({'INFO'}, f"Pushed '{act.name}' to NLA track")
        return {'FINISHED'}


class PIPESCULPT_OT_clip_delete(Operator):
    bl_idname = "pipe_sculpt.clip_delete"
    bl_label = "Delete Clip"
    bl_description = "Delete the active clip (the Action datablock). Cannot be undone after save"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return arm is not None and arm.animation_data and arm.animation_data.action

    def execute(self, context):
        arm = _armature(context)
        act = arm.animation_data.action
        name = act.name
        arm.animation_data.action = None
        bpy.data.actions.remove(act)
        self.report({'INFO'}, f"Deleted clip '{name}'")
        return {'FINISHED'}


class PIPESCULPT_PT_clips(Panel):
    bl_idname = "PIPESCULPT_PT_clips"
    bl_label = "Clips"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 14  # just above Animate (15)

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def draw(self, context):
        layout = self.layout
        arm = _armature(context)
        ad = arm.animation_data
        active = ad.action if ad else None

        # Top action row
        row = layout.row(align=True)
        row.operator("pipe_sculpt.clip_new", text="New", icon='ADD')
        sub = row.row(align=True)
        sub.enabled = active is not None
        sub.operator("pipe_sculpt.clip_duplicate", text="Dup", icon='DUPLICATE')
        sub.operator("pipe_sculpt.clip_rename", text="", icon='GREASEPENCIL')
        sub.operator("pipe_sculpt.clip_push_nla", text="", icon='NLA_PUSHDOWN')
        sub.operator("pipe_sculpt.clip_delete", text="", icon='TRASH')

        # NLA-stashed clip count
        if ad and ad.nla_tracks:
            n_strips = sum(len(t.strips) for t in ad.nla_tracks)
            if n_strips:
                layout.label(text=f"{n_strips} clip(s) in NLA", icon='NLA')

        # Clip list — all actions, active highlighted
        names = clip_core.sort_clip_names([a.name for a in bpy.data.actions])
        if not names:
            layout.label(text="No clips yet — click New", icon='INFO')
            return
        col = layout.column(align=True)
        for name in names:
            is_active = active is not None and name == active.name
            r = col.row(align=True)
            r.operator(
                "pipe_sculpt.clip_activate",
                text=name,
                icon='SOLO_ON' if is_active else 'ACTION',
                depress=is_active,
            ).clip = name


_classes = (
    PIPESCULPT_OT_clip_new,
    PIPESCULPT_OT_clip_activate,
    PIPESCULPT_OT_clip_duplicate,
    PIPESCULPT_OT_clip_rename,
    PIPESCULPT_OT_clip_push_nla,
    PIPESCULPT_OT_clip_delete,
    PIPESCULPT_PT_clips,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
