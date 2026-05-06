"""Manual retopology helper.

One-click setup that configures the standard manual-retopo workflow correctly:
  - locks the high-poly so the user can't accidentally move it
  - spawns (or adapts) a retopo mesh with Mirror + Shrinkwrap modifiers
  - turns on the Blender 5.x **Retopology overlay** (replaces the legacy
    `In Front + Xray` hack — renders the retopo mesh on top of the high-poly
    with a small offset so there's no z-fighting)
  - configures snap settings the way Blender Secrets demonstrates:
      snap_elements          = {FACE}
      snap_elements_individual = {FACE_PROJECT}    <-- the magic fix for
                                                    "snap chaos: all verts
                                                    snap to the side facing
                                                    camera". Only the vertex
                                                    you're moving snaps,
                                                    via projection.
      use_snap_backface_culling = True
  - enables X-symmetry in Edit Mode

Finish operator applies Mirror + Shrinkwrap, transfers GTR bone tags from the
high-poly via KDTree (Phase 3), and hides the high-poly so the result is the
production-ready low-poly + tags.
"""
from __future__ import annotations

import bpy
import mathutils
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator

from . import rigging


RETOPO_NAME_SUFFIX = "_retopo_manual"
MIRROR_MOD_NAME = "PipeSculpt Mirror"
SHRINKWRAP_MOD_NAME = "PipeSculpt Shrinkwrap"

# Custom prop names — survive renames so Finish/Cancel can still pair
# the retopo with its high-poly when the user has changed object names.
RETOPO_HIGH_PROP = "pipe_sculpt_retopo_high"
RETOPO_MARKER_PROP = "pipe_sculpt_retopo_active"


