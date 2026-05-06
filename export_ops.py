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
import mathutils
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
    mod = mesh_obj.modifiers.new(name="PipeSculpt Triangulate", type='TRIANGULATE')
    mod.quad_method = 'BEAUTY'
    mod.ngon_method = 'BEAUTY'
    mod.keep_custom_normals = True
    return mod


def _default_export_path(blend_path):
    if blend_path:
        return os.path.join(os.path.dirname(blend_path), "export.fbx")
    return ""


class PIPESCULPT_OT_export_unity_fbx(Operator, ExportHelper):
    bl_idname = "pipe_sculpt.export_unity_fbx"
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
                    if mod.name == "PipeSculpt Triangulate":
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


def _build_axis_calibration_mesh(name: str):
    """Build an asymmetric L-shape with directional indicators.

    Geometry layout in Blender (Z-up, +Y forward, +X right):
      - Centre cube at origin (size 0.4) — reference body
      - Tall thin pillar on +Z (length 1.0) — should point UP in Unity
      - Short stub on +X (length 0.6) — should point RIGHT in Unity
      - Short stub on +Y (length 0.4) — should point FORWARD in Unity

    The three arms have visibly different lengths so the Unity importer
    can be visually verified at a glance: which axis is which after the
    Z-up → Y-up conversion.
    """
    import bmesh

    bm = bmesh.new()
    # Centre cube
    bmesh.ops.create_cube(bm, size=0.4)

    # +Z arm (UP indicator) — tallest
    bmesh.ops.create_cube(bm, size=0.15, matrix=mathutils.Matrix.Translation((0.0, 0.0, 0.7)))
    # +X arm (RIGHT indicator) — medium
    bmesh.ops.create_cube(bm, size=0.15, matrix=mathutils.Matrix.Translation((0.45, 0.0, 0.0)))
    # +Y arm (FORWARD indicator) — shortest
    bmesh.ops.create_cube(bm, size=0.15, matrix=mathutils.Matrix.Translation((0.0, 0.30, 0.0)))

    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


class PIPESCULPT_OT_export_axis_calibration(Operator):
    bl_idname = "pipe_sculpt.export_axis_calibration"
    bl_label = "Export Axis Calibration FBX (Both Modes)"
    bl_description = (
        "Export a small reference mesh (cube + 3 directional arms) in BOTH "
        "BAKED and DECLARED axis modes to a folder, plus a README with the "
        "Unity 6 verification procedure. Use to validate that DECLARED mode "
        "round-trips correctly through your Unity importer settings"
    )
    bl_options = {'REGISTER'}

    directory: StringProperty(
        name="Output Folder",
        description="Folder to write 'baked.fbx' + 'declared.fbx' + 'README.txt'",
        subtype='DIR_PATH',
    )

    def invoke(self, context, event):
        if not self.directory:
            blend_path = bpy.data.filepath
            self.directory = os.path.dirname(blend_path) if blend_path else os.path.expanduser("~")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        out_dir = bpy.path.abspath(self.directory)
        if not os.path.isdir(out_dir):
            self.report({'ERROR'}, f"Output folder doesn't exist: {out_dir}")
            return {'CANCELLED'}

        # Build the calibration mesh
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        prior_active = context.view_layer.objects.active
        prior_selection = list(context.selected_objects)

        mesh_data = _build_axis_calibration_mesh("PipeSculpt_AxisCalibration")
        cal_obj = bpy.data.objects.new("PipeSculpt_AxisCalibration", mesh_data)
        context.collection.objects.link(cal_obj)
        bpy.ops.object.select_all(action='DESELECT')
        cal_obj.select_set(True)
        context.view_layer.objects.active = cal_obj

        # Export both modes side by side
        try:
            for mode_id, fname in (('BAKED', 'baked.fbx'), ('DECLARED', 'declared.fbx')):
                bpy.ops.export_scene.fbx(
                    filepath=os.path.join(out_dir, fname),
                    use_selection=True,
                    use_active_collection=False,
                    global_scale=1.0,
                    apply_unit_scale=True,
                    apply_scale_options='FBX_SCALE_NONE',
                    bake_space_transform=(mode_id == 'BAKED'),
                    axis_forward='-Z',
                    axis_up='Y',
                    object_types={'MESH'},
                    use_mesh_modifiers=True,
                    mesh_smooth_type='FACE',
                    use_tspace=True,
                    colors_type='SRGB',
                    use_custom_props=False,
                    add_leaf_bones=False,
                    bake_anim=False,
                    path_mode='COPY',
                    embed_textures=False,
                    batch_mode='OFF',
                )
        finally:
            # Always clean up the calibration object, even on export failure
            bpy.data.objects.remove(cal_obj, do_unlink=True)
            bpy.data.meshes.remove(mesh_data, do_unlink=True)
            # Restore prior selection
            for o in prior_selection:
                if o.name in bpy.data.objects:
                    o.select_set(True)
            if prior_active is not None and prior_active.name in bpy.data.objects:
                context.view_layer.objects.active = prior_active

        # Write the verification procedure
        readme_path = os.path.join(out_dir, "README.txt")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(_AXIS_CALIBRATION_README)

        self.report(
            {'INFO'},
            f"Wrote baked.fbx + declared.fbx + README.txt to {out_dir}",
        )
        return {'FINISHED'}


