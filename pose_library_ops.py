"""Pose library operators — apply / insert standard poses onto a rig.

Born Clean adapter: the catalog + pose math live in pose_library_core (pure,
pytest-tested); this file is the bpy shell that writes channels onto pose
bones and inserts keyframes. Keying reuses anim_ops._key_bones so the pose
library and the hand-keying tools stay consistent.

The rig is IK-driven, so a pose is defined by the IK CONTROL bones + the FK
bones; the 8 IK-solved limb bones (pose_library_core.IK_SOLVED_BONES) are
never written or keyed — the solver derives them from the controls. See
pose_library_core for the full rationale.

Operators:
  - PIPESCULPT_OT_pose_apply     : set the current pose to a library pose
  - PIPESCULPT_OT_pose_insert    : apply + keyframe at a target frame (blocking)
"""
from __future__ import annotations

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import anim_ops
from . import pose_library_core as plc


# EnumProperty items must outlive the callback (Blender GC caveat) — a module
# global that register() fills once from the static catalog is safe + dynamic.
_POSE_ENUM_ITEMS: list = []


def _rebuild_pose_items():
    _POSE_ENUM_ITEMS.clear()
    cats = plc.poses_by_category()
    first = True
    for cat in plc.POSE_CATEGORIES:
        poses = cats.get(cat) or []
        if not poses:
            continue
        if not first:
            _POSE_ENUM_ITEMS.append(None)  # separator between categories
        first = False
        for p in poses:
            _POSE_ENUM_ITEMS.append((p.name, p.label, p.description))
    # Any category not in the canonical order (defensive)
    for cat, poses in cats.items():
        if cat in plc.POSE_CATEGORIES:
            continue
        for p in poses:
            _POSE_ENUM_ITEMS.append((p.name, p.label, p.description))


def _pose_enum_items(self, context):
    if not _POSE_ENUM_ITEMS:
        _rebuild_pose_items()
    return _POSE_ENUM_ITEMS


def _armature_in_pose(context):
    obj = context.active_object
    return obj is not None and obj.type == 'ARMATURE' and context.mode == 'POSE'


def _set_rest(pb):
    """Return one pose bone to its rest transform (leave scale untouched)."""
    pb.location = (0.0, 0.0, 0.0)
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    elif pb.rotation_mode == 'AXIS_ANGLE':
        pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    else:
        pb.rotation_euler = (0.0, 0.0, 0.0)


def _write_channel(pb, loc, quat):
    """Write a (loc, quat) channel, honouring the bone's rotation_mode."""
    pb.location = loc
    q = mathutils.Quaternion(quat)
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = q
    elif pb.rotation_mode == 'AXIS_ANGLE':
        aa = q.to_axis_angle()
        pb.rotation_axis_angle = (aa[1], aa[0].x, aa[0].y, aa[0].z)
    else:
        pb.rotation_euler = q.to_euler(pb.rotation_mode)


def _resolve_channels(pose_name, mirror, influence):
    """Catalog pose -> final channels dict (mirror + influence applied)."""
    channels = dict(plc.get_pose(pose_name).channels)
    if mirror:
        channels = plc.mirror_channels(channels)
    if influence < 1.0:
        channels = plc.blend_channels(channels, influence)
    return channels


def _apply_channels(context, arm, channels, selected_only):
    """Reset the affected bones to rest, then write the pose. Returns count."""
    bones = arm.pose.bones
    if selected_only:
        sel = [pb for pb in (context.selected_pose_bones or [])
               if pb.name not in plc.IK_SOLVED_BONES]
        sel_names = {pb.name for pb in sel}
        for pb in sel:
            _set_rest(pb)
        n = 0
        for bone, (loc, quat) in channels.items():
            if bone in sel_names:
                _write_channel(bones[bone], loc, quat)
                n += 1
        return n
    # whole-rig: reset every capturable bone, then write the pose
    for pb in bones:
        if pb.name not in plc.IK_SOLVED_BONES:
            _set_rest(pb)
    n = 0
    for bone, (loc, quat) in channels.items():
        pb = bones.get(bone)
        if pb is not None and pb.name not in plc.IK_SOLVED_BONES:
            _write_channel(pb, loc, quat)
            n += 1
    return n


def _capturable_bones(context, arm, selected_only):
    if selected_only:
        return [pb for pb in (context.selected_pose_bones or [])
                if pb.name not in plc.IK_SOLVED_BONES]
    return [pb for pb in arm.pose.bones if pb.name not in plc.IK_SOLVED_BONES]


