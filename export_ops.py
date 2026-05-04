"""Unity-ready FBX export.

Wraps Blender's FBX exporter with settings the Unity 6 (2026) importer accepts.
The hard part is axis conversion: Blender is Z-up, Unity is Y-up, and there
are two valid Blender→Unity recipes that both work but require different
Unity-side settings. We expose them as `axis_mode`:

  BAKED (default):
    bake_space_transform=True, axis_forward='-Z', axis_up='Y'
    The -90° X rotation is baked into mesh data; FBX header still claims
    Y-up. Unity reads the FBX as-is — no Bake Axis Conversion needed in
    the importer. Gotcha: rotation/scale animation curves in Z-up coords
    will not match the baked geometry, so this mode is best for static or
    bind-pose-only exports.

  DECLARED:
    bake_space_transform=False, axis_forward='-Z', axis_up='Y'
    Mesh data stays in Blender's Z-up; FBX header declares Y-up. Unity 6
    must have "Bake Axis Conversion" = ON on the importer (Inspector →
    Model → Scene). Animation curves stay numerically aligned with the
    Blender source.

Other Unity-relevant settings are constants:
  - apply_transforms baked via use_mesh_modifiers (no negative scales)
  - use_armature_deform_only = True (only deform bones reach Unity Humanoid)
  - mesh_smooth_type = 'FACE' (matches MikkTSpace tangent generation)
  - use_tspace = True (export tangents for normal-map shading)
  - colors_type = 'SRGB' (Unity 6 color management default)
  - bake_anim = False by default (poses/anims authored separately)

Optional pre-export modifier stack:
  - Triangulate modifier (sticky, applied) so Unity doesn't re-triangulate
    against the bake's triangulation, which would produce normal-map seams.
"""
from __future__ import annotations

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper


AXIS_MODES = (
    ('BAKED', "Baked (no Unity tweak)",
     "Bake -90° X into mesh data; works with default Unity 6 importer. "
     "Best for static / bind-pose exports"),
    ('DECLARED', "Declared (modern, with Unity tweak)",
     "Keep Blender Z-up in mesh data; FBX header declares Y-up. "
     "Requires 'Bake Axis Conversion' = ON in Unity 6 importer"),
)


def _ensure_triangulated(mesh_obj):
    """Add a sticky-applied Triangulate modifier so the export matches the bake."""
    existing = next(
        (m for m in mesh_obj.modifiers if m.type == 'TRIANGULATE'), None
    )
    if existing is not None:
        return existing
    mod = mesh_obj.modifiers.new(name="SculptKit Triangulate", type='TRIANGULATE')
    mod.quad_method = 'BEAUTY'
    mod.ngon_method = 'BEAUTY'
    mod.keep_custom_normals = True
    return mod


def _default_export_path(blend_path):
    if blend_path:
        return os.path.join(os.path.dirname(blend_path), "export.fbx")
    return ""


class SCULPTKIT_OT_export_unity_fbx(Operator, ExportHelper):
    bl_idname = "sculpt_kit.export_unity_fbx"
    bl_label = "Export FBX (Unity)"
    bl_description = (
        "Export the active mesh + its armature as an FBX with Unity 6 importer "
        "settings (Y-up, MikkTSpace tangents, no scale, triangulated)"
    )
    bl_options = {'REGISTER'}

    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={'HIDDEN'})

    axis_mode: EnumProperty(
        name="Axis Mode",
        description="How to encode Blender Z-up → Unity Y-up axis conversion",
        items=AXIS_MODES,
        default='BAKED',
    )
    triangulate: BoolProperty(
        name="Triangulate",
        description="Add a Triangulate modifier so Unity does not re-triangulate after import",
        default=True,
    )
    apply_modifiers: BoolProperty(
        name="Apply Modifiers",
        description="Bake all modifiers (including Armature) into mesh data on export",
        default=True,
    )
    bake_anim: BoolProperty(
        name="Bake Animation",
        description="Export current animation actions",
        default=False,
    )
    only_selected: BoolProperty(
        name="Selected Only",
        description="Export only currently selected objects (off = whole scene's mesh+armature)",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type in {'MESH', 'ARMATURE'}

    def invoke(self, context, event):
        addon = context.preferences.addons.get(__package__)
        if addon is not None:
            prefs = addon.preferences
            self.triangulate = prefs.export_triangulate
            self.apply_modifiers = prefs.export_apply_modifiers
            self.axis_mode = prefs.export_axis_mode
        if not self.filepath:
            self.filepath = _default_export_path(bpy.data.filepath) or "character.fbx"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        active = context.active_object
        targets = [o for o in context.selected_objects if o.type in {'MESH', 'ARMATURE'}]
        if active and active.type in {'MESH', 'ARMATURE'} and active not in targets:
            targets.append(active)
        if not targets:
            self.report({'ERROR'}, "No mesh/armature to export")
            return {'CANCELLED'}

        added_modifiers = []
        if self.triangulate:
            for o in targets:
                if o.type == 'MESH':
                    mod = _ensure_triangulated(o)
                    if mod.name == "SculptKit Triangulate":
                        added_modifiers.append((o, mod.name))

        # Re-select target set (FBX exporter respects use_selection)
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        if active is not None:
            context.view_layer.objects.active = active

        try:
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=self.only_selected,
                use_active_collection=False,
                global_scale=1.0,
                apply_unit_scale=True,
                apply_scale_options='FBX_SCALE_NONE',
                bake_space_transform=(self.axis_mode == 'BAKED'),
                axis_forward='-Z',
                axis_up='Y',
                object_types={'MESH', 'ARMATURE', 'EMPTY'},
                use_mesh_modifiers=self.apply_modifiers,
                mesh_smooth_type='FACE',
                use_tspace=True,
                colors_type='SRGB',
                use_custom_props=False,
                add_leaf_bones=False,
                primary_bone_axis='Y',
                secondary_bone_axis='X',
                use_armature_deform_only=True,
                armature_nodetype='NULL',
                bake_anim=self.bake_anim,
                bake_anim_use_all_bones=True,
                bake_anim_use_nla_strips=False,
                bake_anim_use_all_actions=False,
                path_mode='COPY',
                embed_textures=False,
                batch_mode='OFF',
            )
        except Exception as e:
            for obj, mod_name in added_modifiers:
                if mod_name in obj.modifiers:
                    obj.modifiers.remove(obj.modifiers[mod_name])
            self.report({'ERROR'}, f"FBX export failed: {e}")
            return {'CANCELLED'}

        # Keep the Triangulate modifier — user may want to re-export later.
        # If they don't, they can remove it manually.

        self.report(
            {'INFO'},
            f"Exported {len(targets)} object(s) to '{self.filepath}'",
        )
        return {'FINISHED'}


_classes = (SCULPTKIT_OT_export_unity_fbx,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