_AXIS_CALIBRATION_README = """\
PipeSculpt — DECLARED axis-mode round-trip verification

Goal: confirm that the DECLARED FBX axis mode (bake_space_transform=False,
axis -Z/Y) imports correctly into your Unity 6 setup so PipeSculpt can
flag DECLARED as production-ready.

The two FBX files in this folder were exported from the same source mesh
in Blender. The mesh is a centre cube plus three asymmetric arms:

  +Z (UP):      tallest arm, 0.7 m above origin
  +X (RIGHT):   medium arm, 0.45 m to the right of origin
  +Y (FORWARD): shortest arm, 0.30 m forward of origin

After import to Unity 6, each arm should map to the matching Unity axis:

  Unity +Y (up)      ← Blender +Z (cube's tallest arm)
  Unity +X (right)   ← Blender +X (cube's medium arm)
  Unity +Z (forward) ← Blender +Y (cube's shortest arm)

================================================================
Test 1 — BAKED mode (this should already work without tweaks)
================================================================

1. Drop baked.fbx into Unity 6's Project window.
2. Select the imported asset, open Inspector → Model tab.
3. Verify under "Scene":
     - Bake Axis Conversion: OFF
4. Drag the imported prefab into the scene. Front view (Camera looking
   down +Z, i.e. press '2' on numpad with default camera), check:
     - Tallest arm points UP (Y+)
     - Medium arm points RIGHT (X+)
     - Shortest arm points FORWARD (away from camera, Z+)
5. Pass criteria: all three arms point at the expected Unity axis.

================================================================
Test 2 — DECLARED mode (the one we're verifying)
================================================================

1. Drop declared.fbx into Unity 6's Project window.
2. Select the imported asset, open Inspector → Model tab.
3. Under "Scene", set:
     - Bake Axis Conversion: ON
   Click "Apply".
4. Drag the imported prefab into the scene.
5. Verify the same axis mapping as Test 1:
     - Tallest arm points UP
     - Medium arm points RIGHT
     - Shortest arm points FORWARD
6. Pass criteria: all three arms point at the expected Unity axis,
   identical to Test 1.

================================================================
Reporting back
================================================================

If both tests pass: DECLARED mode is verified and PipeSculpt's
README/MANUAL can drop the "not yet round-trip tested" caveat. Set the
Preferences default to either mode based on which workflow you prefer.

If Test 2 fails (DECLARED arms point wrong way) or only works with
"Bake Axis Conversion" OFF: we have a Blender export setting wrong.
Note which arm points where ("the tallest arm points -Z instead of +Y")
and report — that pinpoints which axis the converter is double-rotating.
"""


_classes = (
    PIPESCULPT_OT_export_unity_fbx,
    PIPESCULPT_OT_export_axis_calibration,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
