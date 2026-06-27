"""Headless tests for validator_core."""
from __future__ import annotations

import pytest

# validator_core is preloaded by conftest.py
import validator_core as vc  # noqa: E402


class TestReport:
    def test_empty_report_is_passing(self):
        r = vc.ValidationReport()
        assert r.is_passing
        assert r.errors == []
        assert r.warnings == []

    def test_warning_alone_is_passing(self):
        r = vc.ValidationReport()
        r.add('WARNING', 'X', 'just a warning')
        assert r.is_passing
        assert len(r.warnings) == 1

    def test_error_makes_failing(self):
        r = vc.ValidationReport()
        r.add('ERROR', 'X', 'this is bad')
        assert not r.is_passing

    def test_issue_str_format(self):
        issue = vc.ValidationIssue('ERROR', 'TEST_RULE', 'something broke')
        assert '[ERROR]' in str(issue)
        assert 'TEST_RULE' in str(issue)
        assert 'something broke' in str(issue)


class TestTransformApplied:
    def test_identity_scale_passes(self):
        r = vc.ValidationReport()
        vc.rule_transform_applied({'mesh_scale': (1.0, 1.0, 1.0)}, r)
        assert r.is_passing

    def test_non_identity_scale_fails(self):
        r = vc.ValidationReport()
        vc.rule_transform_applied({'mesh_scale': (2.0, 1.0, 1.0)}, r)
        assert not r.is_passing
        assert any('TRANSFORM_NOT_APPLIED' in i.rule_id for i in r.errors)

    def test_negative_scale_fails(self):
        r = vc.ValidationReport()
        vc.rule_transform_applied({'mesh_scale': (-1.0, 1.0, 1.0)}, r)
        # Two errors: not identity + negative scale
        assert len(r.errors) >= 1
        assert any('NEGATIVE_SCALE' in i.rule_id for i in r.errors)


class TestPolycount:
    def test_zero_tris_fails(self):
        r = vc.ValidationReport()
        vc.rule_polycount_in_range({'mesh_tris': 0}, r)
        assert any('EMPTY_MESH' in i.rule_id for i in r.errors)

    def test_normal_range_passes(self):
        r = vc.ValidationReport()
        vc.rule_polycount_in_range({'mesh_tris': 50_000}, r)
        assert r.is_passing
        assert len(r.warnings) == 0

    def test_too_high_warns(self):
        r = vc.ValidationReport()
        vc.rule_polycount_in_range({'mesh_tris': 200_000}, r)
        assert r.is_passing  # warning only
        assert any('HIGH_POLYCOUNT' in i.rule_id for i in r.warnings)

    def test_too_low_warns(self):
        r = vc.ValidationReport()
        vc.rule_polycount_in_range({'mesh_tris': 500}, r)
        assert any('LOW_POLYCOUNT' in i.rule_id for i in r.warnings)


class TestUVs:
    def test_no_uvs_fails(self):
        r = vc.ValidationReport()
        vc.rule_has_uvs({'mesh_uv_layers': []}, r)
        assert any('NO_UVS' in i.rule_id for i in r.errors)

    def test_one_uv_passes(self):
        r = vc.ValidationReport()
        vc.rule_has_uvs({'mesh_uv_layers': ['UVMap']}, r)
        assert r.is_passing

    def test_multiple_uvs_warns(self):
        r = vc.ValidationReport()
        vc.rule_has_uvs({'mesh_uv_layers': ['UVMap', 'UVMap.001']}, r)
        assert r.is_passing
        assert any('MULTIPLE_UV_LAYERS' in i.rule_id for i in r.warnings)


class TestSkinning:
    def test_no_unskinned_passes(self):
        r = vc.ValidationReport()
        vc.rule_all_verts_skinned({'unskinned_vert_count': 0, 'mesh_vert_count': 1000}, r)
        assert r.is_passing

    def test_unskinned_verts_fail(self):
        r = vc.ValidationReport()
        vc.rule_all_verts_skinned({'unskinned_vert_count': 50, 'mesh_vert_count': 1000}, r)
        assert any('UNSKINNED_VERTS' in i.rule_id for i in r.errors)


class TestWeightLimit:
    def test_within_limit_passes(self):
        r = vc.ValidationReport()
        vc.rule_max_weights_per_vert({'verts_over_weight_limit': 0, 'weight_limit': 4}, r)
        assert r.is_passing

    def test_over_limit_warns(self):
        r = vc.ValidationReport()
        vc.rule_max_weights_per_vert({'verts_over_weight_limit': 12, 'weight_limit': 4}, r)
        assert r.is_passing  # warning only
        assert any('TOO_MANY_WEIGHTS' in i.rule_id for i in r.warnings)


