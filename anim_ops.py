"""Animation operators — Phase 1 pose / keying / loop quick-tools.

Born Clean: thin bpy shells over anim_core's pure logic. Every operator
polls for an armature in pose mode. Mirror / breakdown / loop math lives
in anim_core and is unit-tested headlessly; this file only reads/writes
Blender pose state.

Phase 1 sections:
  2.1 Pose tools   — copy / paste / paste-mirror / mirror / reset / breakdown
  2.2 Keying       — key rig / key selected / toggle interp / fit range
  2.3 Loop         — make cyclic / validate loop / bake in-place
"""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from bpy.types import Operator

from . import anim_core


# Module-level pose buffer for copy/paste. dict[bone_name] = (loc, quat, scale)
_POSE_BUFFER: dict = {}


def _armature_in_pose(context):
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE':
        return None
    if context.mode != 'POSE':
        return None
    return obj


def _target_bones(context, arm):
    """Selected pose bones, or all of them if nothing is selected.

    Uses context.selected_pose_bones — in Blender 5.x bone selection moved
    off Bone.select (removed) onto PoseBone.select, and the context list is
    the robust way to read it.
    """
    selected = context.selected_pose_bones
    if selected:
        return list(selected)
    return list(arm.pose.bones)


def _read_transform(pb):
    """Read a pose bone's local transform as plain tuples for anim_core."""
    loc = tuple(pb.location)
    # Always read as quaternion regardless of the bone's rotation mode
    q = pb.matrix_basis.to_quaternion()
    quat = (q.w, q.x, q.y, q.z)
    scale = tuple(pb.scale)
    return (loc, quat, scale)


def _write_transform(pb, transform):
    """Write a (loc, quat, scale) transform back onto a pose bone."""
    import mathutils

    loc, quat, scale = transform
    pb.location = loc
    q = mathutils.Quaternion((quat[0], quat[1], quat[2], quat[3]))
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = q
    elif pb.rotation_mode == 'AXIS_ANGLE':
        aa = q.to_axis_angle()
        pb.rotation_axis_angle = (aa[1], aa[0].x, aa[0].y, aa[0].z)
    else:
        pb.rotation_euler = q.to_euler(pb.rotation_mode)
    pb.scale = scale


# ======================================================================
# 2.1 Pose tools
# ======================================================================

class PIPESCULPT_OT_anim_copy_pose(Operator):
    bl_idname = "pipe_sculpt.anim_copy_pose"
    bl_label = "Copy Pose"
    bl_description = "Copy the transform of the selected (or all) pose bones to an internal buffer"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        _POSE_BUFFER.clear()
        for pb in _target_bones(context, arm):
            _POSE_BUFFER[pb.name] = _read_transform(pb)
        self.report({'INFO'}, f"Copied {len(_POSE_BUFFER)} bone(s) to pose buffer")
        return {'FINISHED'}


class PIPESCULPT_OT_anim_paste_pose(Operator):
    bl_idname = "pipe_sculpt.anim_paste_pose"
    bl_label = "Paste Pose"
    bl_description = "Paste the buffered pose onto the matching bones"
    bl_options = {'REGISTER', 'UNDO'}

    mirror: BoolProperty(
        name="Mirror",
        description="Paste mirrored across X (.L↔.R)",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None and bool(_POSE_BUFFER)

    def execute(self, context):
        arm = _armature_in_pose(context)
        pasted = 0
        for src_name, transform in _POSE_BUFFER.items():
            target_name = src_name
            xform = transform
            if self.mirror:
                twin = anim_core.mirror_bone_name(src_name)
                if twin is not None:
                    target_name = twin
                xform = _mirror_transform(transform)
            pb = arm.pose.bones.get(target_name)
            if pb is None:
                continue
            _write_transform(pb, xform)
            pasted += 1
        self.report({'INFO'}, f"Pasted {pasted} bone(s){' mirrored' if self.mirror else ''}")
        return {'FINISHED'}


def _mirror_transform(transform):
    """Mirror a transform across the X axis (Blender's standard pose mirror).

    Position: negate X. Rotation quaternion: negate Y and Z components
    (reflection across the YZ plane for an X-mirror). Scale: unchanged.
    This matches how Blender's own Paste X-Flipped behaves for .L/.R bones.
    """
    loc, quat, scale = transform
    m_loc = (-loc[0], loc[1], loc[2])
    w, x, y, z = quat
    m_quat = (w, x, -y, -z)
    return (m_loc, m_quat, scale)


class PIPESCULPT_OT_anim_mirror_pose(Operator):
    bl_idname = "pipe_sculpt.anim_mirror_pose"
    bl_label = "Mirror Pose"
    bl_description = "Mirror the current pose left↔right in one click (.L↔.R bones swap and flip)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        # Snapshot the whole pose first so swaps read pre-mirror values
        snapshot = {pb.name: _read_transform(pb) for pb in arm.pose.bones}
        targets = _target_bones(context, arm)
        written = 0
        for pb in targets:
            twin = anim_core.mirror_bone_name(pb.name)
            if twin is None:
                # Centerline bone — mirror onto itself (flip X)
                _write_transform(pb, _mirror_transform(snapshot[pb.name]))
                written += 1
            else:
                src = snapshot.get(twin)
                if src is None:
                    continue
                _write_transform(pb, _mirror_transform(src))
                written += 1
        self.report({'INFO'}, f"Mirrored {written} bone(s)")
        return {'FINISHED'}


class PIPESCULPT_OT_anim_reset_pose(Operator):
    bl_idname = "pipe_sculpt.anim_reset_pose"
    bl_label = "Reset to Rest"
    bl_description = "Reset selected (or all) bones to rest pose — zero location/rotation, unit scale"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        identity = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        for pb in _target_bones(context, arm):
            _write_transform(pb, identity)
        self.report({'INFO'}, "Reset to rest pose")
        return {'FINISHED'}


_pose_classes = (
    PIPESCULPT_OT_anim_copy_pose,
    PIPESCULPT_OT_anim_paste_pose,
    PIPESCULPT_OT_anim_mirror_pose,
    PIPESCULPT_OT_anim_reset_pose,
)


def register():
    for c in _pose_classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_pose_classes):
        bpy.utils.unregister_class(c)
