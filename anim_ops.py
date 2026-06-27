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
from bpy.types import Operator, Panel

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


# ======================================================================
# F-curve access — version-robust (Blender 5.1 removed action.fcurves)
# ======================================================================

def _action_fcurves(obj):
    """Return the active action's F-curves across Blender versions.

    Spiked against Blender 5.1: `action.fcurves` is GONE — slotted actions
    store curves in channelbags under layers/strips. We try the legacy
    direct path first (Blender < 4.4) then fall back to the channelbag path
    (4.4+/5.x). Returns a flat list of FCurve.
    """
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return []
    act = ad.action

    # Legacy direct path (pre-slotted actions)
    if hasattr(act, "fcurves"):
        return list(act.fcurves)

    # Slotted action: fcurves live in channelbag(slot)
    slot = getattr(ad, "action_slot", None)
    fcurves = []
    for layer in act.layers:
        for strip in layer.strips:
            if not hasattr(strip, "channelbag"):
                continue
            cb = strip.channelbag(slot) if slot is not None else None
            if cb is not None:
                fcurves.extend(cb.fcurves)
    return fcurves


def _active_action(obj):
    ad = obj.animation_data
    return ad.action if ad and ad.action else None


# ======================================================================
# 2.2 Keying helpers
# ======================================================================

class PIPESCULPT_OT_anim_key_rig(Operator):
    bl_idname = "pipe_sculpt.anim_key_rig"
    bl_label = "Key Whole Rig"
    bl_description = "Insert a keyframe on loc/rot/scale of every pose bone at the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        n = _key_bones(arm.pose.bones)
        self.report({'INFO'}, f"Keyed {n} bone(s) at frame {context.scene.frame_current}")
        return {'FINISHED'}


class PIPESCULPT_OT_anim_key_selected(Operator):
    bl_idname = "pipe_sculpt.anim_key_selected"
    bl_label = "Key Selected"
    bl_description = "Insert a keyframe on loc/rot/scale of the selected pose bones only"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        n = _key_bones(_target_bones(context, arm))
        self.report({'INFO'}, f"Keyed {n} selected bone(s)")
        return {'FINISHED'}


def _key_bones(bones):
    """Insert loc/rot/scale keys on each bone, using its actual rotation mode."""
    n = 0
    for pb in bones:
        pb.keyframe_insert("location")
        if pb.rotation_mode == 'QUATERNION':
            pb.keyframe_insert("rotation_quaternion")
        elif pb.rotation_mode == 'AXIS_ANGLE':
            pb.keyframe_insert("rotation_axis_angle")
        else:
            pb.keyframe_insert("rotation_euler")
        pb.keyframe_insert("scale")
        n += 1
    return n