class PIPESCULPT_PG_pose_library(PropertyGroup):
    pose: EnumProperty(
        name="Pose",
        description="Standard pose from the library",
        items=_pose_enum_items,
    )
    mirror: BoolProperty(
        name="Mirror",
        description="Apply the left/right-mirrored version of the pose",
        default=False,
    )
    influence: FloatProperty(
        name="Influence",
        description="Blend from the rest pose toward the library pose (1.0 = full pose)",
        default=1.0, min=0.0, max=1.0, subtype='FACTOR',
    )
    selected_only: BoolProperty(
        name="Selected Bones Only",
        description="Only apply to the selected bones (else the whole rig)",
        default=False,
    )
    target_frame: IntProperty(
        name="Frame",
        description="Frame to insert the pose keyframe on",
        default=1, min=0,
    )
    advance: IntProperty(
        name="Advance",
        description="Frames to advance the target frame after inserting (0 = stay). "
                    "Set e.g. 8-12 to block a pose every N frames",
        default=0, min=0, max=240,
    )


class PIPESCULPT_OT_pose_apply(Operator):
    bl_idname = "pipe_sculpt.pose_apply"
    bl_label = "Apply Pose"
    bl_description = (
        "Set the rig to the selected standard pose. Drives the IK controls + FK "
        "bones; the arms/legs solve via IK. Does NOT keyframe — use 'Insert at "
        "Frame' for that (or turn on Record)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context)

    def execute(self, context):
        arm = context.active_object
        s = context.scene.pipe_sculpt_pose_library
        try:
            channels = _resolve_channels(s.pose, s.mirror, s.influence)
        except KeyError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        n = _apply_channels(context, arm, channels, s.selected_only)
        context.view_layer.update()
        pose = plc.get_pose(s.pose)
        mir = " (mirrored)" if s.mirror else ""
        self.report({'INFO'}, f"Applied '{pose.label}'{mir} — {n} bones set")
        return {'FINISHED'}


class PIPESCULPT_OT_pose_insert(Operator):
    bl_idname = "pipe_sculpt.pose_insert"
    bl_label = "Insert Pose at Frame"
    bl_description = (
        "Jump to the target frame, apply the pose, and keyframe the whole rig "
        "there. Set 'Advance' to auto-step the frame so you can block a pose "
        "per keyframe. Arms/legs are keyed on their IK controls"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context)

    def execute(self, context):
        arm = context.active_object
        s = context.scene.pipe_sculpt_pose_library
        try:
            channels = _resolve_channels(s.pose, s.mirror, s.influence)
        except KeyError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        frame = s.target_frame
        context.scene.frame_set(frame)
        _apply_channels(context, arm, channels, s.selected_only)
        context.view_layer.update()

        bones = _capturable_bones(context, arm, s.selected_only)
        keyed = anim_ops._key_bones(bones)

        if s.advance > 0:
            s.target_frame = frame + s.advance

        pose = plc.get_pose(s.pose)
        mir = " (mirrored)" if s.mirror else ""
        adv = f", frame -> {s.target_frame}" if s.advance > 0 else ""
        self.report(
            {'INFO'},
            f"Inserted '{pose.label}'{mir} at frame {frame} — keyed {keyed} bones{adv}",
        )
        return {'FINISHED'}


class PIPESCULPT_PT_pose_library(Panel):
    bl_idname = "PIPESCULPT_PT_pose_library"
    bl_label = "Pose Library"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 17  # Animate(15) -> Bone Picker(16) -> Pose Library(17) -> Onion(18)

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context)

    def draw(self, context):
        layout = self.layout
        s = context.scene.pipe_sculpt_pose_library

        col = layout.column(align=True)
        col.prop(s, "pose", text="")
        row = col.row(align=True)
        row.prop(s, "mirror", toggle=True, icon='MOD_MIRROR')
        row.prop(s, "selected_only", toggle=True, icon='RESTRICT_SELECT_OFF')
        col.prop(s, "influence", slider=True)

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("pipe_sculpt.pose_apply", icon='ARMATURE_DATA')

        layout.separator()
        box = layout.box().column(align=True)
        box.label(text="Insert as keyframe", icon='KEYFRAME_HLT')
        row = box.row(align=True)
        row.prop(s, "target_frame")
        row.prop(s, "advance")
        box.scale_y = 1.2
        box.operator("pipe_sculpt.pose_insert", icon='KEY_HLT')


_classes = (
    PIPESCULPT_PG_pose_library,
    PIPESCULPT_OT_pose_apply,
    PIPESCULPT_OT_pose_insert,
    PIPESCULPT_PT_pose_library,
)


def register():
    _rebuild_pose_items()
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pipe_sculpt_pose_library = PointerProperty(type=PIPESCULPT_PG_pose_library)


def unregister():
    if hasattr(bpy.types.Scene, "pipe_sculpt_pose_library"):
        del bpy.types.Scene.pipe_sculpt_pose_library
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