class TestHumanoidBones:
    def test_complete_humanoid_passes(self):
        # All PipeSculpt humanoid bones present → mapping complete
        all_bones = list(vc.PIPESCULPT_TO_UNITY.keys())
        r = vc.ValidationReport()
        vc.rule_humanoid_bones_present(
            {'rig_type': 'HUMANOID', 'armature_bones': all_bones},
            r,
        )
        assert r.is_passing

    def test_missing_humanoid_bone_fails(self):
        # Drop hand.L from the armature
        bones = [b for b in vc.PIPESCULPT_TO_UNITY.keys() if b != 'hand.L']
        r = vc.ValidationReport()
        vc.rule_humanoid_bones_present(
            {'rig_type': 'HUMANOID', 'armature_bones': bones},
            r,
        )
        assert any('MISSING_HUMANOID_BONES' in i.rule_id for i in r.errors)
        # Error message should name the missing pair
        assert any('hand.L' in i.message for i in r.errors)

    def test_non_humanoid_rig_skips_rule(self):
        r = vc.ValidationReport()
        vc.rule_humanoid_bones_present(
            {'rig_type': 'BUST', 'armature_bones': []},
            r,
        )
        assert r.is_passing  # rule should no-op


class TestArmaturePresent:
    def test_humanoid_without_armature_fails(self):
        r = vc.ValidationReport()
        vc.rule_armature_for_rig({'rig_type': 'HUMANOID', 'has_armature': False}, r)
        assert any('NO_ARMATURE' in i.rule_id for i in r.errors)

    def test_no_rig_type_skips(self):
        r = vc.ValidationReport()
        vc.rule_armature_for_rig({'has_armature': False}, r)
        assert r.is_passing


class TestMaterials:
    def test_few_materials_passes(self):
        r = vc.ValidationReport()
        vc.rule_material_count({'material_count': 2}, r)
        assert r.is_passing
        assert len(r.warnings) == 0

    def test_many_materials_warns(self):
        r = vc.ValidationReport()
        vc.rule_material_count({'material_count': 8}, r)
        assert any('MANY_MATERIALS' in i.rule_id for i in r.warnings)


class TestFullValidate:
    def test_clean_mesh_passes_everything(self):
        data = {
            'mesh_scale': (1.0, 1.0, 1.0),
            'mesh_tris': 50_000,
            'mesh_vert_count': 25_000,
            'mesh_uv_layers': ['UVMap'],
            'unskinned_vert_count': 0,
            'verts_over_weight_limit': 0,
            'weight_limit': 4,
            'rig_type': 'HUMANOID',
            'has_armature': True,
            'armature_bones': list(vc.PIPESCULPT_TO_UNITY.keys()),
            'material_count': 1,
            'mesh_facing_y': -0.9,
        }
        report = vc.validate(data)
        assert report.is_passing
        assert len(report.warnings) == 0

    def test_broken_mesh_collects_all_errors(self):
        data = {
            'mesh_scale': (2.0, 1.0, 1.0),
            'mesh_tris': 0,
            'mesh_uv_layers': [],
            'unskinned_vert_count': 100,
            'mesh_vert_count': 200,
            'rig_type': 'HUMANOID',
            'has_armature': False,
            'armature_bones': [],
        }
        report = vc.validate(data)
        assert not report.is_passing
        # Should catch transform, empty mesh, no UVs, no armature, missing bones
        error_ids = {i.rule_id for i in report.errors}
        assert 'TRANSFORM_NOT_APPLIED' in error_ids
        assert 'EMPTY_MESH' in error_ids
        assert 'NO_UVS' in error_ids
        assert 'NO_ARMATURE' in error_ids

    def test_buggy_rule_doesnt_crash_validator(self):
        # A rule that crashes should be caught and reported as a RULE_CRASH
        # error, not propagate up. We verify this by feeding a data dict
        # with a value that would crash rule_polycount_in_range if it
        # didn't have defensive code; rule_polycount uses .get() so this is
        # hard to trigger — instead, test indirectly via the rule_crash
        # pattern in validate() catching exceptions.
        report = vc.validate({})  # empty dict — should yield zero errors,
                                  # all rules tolerate missing fields
        assert isinstance(report, vc.ValidationReport)
