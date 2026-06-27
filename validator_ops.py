"""Unity Humanoid validator — Blender adapter for validator_core's rules.

Born Clean: this file extracts plain data from Blender objects (mesh,
armature, materials) and hands it to validator_core.validate() which
runs the rules. All test-able logic lives in validator_core; this file
is a thin translator.
"""
from __future__ import annotations

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from . import validator_core
from . import rigging


def _active_mesh(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _find_armature_modifier(mesh_obj):
    for m in mesh_obj.modifiers:
        if m.type == 'ARMATURE':
            return m
    return None


def _count_unskinned_verts(mesh_obj, weight_threshold: float = 0.001) -> int:
    """A vert is 'unskinned' if no vertex group sums above the threshold."""
    if not mesh_obj.vertex_groups:
        return len(mesh_obj.data.vertices)
    unskinned = 0
    for v in mesh_obj.data.vertices:
        total = sum(g.weight for g in v.groups)
        if total < weight_threshold:
            unskinned += 1
    return unskinned


def _count_verts_over_weight_limit(mesh_obj, limit: int) -> int:
    over = 0
    for v in mesh_obj.data.vertices:
        non_zero = sum(1 for g in v.groups if g.weight > 0.001)
        if non_zero > limit:
            over += 1
    return over


def _mesh_facing_y(mesh_obj) -> float | None:
    """Heuristic: dot product of forward-facing average normal with +Y.

    For a humanoid character standing upright, normals of front-facing
    triangles average to roughly the facing direction. Negative = faces
    -Y, positive = faces +Y. Returns None for meshes with no polygons.
    """
    if not mesh_obj.data.polygons:
        return None
    # Take only roughly horizontal-normal polys to avoid head-top contamination
    relevant = [p for p in mesh_obj.data.polygons if abs(p.normal.z) < 0.5]
    if not relevant:
        return None
    avg_y = sum(p.normal.y for p in relevant) / len(relevant)
    return avg_y


def _gather_validator_data(mesh_obj) -> dict:
    """Build the data dict validator_core.validate() expects."""
    mesh = mesh_obj.data

    # Triangulate count without modifying the mesh
    tri_count = sum(len(p.vertices) - 2 for p in mesh.polygons)

    arm_mod = _find_armature_modifier(mesh_obj)
    arm_obj = arm_mod.object if arm_mod is not None else None
    armature_bones = [b.name for b in arm_obj.data.bones] if arm_obj is not None else []

    rig_type = mesh_obj.get(rigging.RIG_TYPE_PROP, None)

    return {
        'mesh_scale':              tuple(mesh_obj.scale),
        'mesh_tris':               tri_count,
        'mesh_vert_count':         len(mesh.vertices),
        'mesh_uv_layers':          [layer.name for layer in mesh.uv_layers],
        'unskinned_vert_count':    _count_unskinned_verts(mesh_obj),
        'verts_over_weight_limit': _count_verts_over_weight_limit(mesh_obj, 4),
        'weight_limit':            4,
        'rig_type':                rig_type,
        'has_armature':            arm_obj is not None,
        'armature_bones':          armature_bones,
        'material_count':          sum(1 for s in mesh_obj.material_slots if s.material is not None),
        'mesh_facing_y':           _mesh_facing_y(mesh_obj),
    }


class PIPESCULPT_OT_validate_unity(Operator):
    bl_idname = "pipe_sculpt.validate_unity"
    bl_label = "Validate for Unity"
    bl_description = (
        "Pre-flight check the active mesh + rig against Unity 6 Humanoid "
        "import requirements. Reports every error and warning in one go so "
        "you can fix them all before exporting rather than discovering them "
        "one at a time in Unity"
    )
    bl_options = {'REGISTER'}

    weight_limit: IntProperty(
        name="Max Weights / Vertex",
        description="Unity default = 4. Bump to match your project's QualitySettings",
        default=4,
        min=1,
        max=8,
    )

    @classmethod
    def poll(cls, context):
        return _active_mesh(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        mesh_obj = _active_mesh(context)
        data = _gather_validator_data(mesh_obj)
        data['weight_limit'] = self.weight_limit
        data['verts_over_weight_limit'] = _count_verts_over_weight_limit(
            mesh_obj, self.weight_limit,
        )

        report = validator_core.validate(data)

        # Print full report to system console for diagnostic logging
        print(f"\n=== PipeSculpt Validation: '{mesh_obj.name}' ===")
        for issue in report.issues:
            print(f"  {issue}")
        print(f"=== {len(report.errors)} errors, {len(report.warnings)} warnings ===\n")

        # Surface a brief summary in the status bar + each issue as an
        # operator report. Blender shows ERROR reports prominently.
        for issue in report.issues:
            severity = {'ERROR'} if issue.severity == 'ERROR' else {'WARNING'}
            self.report(severity, f"{issue.rule_id}: {issue.message}")

        if report.is_passing and not report.warnings:
            self.report({'INFO'}, f"'{mesh_obj.name}' passes all Unity checks ✓")
        elif report.is_passing:
            self.report(
                {'INFO'},
                f"'{mesh_obj.name}' passes (0 errors, {len(report.warnings)} warnings). "
                "Check System Console for warnings",
            )
        else:
            self.report(
                {'ERROR'},
                f"'{mesh_obj.name}' has {len(report.errors)} validation error(s). "
                "Fix before exporting — see System Console for the full list",
            )
        return {'FINISHED'}


_classes = (PIPESCULPT_OT_validate_unity,)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