class PIPESCULPT_OT_anim_toggle_interp(Operator):
    bl_idname = "pipe_sculpt.anim_toggle_interp"
    bl_label = "Toggle Stepped / Spline"
    bl_description = (
        "Switch every keyframe on the active action between CONSTANT (blocking) "
        "and BEZIER (spline). Detects the current dominant mode and flips it"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature_in_pose(context)
        return arm is not None and _active_action(arm) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        fcurves = _action_fcurves(arm)
        # Detect dominant interpolation across all keys
        constant = 0
        total = 0
        for fc in fcurves:
            for kp in fc.keyframe_points:
                total += 1
                if kp.interpolation == 'CONSTANT':
                    constant += 1
        if total == 0:
            self.report({'WARNING'}, "Active action has no keyframes")
            return {'CANCELLED'}
        # If mostly constant, go spline; otherwise go constant
        new_interp = 'BEZIER' if constant > total / 2 else 'CONSTANT'
        for fc in fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = new_interp
            fc.update()
        self.report({'INFO'}, f"Set {total} keys to {new_interp} ({'spline' if new_interp == 'BEZIER' else 'blocking'})")
        return {'FINISHED'}


class PIPESCULPT_OT_anim_fit_range(Operator):
    bl_idname = "pipe_sculpt.anim_fit_range"
    bl_label = "Fit Preview Range"
    bl_description = "Set the scene preview range to the active action's frame range so loop preview is exact"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = _armature_in_pose(context)
        return arm is not None and _active_action(arm) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        act = _active_action(arm)
        start, end = anim_core.fit_preview_range(act.frame_range[0], act.frame_range[1])
        scene = context.scene
        scene.use_preview_range = True
        scene.frame_preview_start = start
        scene.frame_preview_end = end
        self.report({'INFO'}, f"Preview range {start}–{end}")
        return {'FINISHED'}


# ======================================================================
# 2.3 Loop authoring
# ======================================================================

def _sample_pose(arm, frame, context):
    """Set the scene to `frame` and read every bone's (loc, quat, scale)."""
    context.scene.frame_set(int(frame))
    return {pb.name: _read_transform(pb) for pb in arm.pose.bones}


class PIPESCULPT_OT_anim_validate_loop(Operator):
    bl_idname = "pipe_sculpt.anim_validate_loop"
    bl_label = "Validate Loop"
    bl_description = (
        "Compare the pose at the first vs last frame of the active action and "
        "report which bones 'pop' — i.e. differ enough to make the loop visibly "
        "jump. Makes loop errors visible here instead of in Unity"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        arm = _armature_in_pose(context)
        return arm is not None and _active_action(arm) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        act = _active_action(arm)
        f_start, f_end = int(act.frame_range[0]), int(act.frame_range[1])
        if f_start == f_end:
            self.report({'WARNING'}, "Action is a single frame — nothing to loop")
            return {'CANCELLED'}

        prior_frame = context.scene.frame_current
        pose_first = _sample_pose(arm, f_start, context)
        pose_last = _sample_pose(arm, f_end, context)
        context.scene.frame_set(prior_frame)

        diffs = anim_core.diff_pose(pose_first, pose_last)

        # Print full report to console
        print(f"\n=== PipeSculpt Loop Validation: '{act.name}' f{f_start}↔f{f_end} ===")
        if not diffs:
            print("  Loop is clean — first and last frame match.")
        else:
            for d in diffs[:20]:
                print(f"  {d.bone:<16} loc Δ{d.loc_delta:.4f}  rot Δ{d.rot_delta:.4f}  scale Δ{d.scale_delta:.4f}")
        print("=" * 50)

        if not diffs:
            self.report({'INFO'}, f"Loop clean — frame {f_start} matches frame {f_end} ✓")
        else:
            worst = diffs[0]
            self.report(
                {'WARNING'},
                f"{len(diffs)} bone(s) pop on loop — worst: '{worst.bone}' "
                f"(Δ{worst.max_delta:.3f}). See System Console for the full list",
            )
        return {'FINISHED'}


class PIPESCULPT_OT_anim_make_cyclic(Operator):
    bl_idname = "pipe_sculpt.anim_make_cyclic"
    bl_label = "Make Cyclic"
    bl_description = (
        "Copy the last frame's pose onto the first frame so the cycle closes, "
        "then add a Cycles modifier to every F-curve so it repeats seamlessly"
    )
    bl_options = {'REGISTER', 'UNDO'}

    copy_direction: EnumProperty(
        name="Match",
        items=(
            ('LAST_TO_FIRST', "Last → First", "Copy the last frame's pose onto the first"),
            ('FIRST_TO_LAST', "First → Last", "Copy the first frame's pose onto the last"),
        ),
        default='LAST_TO_FIRST',
    )

    @classmethod
    def poll(cls, context):
        arm = _armature_in_pose(context)
        return arm is not None and _active_action(arm) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        act = _active_action(arm)
        f_start, f_end = int(act.frame_range[0]), int(act.frame_range[1])
        if f_start == f_end:
            self.report({'WARNING'}, "Action is a single frame")
            return {'CANCELLED'}

        prior = context.scene.frame_current
        if self.copy_direction == 'LAST_TO_FIRST':
            src_frame, dst_frame = f_end, f_start
        else:
            src_frame, dst_frame = f_start, f_end

        src_pose = _sample_pose(arm, src_frame, context)
        context.scene.frame_set(dst_frame)
        for pb in arm.pose.bones:
            if pb.name in src_pose:
                _write_transform(pb, src_pose[pb.name])
        _key_bones(arm.pose.bones)
        context.scene.frame_set(prior)

        # Add Cycles modifier to every fcurve (idempotent — skip if present)
        cyc = 0
        for fc in _action_fcurves(arm):
            if not any(mod.type == 'CYCLES' for mod in fc.modifiers):
                fc.modifiers.new('CYCLES')
                cyc += 1
            fc.update()

        self.report(
            {'INFO'},
            f"Cycle closed ({self.copy_direction.replace('_', ' ').lower()}); "
            f"added Cycles to {cyc} curve(s)",
        )
        return {'FINISHED'}


class PIPESCULPT_OT_anim_bake_in_place(Operator):
    bl_idname = "pipe_sculpt.anim_bake_in_place"
    bl_label = "Bake In-Place"
    bl_description = (
        "Remove the root bone's horizontal (XY) translation so an in-place loop "
        "doesn't drift. Keep Z for crouch/jump height. Use for Unity 'Bake Into "
        "Pose' on root position"
    )
    bl_options = {'REGISTER', 'UNDO'}

    keep_z: BoolProperty(
        name="Keep Vertical (Z)",
        description="Preserve up/down motion (crouch, jump); only strip horizontal drift",
        default=True,
    )
    root_bone: bpy.props.StringProperty(
        name="Root Bone",
        description="Name of the bone carrying root motion",
        default="root",
    )

    @classmethod
    def poll(cls, context):
        arm = _armature_in_pose(context)
        return arm is not None and _active_action(arm) is not None

    def execute(self, context):
        arm = _armature_in_pose(context)
        data_path = f'pose.bones["{self.root_bone}"].location'
        fcurves = [fc for fc in _action_fcurves(arm) if fc.data_path == data_path]
        if not fcurves:
            self.report(
                {'WARNING'},
                f"No location curves on '{self.root_bone}' — nothing to strip "
                "(clip may already be in-place)",
            )
            return {'CANCELLED'}

        # Report the travel we're about to remove, then zero X (0) and Y (1)
        stripped = 0
        for fc in fcurves:
            if fc.array_index == 2 and self.keep_z:
                continue  # keep vertical
            for kp in fc.keyframe_points:
                kp.co[1] = 0.0
                kp.handle_left[1] = 0.0
                kp.handle_right[1] = 0.0
            fc.update()
            stripped += 1
        self.report(
            {'INFO'},
            f"Stripped root translation on {stripped} axis-curve(s) "
            f"({'kept Z' if self.keep_z else 'all axes'})",
        )
        return {'FINISHED'}


# ======================================================================
# Animate panel — pose-mode only (sits between Rigging and Export)
# ======================================================================

class PIPESCULPT_PT_animate(Panel):
    bl_idname = "PIPESCULPT_PT_animate"
    bl_label = "Animate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 15  # between Workflow Pipeline (10) and Quick Palette (20)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE' and context.mode == 'POSE'

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="Pose", icon='POSE_HLT')
        row = col.row(align=True)
        row.operator("pipe_sculpt.anim_copy_pose", text="Copy")
        op = row.operator("pipe_sculpt.anim_paste_pose", text="Paste")
        op.mirror = False
        op = row.operator("pipe_sculpt.anim_paste_pose", text="Paste Flip")
        op.mirror = True
        row = col.row(align=True)
        row.operator("pipe_sculpt.anim_mirror_pose", text="Mirror", icon='MOD_MIRROR')
        row.operator("pipe_sculpt.anim_reset_pose", text="Rest", icon='LOOP_BACK')

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Key", icon='KEYINGSET')
        row = col.row(align=True)
        row.operator("pipe_sculpt.anim_key_rig", text="Key Rig")
        row.operator("pipe_sculpt.anim_key_selected", text="Key Sel")
        col.operator("pipe_sculpt.anim_toggle_interp", icon='IPO_CONSTANT')
        col.operator("pipe_sculpt.anim_fit_range", icon='PREVIEW_RANGE')

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Loop", icon='FILE_REFRESH')
        col.operator("pipe_sculpt.anim_validate_loop", icon='CHECKMARK')
        col.operator("pipe_sculpt.anim_make_cyclic", icon='FORCE_HARMONIC')
        col.operator("pipe_sculpt.anim_bake_in_place", icon='ANIM')


_pose_classes = (
    PIPESCULPT_OT_anim_copy_pose,
    PIPESCULPT_OT_anim_paste_pose,
    PIPESCULPT_OT_anim_mirror_pose,
    PIPESCULPT_OT_anim_reset_pose,
    PIPESCULPT_OT_anim_key_rig,
    PIPESCULPT_OT_anim_key_selected,
    PIPESCULPT_OT_anim_toggle_interp,
    PIPESCULPT_OT_anim_fit_range,
    PIPESCULPT_OT_anim_validate_loop,
    PIPESCULPT_OT_anim_make_cyclic,
    PIPESCULPT_OT_anim_bake_in_place,
    PIPESCULPT_PT_animate,
)


def register():
    for c in _pose_classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_pose_classes):
        bpy.utils.unregister_class(c)
