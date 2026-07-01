"""Visualisation overlays — wireframe / stats / normals toggles.

Pure bpy: these operators flip viewport overlay properties. No core
logic to test.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator, Panel


def _find_3d_view_space(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    return space
    return None


class PIPESCULPT_OT_viz_wireframe(Operator):
    bl_idname = "pipe_sculpt.viz_wireframe"
    bl_label = "Toggle Wireframe Overlay"
    bl_description = "Show / hide mesh wireframe on top of shading. Use to spot bad topology"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _find_3d_view_space(context) is not None

    def execute(self, context):
        space = _find_3d_view_space(context)
        space.overlay.show_wireframes = not space.overlay.show_wireframes
        state = "ON" if space.overlay.show_wireframes else "OFF"
        self.report({'INFO'}, f"Wireframe overlay {state}")
        return {'FINISHED'}


class PIPESCULPT_OT_viz_stats(Operator):
    bl_idname = "pipe_sculpt.viz_stats"
    bl_label = "Toggle Scene Statistics"
    bl_description = (
        "Show / hide vertex / face / triangle counts in the viewport. "
        "Use to keep an eye on polycount while sculpting"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _find_3d_view_space(context) is not None

    def execute(self, context):
        space = _find_3d_view_space(context)
        space.overlay.show_stats = not space.overlay.show_stats
        state = "ON" if space.overlay.show_stats else "OFF"
        self.report({'INFO'}, f"Statistics overlay {state}")
        return {'FINISHED'}


class PIPESCULPT_OT_viz_normals(Operator):
    bl_idname = "pipe_sculpt.viz_normals"
    bl_label = "Toggle Face Normals"
    bl_description = (
        "Show / hide face normal indicators in Edit Mode. Use to spot "
        "flipped faces before baking — flipped normals = black bake spots"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and _find_3d_view_space(context) is not None

    def execute(self, context):
        space = _find_3d_view_space(context)
        space.overlay.show_face_normals = not space.overlay.show_face_normals
        state = "ON" if space.overlay.show_face_normals else "OFF"
        self.report({'INFO'}, f"Face normals overlay {state}")
        return {'FINISHED'}


class PIPESCULPT_PT_viz_stats_live(Panel):
    """Live polycount display in the side panel — no toggle needed."""
    bl_idname = "PIPESCULPT_PT_viz_stats_live"
    bl_label = "Mesh Stats"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PipeSculpt"
    bl_order = 30

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        mesh = obj.data

        # All len() reads are O(1). NEVER iterate polygons here — this panel
        # redraws on every viewport update (constantly while sculpting/posing),
        # so an O(n) triangle sum froze the UI on heavy/multires meshes.
        n_faces = len(mesh.polygons)
        col = layout.column(align=True)
        col.label(text=f"Vertices: {len(mesh.vertices):,}", icon='VERTEXSEL')
        col.label(text=f"Edges: {len(mesh.edges):,}", icon='EDGESEL')
        col.label(text=f"Faces: {n_faces:,}", icon='FACESEL')
        # Rough triangle estimate (quads → ~2 tris) without touching polygons.
        col.label(text=f"~Triangles: {n_faces * 2:,}", icon='MESH_DATA')

        # Polycount budget hints (based on the O(1) face count)
        layout.separator()
        col = layout.column(align=True)
        if n_faces == 0:
            col.label(text="(empty mesh)", icon='ERROR')
        elif n_faces > 50_000:
            col.label(text="> 100k tris — sculpt only", icon='ERROR')
        elif n_faces > 25_000:
            col.label(text="50-100k tris — hero range", icon='INFO')
        elif n_faces > 2_500:
            col.label(text="Unity-ready", icon='CHECKMARK')
        else:
            col.label(text="Low-poly", icon='CHECKMARK')

        # Quick toggle row
        layout.separator()
        row = layout.row(align=True)
        row.operator("pipe_sculpt.viz_wireframe", text="Wire", icon='SHADING_WIRE')
        row.operator("pipe_sculpt.viz_stats", text="Stats", icon='INFO')


_classes = (
    PIPESCULPT_OT_viz_wireframe,
    PIPESCULPT_OT_viz_stats,
    PIPESCULPT_OT_viz_normals,
    PIPESCULPT_PT_viz_stats_live,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
