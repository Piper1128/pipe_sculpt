"""Onion skinning — Phase 3 §F. Ghost poses of the deformed mesh around the
current frame, so you can see the motion arc.

Snapshots the *evaluated* (deformed) mesh at neighbouring frames into static
"ghost" objects, tinted past=blue / future=warm, fading with distance, in a
dedicated collection that's hidden from render and selection.

Caveat (SPIKE §F): in headless background mode, IK constraints block the
armature→mesh deform eval, so the automated test poses FK bones. In
interactive Blender (where you'll use it) IK evaluates normally and the
ghosts capture the real deformed pose. Ghosts are static snapshots — re-run
Show / Refresh after editing to update them.

Transparency only renders in Material Preview / Rendered shading (the ghost
material is EEVEE-blended), so Show switches a Solid viewport to Material
Preview — matching uv_ops's checker behaviour.
"""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup

from . import onion_core


GHOST_COLLECTION = "PipeSculpt Onion Skin"
GHOST_PROP = "pipe_sculpt_onion_ghost"
GHOST_PREFIX = "Onion"
GHOST_MAT_PREFIX = "OnionGhostMat"


# ----------------------------------------------------------------------
# Live panel settings (persist on the scene, edited in the Onion panel)
# ----------------------------------------------------------------------

def _on_setting_changed(self, context):
    """Live update: if ghosts are showing, rebuild them when a setting changes."""
    if self.auto_refresh and _count_ghosts() > 0:
        try:
            bpy.ops.pipe_sculpt.onion_show('EXEC_DEFAULT')
        except RuntimeError:
            pass


class PIPESCULPT_PG_onion(PropertyGroup):
    frames_before: IntProperty(
        name="Before", description="Ghosts before the current frame",
        default=3, min=0, max=20, update=_on_setting_changed,
    )
    frames_after: IntProperty(
        name="After", description="Ghosts after the current frame",
        default=3, min=0, max=20, update=_on_setting_changed,
    )
    step: IntProperty(
        name="Spacing", description="Frames between ghosts (1 = every frame)",
        default=1, min=1, max=20, update=_on_setting_changed,
    )
    base_alpha: FloatProperty(
        name="Opacity", description="Nearest ghost's opacity (far ones fade)",
        default=0.5, min=0.05, max=1.0, subtype='FACTOR', update=_on_setting_changed,
    )
    auto_refresh: BoolProperty(
        name="Auto-Refresh",
        description="Rebuild ghosts automatically when a setting changes (while showing)",
        default=True,
    )


# ----------------------------------------------------------------------
# Source-mesh resolution
# ----------------------------------------------------------------------

def _source_meshes(context):
    """All meshes to snapshot.

    Active mesh → [that mesh]. Active armature → ALL of its child meshes
    (body + clothes + hair are commonly separate skinned meshes, so we
    ghost every piece, not just the first).
    """
    obj = context.active_object
    if obj is None:
        return []
    if obj.type == 'MESH':
        return [obj]
    if obj.type == 'ARMATURE':
        return [c for c in obj.children if c.type == 'MESH']
    return []


def _is_ghost(obj):
    return obj.get(GHOST_PROP) is not None


# ----------------------------------------------------------------------
# Ghost collection + cleanup
# ----------------------------------------------------------------------

def _get_ghost_collection(context, create=True):
    coll = bpy.data.collections.get(GHOST_COLLECTION)
    if coll is None and create:
        coll = bpy.data.collections.new(GHOST_COLLECTION)
        context.scene.collection.children.link(coll)
    elif coll is not None and coll.name not in context.scene.collection.children:
        try:
            context.scene.collection.children.link(coll)
        except RuntimeError:
            pass
    return coll


def _clear_ghosts(context):
    """Remove every ghost object, its mesh, its material, and the collection.

    Identity is collection membership UNION the prop marker — so a ghost at
    frame 0 (prop value int 0, which is falsy) and any object sitting in the
    onion collection are both reaped. Avoids the falsy-zero cleanup gap.
    """
    targets = {}  # id(obj) -> obj, de-duplicated
    for o in bpy.data.objects:
        if _is_ghost(o):
            targets[id(o)] = o
    coll = bpy.data.collections.get(GHOST_COLLECTION)
    if coll is not None:
        for o in list(coll.objects):
            targets[id(o)] = o

    removed = 0
    for o in list(targets.values()):
        mesh = o.data if o.type == 'MESH' else None
        bpy.data.objects.remove(o, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh, do_unlink=True)
        removed += 1

    # Orphan ghost materials
    for mat in [m for m in bpy.data.materials if m.name.startswith(GHOST_MAT_PREFIX)]:
        if mat.users == 0:
            bpy.data.materials.remove(mat, do_unlink=True)
    # Remove the collection if now empty
    coll = bpy.data.collections.get(GHOST_COLLECTION)
    if coll is not None and len(coll.objects) == 0:
        bpy.data.collections.remove(coll)
    return removed


