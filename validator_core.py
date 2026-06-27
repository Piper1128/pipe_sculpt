"""Unity Humanoid validator — pure Python rules engine.

Born Clean per IronCore conventions: NO bpy import. Takes plain data
(dicts, lists, floats) describing a mesh+armature and returns a
ValidationReport. The bpy wrapper in validator_ops.py extracts the
data from Blender objects and calls in here.

Tested headlessly via pytest. The rules are documented enough that
adding a new check is a single function + a single test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Unity Humanoid required bone names (case-sensitive in Mecanim).
# Optional bones (fingers, etc.) are not in this list — they get a
# soft warning instead of an error.
UNITY_HUMANOID_REQUIRED = (
    "Hips",         # = pelvis in PipeSculpt
    "Spine",
    "Chest",
    "Neck",
    "Head",
    "LeftShoulder",
    "LeftUpperArm",
    "LeftLowerArm",
    "LeftHand",
    "RightShoulder",
    "RightUpperArm",
    "RightLowerArm",
    "RightHand",
    "LeftUpperLeg",
    "LeftLowerLeg",
    "LeftFoot",
    "RightUpperLeg",
    "RightLowerLeg",
    "RightFoot",
)

# Mapping from PipeSculpt's HUMANOID_BONES names to Unity Humanoid names.
# This is what Unity's Avatar setup will eventually do, but the user
# benefits from knowing if a required mapping is missing BEFORE export.
PIPESCULPT_TO_UNITY = {
    "pelvis":      "Hips",
    "spine":       "Spine",
    "chest":       "Chest",
    "neck":        "Neck",
    "head":        "Head",
    "clavicle.L":  "LeftShoulder",
    "upper_arm.L": "LeftUpperArm",
    "forearm.L":   "LeftLowerArm",
    "hand.L":      "LeftHand",
    "clavicle.R":  "RightShoulder",
    "upper_arm.R": "RightUpperArm",
    "forearm.R":   "RightLowerArm",
    "hand.R":      "RightHand",
    "upper_leg.L": "LeftUpperLeg",
    "lower_leg.L": "LeftLowerLeg",
    "foot.L":      "LeftFoot",
    "upper_leg.R": "RightUpperLeg",
    "lower_leg.R": "RightLowerLeg",
    "foot.R":      "RightFoot",
}


@dataclass
class ValidationIssue:
    severity: str  # 'ERROR' or 'WARNING'
    rule_id: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.rule_id}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == 'ERROR']

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == 'WARNING']

    @property
    def is_passing(self) -> bool:
        return not self.errors

    def add(self, severity: str, rule_id: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, rule_id, message))


# Each rule is `def rule_xxx(data: dict, report: ValidationReport) -> None`.
# data is a plain dict assembled by the bpy adapter; see DATA_SCHEMA at
# the bottom of this module for the expected shape.


def rule_transform_applied(data: dict, report: ValidationReport) -> None:
    """Mesh scale must be (1,1,1), no negative scales, location/rotation applied."""
    scale = data.get('mesh_scale', (1.0, 1.0, 1.0))
    if not all(abs(s - 1.0) < 0.001 for s in scale):
        report.add(
            'ERROR', 'TRANSFORM_NOT_APPLIED',
            f"Mesh scale is {scale} — apply transforms (Ctrl+A → All Transforms)",
        )
    if any(s < 0 for s in scale):
        report.add(
            'ERROR', 'NEGATIVE_SCALE',
            f"Negative scale {scale} — Unity will flip normals. Apply transforms",
        )


def rule_polycount_in_range(data: dict, report: ValidationReport) -> None:
    """Hero characters: 30-80k tris. Warn outside this range."""
    tris = data.get('mesh_tris', 0)
    if tris == 0:
        report.add('ERROR', 'EMPTY_MESH', "Mesh has zero triangles")
        return
    if tris > 100_000:
        report.add(
            'WARNING', 'HIGH_POLYCOUNT',
            f"Mesh has {tris:,} triangles — Unity hero characters target 30-80k. "
            "Run Retopo if this is a high-poly sculpt",
        )
    elif tris < 1000:
        report.add(
            'WARNING', 'LOW_POLYCOUNT',
            f"Mesh has only {tris:,} triangles — may look blocky in Unity",
        )


def rule_has_uvs(data: dict, report: ValidationReport) -> None:
    if not data.get('mesh_uv_layers'):
        report.add(
            'ERROR', 'NO_UVS',
            "Mesh has no UV layer — bake maps and textures won't appear correctly. "
            "Run UV → Smart Unwrap first",
        )
        return
    if len(data['mesh_uv_layers']) > 1:
        report.add(
            'WARNING', 'MULTIPLE_UV_LAYERS',
            f"Mesh has {len(data['mesh_uv_layers'])} UV layers — Unity will import the "
            "active one. Make sure the active layer is the one you painted on",
        )


def rule_all_verts_skinned(data: dict, report: ValidationReport) -> None:
    """Every vertex must have at least one bone weight ≥ 0.001."""
    unskinned = data.get('unskinned_vert_count', 0)
    total = data.get('mesh_vert_count', 1)
    if unskinned == 0:
        return
    pct = (unskinned / total) * 100.0
    report.add(
        'ERROR', 'UNSKINNED_VERTS',
        f"{unskinned:,} of {total:,} vertices ({pct:.1f}%) have no bone weights — "
        "they'll stick to the mesh origin in Unity. Run Generate Rig or paint weights",
    )


def rule_max_weights_per_vert(data: dict, report: ValidationReport) -> None:
    """Unity caps influences per vertex (default 4). Warn if exceeded."""
    over_limit = data.get('verts_over_weight_limit', 0)
    limit = data.get('weight_limit', 4)
    if over_limit > 0:
        report.add(
            'WARNING', 'TOO_MANY_WEIGHTS',
            f"{over_limit:,} verts have >{limit} bone weights — Unity will drop the "
            f"weakest. Use Object → Modifier → Vertex Weight → Limit Total = {limit}",
        )


def rule_humanoid_bones_present(data: dict, report: ValidationReport) -> None:
    """For HUMANOID rig: every required Unity bone must have a source counterpart."""
    rig_type = data.get('rig_type')
    if rig_type != 'HUMANOID':
        return  # Other rig types use Generic, not Humanoid
    armature_bones = set(data.get('armature_bones', []))
    missing = []
    for pipe_name, unity_name in PIPESCULPT_TO_UNITY.items():
        if pipe_name not in armature_bones:
            missing.append(f"{pipe_name} → {unity_name}")
    if missing:
        report.add(
            'ERROR', 'MISSING_HUMANOID_BONES',
            f"Required Humanoid bones missing on armature: {', '.join(missing)}",
        )


def rule_armature_for_rig(data: dict, report: ValidationReport) -> None:
    """If the rig type expects an armature, one must be present and parented."""
    rig_type = data.get('rig_type')
    if rig_type not in ('HUMANOID', 'BUST', 'HEAD', 'QUADRUPED', 'BIRD', 'MECH'):
        return
    if not data.get('has_armature'):
        report.add(
            'ERROR', 'NO_ARMATURE',
            f"Rig type is '{rig_type}' but no armature is parented to the mesh. "
            "Run Generate Rig",
        )


def rule_material_count(data: dict, report: ValidationReport) -> None:
    """Unity supports multiple materials but each becomes a draw call. Warn at >2."""
    mat_count = data.get('material_count', 0)
    if mat_count > 2:
        report.add(
            'WARNING', 'MANY_MATERIALS',
            f"Mesh has {mat_count} materials — each is a separate Unity draw call. "
            "Consider consolidating to 1-2 if performance matters",
        )


def rule_facing_axis(data: dict, report: ValidationReport) -> None:
    """Unity Humanoid expects character to face +Z (Blender -Y after axis conversion)."""
    rig_type = data.get('rig_type')
    if rig_type != 'HUMANOID':
        return
    facing = data.get('mesh_facing_y', None)
    if facing is None:
        return
    # Mesh should face -Y in Blender (becomes +Z in Unity after BAKED axis conversion)
    if facing > 0.5:
        report.add(
            'WARNING', 'CHARACTER_FACING_WRONG_WAY',
            "Character appears to be facing +Y in Blender — Unity Humanoid expects "
            "characters facing -Y (camera-toward). Rotate 180° around Z before export",
        )


_ALL_RULES = (
    rule_transform_applied,
    rule_polycount_in_range,
    rule_has_uvs,
    rule_all_verts_skinned,
    rule_max_weights_per_vert,
    rule_armature_for_rig,
    rule_humanoid_bones_present,
    rule_material_count,
    rule_facing_axis,
)


def validate(data: dict) -> ValidationReport:
    """Run every rule against the supplied data dict, return the report."""
    report = ValidationReport()
    for rule in _ALL_RULES:
        try:
            rule(data, report)
        except Exception as e:
            # A buggy rule shouldn't crash the entire validator
            report.add('ERROR', 'RULE_CRASH', f"{rule.__name__}: {e}")
    return report


# Expected `data` dict schema for the bpy adapter. Keys are optional —
# rules tolerate missing fields and just skip themselves.
DATA_SCHEMA = """
{
    'mesh_scale': (sx, sy, sz),
    'mesh_tris': int,
    'mesh_vert_count': int,
    'mesh_uv_layers': [str, ...],
    'unskinned_vert_count': int,
    'verts_over_weight_limit': int,
    'weight_limit': int,                       # default 4
    'rig_type': str,                            # 'HUMANOID', 'BUST', ...
    'has_armature': bool,
    'armature_bones': [str, ...],
    'material_count': int,
    'mesh_facing_y': float,                     # +1 = faces +Y, -1 = faces -Y
}
"""
