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

import os
import json

import bpy
import mathutils
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import anim_ops
from . import pose_library_core as plc
from . import pose_io_core as pio


# User poses loaded from disk: name -> {"spec": PoseSpec, "path": str}. Built
# from the user-pose folder on register + after every save/delete.
USER_POSES: dict = {}


def _user_pose_dir(context, create=False) -> str:
    """The folder holding user pose .json files (pref, or Blender config)."""
    path = ""
    try:
        prefs = context.preferences.addons[__package__].preferences
        path = bpy.path.abspath(prefs.user_pose_dir).strip() if prefs.user_pose_dir else ""
    except (KeyError, AttributeError):
        path = ""
    if not path:
        path = bpy.utils.user_resource('CONFIG', path="pipe_sculpt/poses", create=create)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _load_user_poses(context):
    """Scan the user-pose folder and rebuild USER_POSES + the enum items."""
    USER_POSES.clear()
    folder = _user_pose_dir(context)
    if folder and os.path.isdir(folder):
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(".json"):
                continue
            fpath = os.path.join(folder, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    spec = pio.pose_from_dict(json.load(f))
            except (OSError, ValueError, json.JSONDecodeError) as e:
                print(f"[PipeSculpt] skipped pose '{fname}': {e}")
                continue
            # Never let a user file shadow a built-in id.
            if any(p.name == spec.name for p in plc.POSE_LIBRARY):
                print(f"[PipeSculpt] user pose '{spec.name}' clashes with a built-in — skipped")
                continue
            USER_POSES[spec.name] = {"spec": spec, "path": fpath}
    _rebuild_pose_items()


def _all_poses():
    return tuple(plc.POSE_LIBRARY) + tuple(v["spec"] for v in USER_POSES.values())


def _get_pose(name):
    for p in _all_poses():
        if p.name == name:
            return p
    raise KeyError(f"Unknown pose '{name}'")


# EnumProperty items must outlive the callback (Blender GC caveat) — a module
# global filled by _rebuild_pose_items on register + after save/delete.
_POSE_ENUM_ITEMS: list = []


def _rebuild_pose_items():
    _POSE_ENUM_ITEMS.clear()
    # Built-in categories first, in canonical order.
    cats = plc.poses_by_category()
    first = True
    for cat in plc.POSE_CATEGORIES:
        poses = cats.get(cat) or []
        if not poses:
            continue
        if not first:
            _POSE_ENUM_ITEMS.append(None)
        first = False
        for p in poses:
            _POSE_ENUM_ITEMS.append((p.name, p.label, p.description))
    # Then the user's own saved poses.
    if USER_POSES:
        if not first:
            _POSE_ENUM_ITEMS.append(None)
        for name in sorted(USER_POSES):
            p = USER_POSES[name]["spec"]
            _POSE_ENUM_ITEMS.append((p.name, f"★ {p.label}", p.description))


def _pose_enum_items(self, context):
    if not _POSE_ENUM_ITEMS:
        _load_user_poses(context)
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
    channels = dict(_get_pose(pose_name).channels)
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
        pose = _get_pose(s.pose)
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

        pose = _get_pose(s.pose)
        mir = " (mirrored)" if s.mirror else ""
        adv = f", frame -> {s.target_frame}" if s.advance > 0 else ""
        self.report(
            {'INFO'},
            f"Inserted '{pose.label}'{mir} at frame {frame} — keyed {keyed} bones{adv}",
        )
        return {'FINISHED'}


def _capture_current(arm, name, label, category, description):
    """Read the rig's current pose into a PoseSpec (controls + FK, non-rest)."""
    channels = {}
    for pb in arm.pose.bones:
        if pb.name in plc.IK_SOLVED_BONES:
            continue
        loc = tuple(round(v, 6) for v in pb.location)
        q = pb.matrix_basis.to_quaternion()
        quat = (round(q.w, 6), round(q.x, 6), round(q.y, 6), round(q.z, 6))
        if (any(abs(v) > 1e-5 for v in loc) or abs(quat[0] - 1.0) > 1e-5
                or any(abs(v) > 1e-5 for v in quat[1:])):
            channels[pb.name] = (loc, quat)
    return plc.PoseSpec(name, label, category, description, channels=channels)


class PIPESCULPT_OT_pose_save(Operator):
    bl_idname = "pipe_sculpt.pose_save"
    bl_label = "Save Current Pose"
    bl_description = (
        "Save the rig's current pose to your pose folder as a reusable .json "
        "asset (like a Unity ScriptableObject). It appears in the list under "
        "★. Re-saving with the same name updates it — pose, tweak, re-save"
    )
    bl_options = {'REGISTER'}

    pose_name: StringProperty(
        name="Name",
        description="Display name for the pose (also the file name)",
        default="My Pose",
    )

    @classmethod
    def poll(cls, context):
        return _armature_in_pose(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        self.layout.prop(self, "pose_name")

    def execute(self, context):
        arm = context.active_object
        label = self.pose_name.strip()
        if not label:
            self.report({'ERROR'}, "Give the pose a name")
            return {'CANCELLED'}
        pose_id = pio.normalise_pose_id(label)
        if any(p.name == pose_id for p in plc.POSE_LIBRARY):
            self.report({'ERROR'}, f"'{label}' clashes with a built-in pose — pick another name")
            return {'CANCELLED'}

        spec = _capture_current(arm, pose_id, label, pio.USER_CATEGORY,
                                f"User pose saved from {arm.name}")
        if not spec.channels:
            self.report({'WARNING'}, "The rig is at rest — pose it first, then Save")
            return {'CANCELLED'}

        folder = _user_pose_dir(context, create=True)
        fpath = os.path.join(folder, pio.slugify(label) + ".json")
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(pio.pose_to_dict(spec), f, indent=2)
        except OSError as e:
            self.report({'ERROR'}, f"Couldn't write pose file: {e}")
            return {'CANCELLED'}

        _load_user_poses(context)
        context.scene.pipe_sculpt_pose_library.pose = pose_id
        self.report({'INFO'}, f"Saved '{label}' ({len(spec.channels)} bones) → {fpath}")
        return {'FINISHED'}


class PIPESCULPT_OT_pose_delete(Operator):
    bl_idname = "pipe_sculpt.pose_delete"
    bl_label = "Delete Saved Pose"
    bl_description = "Delete the selected user pose (★) file from disk. Built-in poses can't be deleted"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        s = getattr(context.scene, "pipe_sculpt_pose_library", None)
        return s is not None and s.pose in USER_POSES

    def execute(self, context):
        s = context.scene.pipe_sculpt_pose_library
        entry = USER_POSES.get(s.pose)
        if entry is None:
            self.report({'ERROR'}, "That's a built-in pose — can't delete it")
            return {'CANCELLED'}
        label = entry["spec"].label
        try:
            os.remove(entry["path"])
        except OSError as e:
            self.report({'ERROR'}, f"Couldn't delete: {e}")
            return {'CANCELLED'}
        _load_user_poses(context)
        self.report({'INFO'}, f"Deleted saved pose '{label}'")
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

        layout.separator()
        box = layout.box().column(align=True)
        box.label(text="Save your own", icon='FILE_TICK')
        row = box.row(align=True)
        row.operator("pipe_sculpt.pose_save", text="Save Current Pose", icon='ADD')
        sub = row.row(align=True)
        sub.enabled = s.pose in USER_POSES
        sub.operator("pipe_sculpt.pose_delete", text="", icon='TRASH')


_classes = (
    PIPESCULPT_PG_pose_library,
    PIPESCULPT_OT_pose_apply,
    PIPESCULPT_OT_pose_insert,
    PIPESCULPT_OT_pose_save,
    PIPESCULPT_OT_pose_delete,
    PIPESCULPT_PT_pose_library,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pipe_sculpt_pose_library = PointerProperty(type=PIPESCULPT_PG_pose_library)
    # Load the user's saved poses (best-effort — never block register).
    try:
        _load_user_poses(bpy.context)
    except Exception as e:  # noqa: BLE001 — registration must not fail
        print(f"[PipeSculpt] user pose load skipped at register: {e}")
        _rebuild_pose_items()


def unregister():
    if hasattr(bpy.types.Scene, "pipe_sculpt_pose_library"):
        del bpy.types.Scene.pipe_sculpt_pose_library
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