def _count_ghosts():
    # O(1)-ish: read the ghost collection's object count instead of scanning
    # every object in the file. The panel calls this on every redraw.
    coll = bpy.data.collections.get(GHOST_COLLECTION)
    return len(coll.objects) if coll is not None else 0


# ----------------------------------------------------------------------
# Ghost construction
# ----------------------------------------------------------------------

def _ghost_material(frame, tint):
    """Per-ghost translucent material (Principled, BLEND) tinted to `tint` RGBA."""
    mat = bpy.data.materials.new(f"{GHOST_MAT_PREFIX}_f{int(round(frame))}")
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        bsdf.inputs['Base Color'].default_value = (tint[0], tint[1], tint[2], 1.0)
        if 'Alpha' in bsdf.inputs:
            bsdf.inputs['Alpha'].default_value = tint[3]
        if 'Roughness' in bsdf.inputs:
            bsdf.inputs['Roughness'].default_value = 1.0
        if 'Specular IOR Level' in bsdf.inputs:
            bsdf.inputs['Specular IOR Level'].default_value = 0.0
    return mat


def _make_ghost(context, src, frame, tint):
    """Snapshot the deformed src mesh at `frame` into a static ghost object."""
    dg = context.evaluated_depsgraph_get()
    ev = src.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)  # static copy of the evaluated mesh
    me.name = onion_core.ghost_name(f"{GHOST_PREFIX}_{src.name}", frame)
    # new_from_object copies the source's material slots; clear them so every
    # face falls back to slot 0 = our tint material (otherwise the tint is
    # appended as an unused trailing slot and ghosts render with the source
    # material — invisible tint).
    me.materials.clear()
    me.materials.append(_ghost_material(frame, tint))

    ghost = bpy.data.objects.new(me.name, me)
    ghost.matrix_world = src.matrix_world.copy()
    ghost[GHOST_PROP] = int(round(frame))
    ghost.color = tint
    ghost.hide_render = True
    ghost.hide_select = True
    ghost.display.show_shadows = False
    _get_ghost_collection(context).objects.link(ghost)
    return ghost


def _switch_to_material_preview(context):
    """Switch a Solid 3D viewport to Material Preview so the BLEND tint shows.

    Solid (Workbench) shading ignores per-material alpha, so ghosts would be
    opaque and occlude the live mesh. Matches uv_ops's checker auto-switch.
    """
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type == 'VIEW_3D' and space.shading.type == 'SOLID':
                space.shading.type = 'MATERIAL'