def _find_3d_view_space(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            return area.spaces.active
    return None


def _resolve_high_and_retopo(context):
    """Pick high-poly and retopo target from current selection.

    Cases handled:
      1. Active object is a mesh and is the only mesh selected -> active is
         high-poly, no retopo yet (will be created).
      2. Two meshes selected, active is one of them -> active is retopo target,
         the other is high-poly.
    """
    active = context.active_object
    if active is None or active.type != 'MESH':
        return None, None
    selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
    if len(selected_meshes) == 1:
        return active, None
    if len(selected_meshes) == 2 and active in selected_meshes:
        other = next(o for o in selected_meshes if o is not active)
        return other, active
    return None, None


def _spawn_retopo_mesh(context, high):
    """Create a retopo mesh with a single vertex on X=0 at high-poly's origin.

    Earlier versions added a 10cm primitive plane, but its 4 verts at
    (±0.05, ±0.05, 0) collided with X-symmetry: not exactly on X=0, so
    Mirror's merge_threshold didn't fuse them and the user got 8
    overlapping verts. A single vertex at X=0 mirrors cleanly (merge
    eats the duplicate) and gives the user a starting point to extrude
    from. Shrinkwrap pulls it onto the high-poly surface immediately.
    """
    loc = high.matrix_world @ mathutils.Vector((0.0, 0.0, 0.0))
    mesh_data = bpy.data.meshes.new(f"{high.name}{RETOPO_NAME_SUFFIX}")
    # One vertex at the local origin (X=0); Shrinkwrap snaps it to surface.
    mesh_data.from_pydata([(0.0, 0.0, 0.0)], [], [])
    mesh_data.update()
    obj = bpy.data.objects.new(mesh_data.name, mesh_data)
    obj.location = loc
    context.collection.objects.link(obj)
    return obj


def _ensure_modifiers(retopo, high, shrinkwrap_offset: float):
    """Add Mirror + Shrinkwrap and force the canonical order (Mirror → Shrinkwrap).

    Order matters: Shrinkwrap must run AFTER Mirror so it sees the mirrored
    geometry and projects both halves onto the high-poly. Reverse order
    leaves the mirror half un-projected and produces broken topology.
    """
    # Mirror with clipping
    mir = next((m for m in retopo.modifiers if m.name == MIRROR_MOD_NAME), None)
    if mir is None:
        mir = retopo.modifiers.new(name=MIRROR_MOD_NAME, type='MIRROR')
    mir.use_axis = (True, False, False)
    mir.use_clip = True
    mir.use_mirror_merge = True
    # Scale merge threshold to mesh size — a fixed 1mm is too coarse on
    # 10cm props and too fine on 10m hero meshes.
    bbox = max(retopo.dimensions.x, retopo.dimensions.y, retopo.dimensions.z, 0.1)
    mir.merge_threshold = max(0.0001, bbox * 0.001)

    # Shrinkwrap to high-poly. PROJECT along negative Z is the Blender Secrets
    # default for retopo, but NEAREST_SURFACEPOINT works for the all-angle
    # case where the user is moving verts manually with Face Project snap.
    sw = next((m for m in retopo.modifiers if m.name == SHRINKWRAP_MOD_NAME), None)
    if sw is None:
        sw = retopo.modifiers.new(name=SHRINKWRAP_MOD_NAME, type='SHRINKWRAP')
    sw.target = high
    sw.wrap_method = 'NEAREST_SURFACEPOINT'
    sw.offset = shrinkwrap_offset

    # Force order: Mirror first, then Shrinkwrap. Idempotent — moves are no-ops
    # if the modifier is already at the right index.
    bpy.ops.object.modifier_move_to_index(modifier=MIRROR_MOD_NAME, index=0)
    bpy.ops.object.modifier_move_to_index(modifier=SHRINKWRAP_MOD_NAME, index=1)


# Scene props snapshotting prior tool_settings so Finish/Cancel can restore them
_SNAP_PROPS = (
    "use_snap",
    "snap_elements",
    "snap_elements_individual",
    "snap_target",
    "use_snap_backface_culling",
    "use_snap_self",
    "use_snap_align_rotation",
)
SNAP_SNAPSHOT_KEY = "pipe_sculpt_snap_snapshot"


def _snapshot_snap(context):
    """Save current tool_settings snap state into a scene custom prop."""
    ts = context.scene.tool_settings
    snapshot = {}
    for p in _SNAP_PROPS:
        v = getattr(ts, p, None)
        # bpy_prop_set is not JSON-serialisable; convert to list
        if hasattr(v, '__iter__') and not isinstance(v, str):
            snapshot[p] = list(v)
        else:
            snapshot[p] = v
    import json as _json
    context.scene[SNAP_SNAPSHOT_KEY] = _json.dumps(snapshot)


def _restore_snap(context):
    """Restore tool_settings snap state from the scene custom prop, if present."""
    snap_json = context.scene.get(SNAP_SNAPSHOT_KEY)
    if not snap_json:
        return
    import json as _json
    try:
        snapshot = _json.loads(snap_json)
    except ValueError:
        return
    ts = context.scene.tool_settings
    for p in _SNAP_PROPS:
        if p not in snapshot:
            continue
        v = snapshot[p]
        try:
            if isinstance(v, list):
                setattr(ts, p, set(v))
            else:
                setattr(ts, p, v)
        except (TypeError, AttributeError):
            continue
    del context.scene[SNAP_SNAPSHOT_KEY]


def _configure_snap(context):
    _snapshot_snap(context)
    ts = context.scene.tool_settings
    ts.use_snap = True
    ts.snap_elements = {'FACE'}
    ts.snap_elements_individual = {'FACE_PROJECT'}
    ts.snap_target = 'CLOSEST'
    ts.use_snap_backface_culling = True
    ts.use_snap_self = False
    ts.use_snap_align_rotation = False


def _configure_retopology_overlay(context, offset: float = 0.01):
    space = _find_3d_view_space(context)
    if space is None:
        return False
    ovl = space.overlay
    if hasattr(ovl, 'show_retopology'):
        ovl.show_retopology = True
        if hasattr(ovl, 'retopology_offset'):
            ovl.retopology_offset = offset
        return True
    return False


def _lock_high_poly(high):
    """Make the high-poly unselectable so the user can't grab it by accident."""
    high.hide_select = True


class PIPESCULPT_OT_retopo_manual_setup(Operator):
    bl_idname = "pipe_sculpt.retopo_manual_setup"
    bl_label = "Setup Manual Retopo"
    bl_description = (
        "Configure the scene for manual retopology on the active high-poly. "
        "Adds Mirror + Shrinkwrap, turns on the Retopology overlay, sets "
        "Face Project snap (no more 'snap chaos'), enters Edit Mode"
    )
    bl_options = {'REGISTER', 'UNDO'}

    shrinkwrap_offset: FloatProperty(
        name="Shrinkwrap Offset",
        description="Distance the retopo verts sit above the high-poly surface",
        default=0.001,
        min=0.0,
        max=0.1,
    )
    overlay_offset: FloatProperty(
        name="Overlay Offset",
        description="Retopology overlay z-offset to avoid z-fighting",
        default=0.01,
        min=0.0,
        max=1.0,
    )
    lock_high_poly: BoolProperty(
        name="Lock High-Poly Selectable",
        description="Make the high-poly unselectable so you don't grab it by mistake",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        high, retopo = _resolve_high_and_retopo(context)
        if high is None:
            self.report({'ERROR'}, "Couldn't resolve high-poly — select 1 mesh (high-poly) "
                                   "or 2 meshes (high-poly + retopo target with retopo active)")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        if retopo is None:
            retopo = _spawn_retopo_mesh(context, high)

        # _ensure_modifiers calls modifier_move_to_index which is an operator
        # and needs the retopo as both selected and active.
        bpy.ops.object.select_all(action='DESELECT')
        retopo.select_set(True)
        context.view_layer.objects.active = retopo

        # Pin the high-poly identity on the retopo as a custom prop. This
        # survives object renames (so Finish still pairs them up) and lets us
        # detect "an active retopo session" from outside of name conventions.
        retopo[RETOPO_HIGH_PROP] = high.name
        retopo[RETOPO_MARKER_PROP] = True

        _ensure_modifiers(retopo, high, self.shrinkwrap_offset)

        if self.lock_high_poly:
            _lock_high_poly(high)

        _configure_snap(context)
        overlay_ok = _configure_retopology_overlay(context, self.overlay_offset)

        # Select retopo, enter edit mode with X symmetry on
        bpy.ops.object.select_all(action='DESELECT')
        retopo.select_set(True)
        context.view_layer.objects.active = retopo
        bpy.ops.object.mode_set(mode='EDIT')
        retopo.data.use_mirror_x = True

        msg = f"Retopo setup ready on '{retopo.name}' (high-poly: '{high.name}')"
        if not overlay_ok:
            msg += " — overlay toggle skipped (no 3D view found)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class PIPESCULPT_OT_retopo_manual_finish(Operator):
    bl_idname = "pipe_sculpt.retopo_manual_finish"
    bl_label = "Finish Manual Retopo"
    bl_description = (
        "Apply Mirror + Shrinkwrap on the active retopo mesh, transfer GTR bone "
        "tags from the paired high-poly via KDTree, hide the high-poly"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return False
        # Accept either the prop marker (preferred — survives renames) or the
        # legacy suffix convention (older retopo sessions saved before the
        # marker existed).
        return bool(obj.get(RETOPO_MARKER_PROP)) or obj.name.endswith(RETOPO_NAME_SUFFIX)

    def execute(self, context):
        retopo = context.active_object
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Resolve high-poly: prop marker first (rename-safe), then legacy suffix.
        high_name = retopo.get(RETOPO_HIGH_PROP)
        if not high_name and retopo.name.endswith(RETOPO_NAME_SUFFIX):
            high_name = retopo.name[: -len(RETOPO_NAME_SUFFIX)]
        high = bpy.data.objects.get(high_name) if high_name else None
        if high is None or high.type != 'MESH':
            self.report(
                {'ERROR'},
                f"Could not find paired high-poly '{high_name}'. "
                "Re-run Setup Manual Retopo with both meshes selected.",
            )
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        retopo.select_set(True)
        context.view_layer.objects.active = retopo

        # Apply Mirror first, then Shrinkwrap (order matters: shrinkwrap should
        # see the mirrored geometry)
        for mod_name in (MIRROR_MOD_NAME, SHRINKWRAP_MOD_NAME):
            mod = retopo.modifiers.get(mod_name)
            if mod is None:
                continue
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except RuntimeError as e:
                self.report({'WARNING'}, f"Failed to apply {mod_name}: {e}")
                retopo.modifiers.remove(mod)

        # GTR Phase 3: transfer bone tags from high-poly to the new retopo
        if rigging.VERTEX_ATTR in high.data.attributes:
            transferred = rigging.transfer_bone_tags_from_high(high, retopo)
            tag_msg = "GTR tags transferred" if transferred else "GTR transfer skipped"
        else:
            tag_msg = "no GTR tags on high-poly"

        # Hide and unlock high-poly
        high.hide_select = False
        high.hide_set(True)

        # Clean up our pairing props — session is over, don't leak state
        for prop in (RETOPO_HIGH_PROP, RETOPO_MARKER_PROP):
            if prop in retopo:
                del retopo[prop]

        # Disable Edit-mode X mirror — Mirror modifier was just applied so
        # the geometry is already mirrored; leaving use_mirror_x on would
        # add a redundant edit-mode mirror that prevents X=0 verts from
        # moving off-axis (confusing for the user).
        retopo.data.use_mirror_x = False

        # Restore prior snap settings instead of nulling them
        _restore_snap(context)

        # Turn off retopology overlay
        space = _find_3d_view_space(context)
        if space is not None and hasattr(space.overlay, 'show_retopology'):
            space.overlay.show_retopology = False

        self.report({'INFO'}, f"Finished retopo on '{retopo.name}'; {tag_msg}")
        return {'FINISHED'}


class PIPESCULPT_OT_retopo_manual_cancel(Operator):
    bl_idname = "pipe_sculpt.retopo_manual_cancel"
    bl_label = "Cancel Manual Retopo"
    bl_description = (
        "Abort an active retopo session: unlock the high-poly, drop "
        "the retopo's Mirror+Shrinkwrap modifiers, restore prior snap "
        "settings. Does NOT delete the retopo mesh"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Available whenever a retopo session is detected — either via the
        # marker prop on the active mesh, or any mesh in the file with the
        # marker (so the user can recover from a save/reload).
        obj = context.active_object
        if obj is not None and obj.get(RETOPO_MARKER_PROP):
            return True
        return any(o.get(RETOPO_MARKER_PROP) for o in bpy.data.objects)

    def execute(self, context):
        retopo = context.active_object
        if retopo is None or not retopo.get(RETOPO_MARKER_PROP):
            # Find any retopo session in the file
            retopo = next(
                (o for o in bpy.data.objects if o.get(RETOPO_MARKER_PROP)),
                None,
            )
        if retopo is None:
            self.report({'ERROR'}, "No active retopo session found")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # Unlock paired high-poly if we can find it
        high_name = retopo.get(RETOPO_HIGH_PROP)
        if high_name:
            high = bpy.data.objects.get(high_name)
            if high is not None:
                high.hide_select = False

        # Drop our session modifiers (don't apply — user is bailing)
        for mod_name in (MIRROR_MOD_NAME, SHRINKWRAP_MOD_NAME):
            mod = retopo.modifiers.get(mod_name)
            if mod is not None:
                retopo.modifiers.remove(mod)

        # Clean up props + snap state
        for prop in (RETOPO_HIGH_PROP, RETOPO_MARKER_PROP):
            if prop in retopo:
                del retopo[prop]
        retopo.data.use_mirror_x = False
        _restore_snap(context)

        space = _find_3d_view_space(context)
        if space is not None and hasattr(space.overlay, 'show_retopology'):
            space.overlay.show_retopology = False

        self.report({'INFO'}, f"Cancelled retopo session on '{retopo.name}'")
        return {'FINISHED'}


class PIPESCULPT_OT_retopo_relax(Operator):
    bl_idname = "pipe_sculpt.retopo_relax"
    bl_label = "Relax Geometry"
    bl_description = (
        "Switch the active retopo mesh into Sculpt Mode with the Relax Slide "
        "brush activated, so you can paint-equalise bunched-up topology "
        "without changing the silhouette"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        obj = context.active_object

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='SCULPT')

        # Activate Relax Slide from the essentials brush library
        try:
            bpy.ops.brush.asset_activate(
                asset_library_type='ESSENTIALS',
                asset_library_identifier="",
                relative_asset_identifier=(
                    "brushes/essentials_brushes-mesh_sculpt.blend/Brush/Relax Slide"
                ),
            )
        except RuntimeError:
            try:
                bpy.ops.brush.asset_activate(
                    asset_library_type='ALL',
                    asset_library_identifier="",
                    relative_asset_identifier=(
                        "brushes/essentials_brushes-mesh_sculpt.blend/Brush/Relax Slide"
                    ),
                )
            except RuntimeError as e:
                self.report({'WARNING'}, f"Couldn't activate Relax Slide brush: {e}")

        self.report(
            {'INFO'},
            "Relax Slide active — paint over bunched topology to redistribute it",
        )
        return {'FINISHED'}


_classes = (
    PIPESCULPT_OT_retopo_manual_setup,
    PIPESCULPT_OT_retopo_manual_finish,
    PIPESCULPT_OT_retopo_manual_cancel,
    PIPESCULPT_OT_retopo_relax,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
