"""Additive layers — Phase 3 §G. Stack recoil / breathing / flinch on a base.

Built on NLA (the Q2 spike: layered actions cap at one layer, so additive
must use NLA strips with blend_type COMBINE). A base clip sits on a REPLACE
track (via the Clip Manager's Push to NLA); additive clips go on COMBINE
tracks above it. No NLA tweak-mode wrestling — add, set influence, mute,
remove from the Layers panel.

Constant per-layer influence uses the recipe verified in Blender 5.1:
use_animated_influence + a flat influence F-curve (a bare strip.influence
poke is overridden by auto-influence).
"""
from __future__ import annotations

import bpy
from bpy.props import FloatProperty, StringProperty
from bpy.types import Operator, Panel

from . import layer_core


def _armature(context):
    obj = context.active_object
    return obj if (obj is not None and obj.type == 'ARMATURE') else None


def _first_strip(track):
    return track.strips[0] if track.strips else None


def _set_constant_influence(strip, value: float):
    """Apply a constant influence via the spike-verified F-curve recipe.

    strip.fcurves has no remove(), so we clear existing keyframe points and
    re-insert two flat keys spanning the strip. use_animated_influence must
    be on or the F-curve is ignored (verified in the influence probe).
    """
    value = layer_core.clamp_influence(value)
    strip.use_animated_influence = True
    fc = strip.fcurves.find("influence")
    if fc is None:
        fc = strip.fcurves.new("influence")
    else:
        for kp in list(fc.keyframe_points):
            fc.keyframe_points.remove(kp)
    fc.keyframe_points.insert(strip.frame_start, value)
    fc.keyframe_points.insert(strip.frame_end, value)
    fc.update()


def _read_influence(strip) -> float:
    """Read the strip's effective constant influence (1.0 if not animated)."""
    if not strip.use_animated_influence:
        return 1.0
    fc = strip.fcurves.find("influence")
    if fc is None or not fc.keyframe_points:
        return strip.influence
    return fc.keyframe_points[0].co[1]


class PIPESCULPT_OT_layer_add(Operator):
    bl_idname = "pipe_sculpt.layer_add"
    bl_label = "Add Additive Layer"
    bl_description = (
        "Push the active clip onto a new NLA track as an additive (COMBINE) "
        "layer over the base, then clear the active slot. Use for recoil / "
        "breathing / flinch on top of a base cycle"
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
            strip = track.strips.new(act.name, start, act)
        except RuntimeError as e:
            ad.nla_tracks.remove(track)
            self.report({'ERROR'}, f"Add layer failed: {e}")
            return {'CANCELLED'}
        strip.blend_type = layer_core.DEFAULT_BLEND_MODE  # COMBINE
        ad.action = None
        self.report({'INFO'}, f"Added '{act.name}' as additive (COMBINE) layer")
        return {'FINISHED'}


class PIPESCULPT_OT_layer_remove(Operator):
    bl_idname = "pipe_sculpt.layer_remove"
    bl_label = "Remove Layer"
    bl_description = "Remove this NLA layer track (the clip Action is kept)"
    bl_options = {'REGISTER', 'UNDO'}

    track: StringProperty()

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def execute(self, context):
        arm = _armature(context)
        ad = arm.animation_data
        track = ad.nla_tracks.get(self.track)
        if track is None:
            self.report({'WARNING'}, f"No track '{self.track}'")
            return {'CANCELLED'}
        ad.nla_tracks.remove(track)
        self.report({'INFO'}, f"Removed layer '{self.track}'")
        return {'FINISHED'}


class PIPESCULPT_OT_layer_influence(Operator):
    bl_idname = "pipe_sculpt.layer_influence"
    bl_label = "Layer Influence"
    bl_description = "Set how strongly this additive layer blends in (0–100%)"
    bl_options = {'REGISTER', 'UNDO'}

    track: StringProperty()
    influence: FloatProperty(
        name="Influence", default=1.0, min=0.0, max=1.0, subtype='FACTOR',
    )

    @classmethod
    def poll(cls, context):
        return _armature(context) is not None

    def _strip(self, context):
        arm = _armature(context)
        track = arm.animation_data.nla_tracks.get(self.track)
        return _first_strip(track) if track else None

    def invoke(self, context, event):
        strip = self._strip(context)
        if strip is not None:
            self.influence = _read_influence(strip)
        return context.window_manager.invoke_props_dialog(self, width=240)

    def execute(self, context):
        strip = self._strip(context)
        if strip is None:
            self.report({'WARNING'}, f"No layer '{self.track}'")
            return {'CANCELLED'}
        _set_constant_influence(strip, self.influence)
        self.report({'INFO'}, f"Influence {layer_core.influence_percent(self.influence)}%")
        return {'FINISHED'}


class PIPESCULPT_PT_layers(Panel):
    bl_idname = "PIPESCULPT_PT_layers"
    bl_label = "Additive Layers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 17  # after Bone Picker (16)

    @classmethod
    def poll(cls, context):
        arm = _armature(context)
        return arm is not None and arm.animation_data is not None

    def draw(self, context):
        layout = self.layout
        arm = _armature(context)
        ad = arm.animation_data

        layout.operator("pipe_sculpt.layer_add", icon='NLA_PUSHDOWN')

        tracks = list(ad.nla_tracks)
        if not tracks:
            layout.label(text="No layers — push a base clip, then add", icon='INFO')
            return

        # Stack drawn top-down (NLA evaluates bottom-up, so reverse for display)
        for track in reversed(tracks):
            strip = _first_strip(track)
            box = layout.box()
            header = box.row(align=True)
            is_base = strip is not None and strip.blend_type == 'REPLACE'
            header.label(
                text=track.name,
                icon='ACTION' if is_base else 'NLA',
            )
            header.prop(track, "mute", text="", icon='HIDE_ON' if track.mute else 'HIDE_OFF', emboss=False)
            header.operator("pipe_sculpt.layer_remove", text="", icon='X', emboss=False).track = track.name
            if strip is None:
                continue
            row = box.row(align=True)
            if is_base:
                row.label(text="Base (replace)")
            else:
                row.prop(strip, "blend_type", text="")
                infl = layer_core.influence_percent(_read_influence(strip))
                row.operator("pipe_sculpt.layer_influence", text=f"{infl}%").track = track.name


_classes = (
    PIPESCULPT_OT_layer_add,
    PIPESCULPT_OT_layer_remove,
    PIPESCULPT_OT_layer_influence,
    PIPESCULPT_PT_layers,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