def _meshes_differ(ghost_a, ghost_b, eps=1e-4, samples=32):
    """Cheap check: do two ghost meshes have different geometry?

    Samples a spread of vertices. Used to warn when nothing animates the
    source (all ghosts identical → a single overlapping blob, no arc).
    """
    va, vb = ghost_a.data.vertices, ghost_b.data.vertices
    n = min(len(va), len(vb))
    if n == 0:
        return False
    step = max(1, n // samples)
    for i in range(0, n, step):
        if (va[i].co - vb[i].co).length > eps:
            return True
    return False


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------

class PIPESCULPT_OT_onion_show(Operator):
    bl_idname = "pipe_sculpt.onion_show"
    bl_label = "Show Onion Skin"
    bl_description = (
        "Snapshot the deformed mesh at neighbouring frames as translucent "
        "ghosts (past=blue, future=warm) so you can see the motion arc. "
        "Static — re-run to update. Needs Material Preview shading (auto-set)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    # -1 sentinel = "use the scene panel setting". Explicit values (incl. from
    # scripting / the redo panel) override. Lets the panel be the live control
    # surface while keeping the operator scriptable.
    frames_before: IntProperty(name="Before", default=-1, min=-1, max=20)
    frames_after: IntProperty(name="After", default=-1, min=-1, max=20)
    step: IntProperty(name="Spacing", default=-1, min=-1, max=20)
    base_alpha: FloatProperty(name="Opacity", default=-1.0, min=-1.0, max=1.0)

    @classmethod
    def poll(cls, context):
        return len(_source_meshes(context)) > 0

    def _resolved_settings(self, context):
        s = context.scene.pipe_sculpt_onion
        before = self.frames_before if self.frames_before >= 0 else s.frames_before
        after = self.frames_after if self.frames_after >= 0 else s.frames_after
        step = self.step if self.step >= 1 else s.step
        alpha = self.base_alpha if self.base_alpha >= 0.0 else s.base_alpha
        return before, after, max(1, step), alpha

    def execute(self, context):
        sources = _source_meshes(context)
        frames_before, frames_after, step, base_alpha = self._resolved_settings(context)
        if not sources:
            self.report({'ERROR'}, "No source mesh (select the mesh or its armature)")
            return {'CANCELLED'}

        scene = context.scene
        original_frame = scene.frame_current

        # Frame bounds — normalised so an inverted range can't drop a side.
        if scene.use_preview_range:
            lo, hi = scene.frame_preview_start, scene.frame_preview_end
        else:
            lo, hi = scene.frame_start, scene.frame_end
        if lo > hi:
            lo, hi = hi, lo

        if lo == hi:
            self.report({'WARNING'}, "Frame range is a single frame — nothing to ghost")
            return {'CANCELLED'}

        if original_frame < lo or original_frame > hi:
            self.report(
                {'WARNING'},
                "Playhead is outside the frame range — ghosts will be one-sided. "
                "Move it into range for a past/future arc",
            )

        frames = onion_core.ghost_frames(
            original_frame, frames_before, frames_after, step,
            frame_min=lo, frame_max=hi,
        )
        if not frames:
            self.report({'WARNING'}, "No ghost frames in range — widen Before/After or the scene range")
            return {'CANCELLED'}

        # Rebuild from scratch each time so Show doubles as Refresh
        _clear_ghosts(context)

        max_dist = max(frames_before, frames_after) * step
        # ghost objects grouped by source, to detect "no animation" afterwards
        per_source = {s.name: [] for s in sources}
        try:
            for f in frames:
                scene.frame_set(int(f))
                tint = onion_core.ghost_tint(f, original_frame, max_dist, base_alpha)
                for src in sources:
                    per_source[src.name].append(_make_ghost(context, src, f, tint))
        finally:
            scene.frame_set(original_frame)  # restore even on error

        _switch_to_material_preview(context)

        # Warn if nothing actually animates the source (all ghosts coincident)
        static = False
        for ghosts in per_source.values():
            if len(ghosts) >= 2 and not _meshes_differ(ghosts[0], ghosts[-1]):
                static = True
                break

        made = sum(len(g) for g in per_source.values())
        if static:
            self.report(
                {'WARNING'},
                f"{made} ghost(s) — but no motion detected; they overlap. "
                "Animate the rig first",
            )
        else:
            self.report({'INFO'}, f"Onion skin: {made} ghost(s) around frame {original_frame}")
        return {'FINISHED'}


class PIPESCULPT_OT_onion_clear(Operator):
    bl_idname = "pipe_sculpt.onion_clear"
    bl_label = "Clear Onion Skin"
    bl_description = "Remove all onion-skin ghosts"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _count_ghosts() > 0

    def execute(self, context):
        n = _clear_ghosts(context)
        self.report({'INFO'}, f"Cleared {n} ghost(s)")
        return {'FINISHED'}


class PIPESCULPT_PT_onion(Panel):
    bl_idname = "PIPESCULPT_PT_onion"
    bl_label = "Onion Skin"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 18  # after Additive Layers (17)

    @classmethod
    def poll(cls, context):
        return len(_source_meshes(context)) > 0

    def draw(self, context):
        layout = self.layout
        s = context.scene.pipe_sculpt_onion
        n = _count_ghosts()

        # Live controls
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(s, "frames_before")
        row.prop(s, "frames_after")
        col.prop(s, "step")
        col.prop(s, "base_alpha", slider=True)
        col.prop(s, "auto_refresh")

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("pipe_sculpt.onion_show", icon='ONIONSKIN_ON')
        if n > 0:
            col.operator("pipe_sculpt.onion_clear", icon='X')
            layout.label(text=f"{n} ghost(s) — needs Material Preview", icon='INFO')
        else:
            layout.label(text="Snapshots the deformed pose", icon='INFO')


_classes = (
    PIPESCULPT_PG_onion,
    PIPESCULPT_OT_onion_show,
    PIPESCULPT_OT_onion_clear,
    PIPESCULPT_PT_onion,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.pipe_sculpt_onion = PointerProperty(type=PIPESCULPT_PG_onion)


def unregister():
    if hasattr(bpy.types.Scene, "pipe_sculpt_onion"):
        del bpy.types.Scene.pipe_sculpt_onion
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
