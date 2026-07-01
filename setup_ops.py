"""Rig styling for animation — visible, grabbable control widgets.

The GTR rig's IK controls (hand_ik / foot_ik / poles / root) are tiny
octahedra buried inside the mesh, so a beginner can't see or grab the thing
that actually moves the arm. This gives each control a bright, distinctly-
shaped, larger custom-shape widget (cube on IK targets, diamond on poles,
ground ring on root), colours bones by side (left blue / right red), sorts
them into Controls / Deform / Fingers bone collections, and shows the rig
in front. Idempotent; safe to re-run and to run on existing rigs.

Widget objects live in a hidden 'WGT_PipeSculpt' collection and control
bones are kind='C', so neither reaches the FBX (export uses use_selection +
use_armature_deform_only).

Styling classification is in setup_core.py (pure, tested); this file only
builds meshes and writes bpy pose state.
"""
from __future__ import annotations

import math

import bpy
from bpy.props import FloatProperty
from bpy.types import Operator

from . import setup_core


WGT_COLLECTION = "WGT_PipeSculpt"
WGT_NAMES = {'CUBE': "WGT_cube", 'DIAMOND': "WGT_diamond", 'RING': "WGT_ring"}


# ----------------------------------------------------------------------
# Widget meshes (unit-sized wireframes: verts + edges, no faces)
# ----------------------------------------------------------------------

def _cube_data():
    v = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5),
         (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
    e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
         (0, 4), (1, 5), (2, 6), (3, 7)]
    return v, e


def _diamond_data():
    v = [(.5, 0, 0), (-.5, 0, 0), (0, .5, 0), (0, -.5, 0), (0, 0, .5), (0, 0, -.5)]
    e = [(0, 2), (2, 1), (1, 3), (3, 0), (0, 4), (2, 4), (1, 4), (3, 4),
         (0, 5), (2, 5), (1, 5), (3, 5)]
    return v, e


def _ring_data(segments=24):
    # Ring in the bone-local XZ plane so it lies flat on the ground when the
    # root bone points up (bone-local Y = world Z).
    v = []
    for i in range(segments):
        t = 2.0 * math.pi * i / segments
        v.append((0.5 * math.cos(t), 0.0, 0.5 * math.sin(t)))
    e = [(i, (i + 1) % segments) for i in range(segments)]
    return v, e


_WIDGET_BUILDERS = {'CUBE': _cube_data, 'DIAMOND': _diamond_data, 'RING': _ring_data}


def _get_wgt_collection():
    coll = bpy.data.collections.get(WGT_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(WGT_COLLECTION)
        # Link at scene root, then hide from viewport + render.
        bpy.context.scene.collection.children.link(coll)
    coll.hide_viewport = True
    coll.hide_render = True
    return coll


def _ensure_widget(shape):
    """Get or build the shared widget object for a shape id."""
    name = WGT_NAMES[shape]
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == 'MESH':
        return obj
    verts, edges = _WIDGET_BUILDERS[shape]()
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    me.update()
    obj = bpy.data.objects.new(name, me)
    obj.hide_render = True
    _get_wgt_collection().objects.link(obj)
    return obj


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------

def _armature(context):
    obj = context.active_object
    return obj if (obj is not None and obj.type == 'ARMATURE') else None


def _ensure_bone_collections(arm_data):
    """Get or create the Controls / Deform / Fingers bone collections."""
    out = {}
    for name in ('Controls', 'Deform', 'Fingers'):
        coll = arm_data.collections.get(name) if hasattr(arm_data.collections, 'get') else None
        if coll is None:
            coll = next((c for c in arm_data.collections if c.name == name), None)
        if coll is None:
            coll = arm_data.collections.new(name)
        out[name] = coll
    return out


class PIPESCULPT_OT_style_rig(Operator):
    bl_idname = "pipe_sculpt.style_rig"
    bl_label = "Style Rig for Animation"
    bl_description = (
        "Give the IK controls (hand/foot targets, poles, root) big coloured "
        "widgets so they're easy to see and grab — cube on IK targets, diamond "
        "on poles, ring on root. Colours bones by side, shows the rig in front"
    )
    bl_options = {'REGISTER', 'UNDO'}

    scale: FloatProperty(
        name="Widget Size", default=1.0, min=0.1, max=5.0, subtype='FACTOR',
        description="Global multiplier for control widget size",
    )

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        arm_data = arm.data
        colls = _ensure_bone_collections(arm_data)

        styled = 0
        for pb in arm.pose.bones:
            name = pb.name
            # Bone collection + colour (pure classification)
            target_coll = setup_core.collection_for_bone(name)
            for cname, coll in colls.items():
                if cname == target_coll:
                    coll.assign(arm_data.bones[name])
            theme = setup_core.theme_for_bone(name)
            try:
                pb.color.palette = theme
            except (TypeError, AttributeError):
                pass

            # Control widget
            widget = setup_core.widget_for_control(name)
            if widget is not None:
                shape, _base = widget
                pb.custom_shape = _ensure_widget(shape)
                pb.use_custom_shape_bone_size = False
                s = setup_core.widget_scale(name, self.scale)
                pb.custom_shape_scale_xyz = (s, s, s)
                if hasattr(pb, "custom_shape_wire_width"):
                    pb.custom_shape_wire_width = 3.0
                styled += 1

        arm.show_in_front = True
        self.report({'INFO'}, f"Styled {styled} control(s) — grab the coloured widgets")
        return {'FINISHED'}


class PIPESCULPT_OT_unstyle_rig(Operator):
    bl_idname = "pipe_sculpt.unstyle_rig"
    bl_label = "Clear Rig Style"
    bl_description = "Remove control widgets and reset bone colours to default"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        for pb in arm.pose.bones:
            pb.custom_shape = None
            try:
                pb.color.palette = 'DEFAULT'
            except (TypeError, AttributeError):
                pass
        self.report({'INFO'}, "Rig style cleared")
        return {'FINISHED'}


def apply_default_style(context, arm):
    """Style a freshly generated rig. Called from Generate Rig; never fatal."""
    prev_active = context.view_layer.objects.active
    try:
        context.view_layer.objects.active = arm
        bpy.ops.pipe_sculpt.style_rig()
    except Exception:
        pass
    finally:
        if prev_active is not None and prev_active.name in bpy.data.objects:
            context.view_layer.objects.active = prev_active


_classes = (
    PIPESCULPT_OT_style_rig,
    PIPESCULPT_OT_unstyle_rig,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
