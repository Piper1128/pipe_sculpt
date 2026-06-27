"""Headless tests for anim_core — Phase 1 animation logic."""
from __future__ import annotations

import math

import pytest

import anim_core as ac  # noqa: E402  (preloaded by conftest.py)


# Identity quaternion for convenience
Q_ID = (1.0, 0.0, 0.0, 0.0)


class TestMirrorBoneName:
    def test_dot_L_to_R(self):
        assert ac.mirror_bone_name("upper_arm.L") == "upper_arm.R"

    def test_dot_R_to_L(self):
        assert ac.mirror_bone_name("index_02.R") == "index_02.L"

    def test_underscore_convention(self):
        assert ac.mirror_bone_name("Hand_L") == "Hand_R"
        assert ac.mirror_bone_name("Hand_R") == "Hand_L"

    def test_lowercase_dot(self):
        assert ac.mirror_bone_name("foot.l") == "foot.r"

    def test_centerline_returns_none(self):
        for name in ("pelvis", "spine", "chest", "neck", "head", "root", "jaw"):
            assert ac.mirror_bone_name(name) is None

    def test_empty_string(self):
        assert ac.mirror_bone_name("") is None

    def test_roundtrip(self):
        # Mirroring twice returns the original
        for name in ("clavicle.L", "thumb_03.R", "knee_pole.L"):
            mirrored = ac.mirror_bone_name(name)
            assert ac.mirror_bone_name(mirrored) == name

    def test_finger_bones(self):
        assert ac.mirror_bone_name("thumb_01.L") == "thumb_01.R"
        assert ac.mirror_bone_name("pinky_03.R") == "pinky_03.L"


class TestIsCenterline:
    def test_centerline_true(self):
        assert ac.is_centerline("spine")
        assert ac.is_centerline("chest")

    def test_sided_false(self):
        assert not ac.is_centerline("upper_arm.L")
        assert not ac.is_centerline("foot.R")

    def test_centerline_set_all_centerline(self):
        # Every name in the documented centerline set must report centerline
        for name in ac.CENTERLINE_BONES:
            assert ac.is_centerline(name), f"{name} should be centerline"


class TestLerp:
    def test_endpoints(self):
        assert ac.lerp(0.0, 10.0, 0.0) == 0.0
        assert ac.lerp(0.0, 10.0, 1.0) == 10.0

    def test_midpoint(self):
        assert ac.lerp(0.0, 10.0, 0.5) == 5.0

    def test_overshoot_allowed(self):
        # Breakdown sliders can push past the endpoints
        assert ac.lerp(0.0, 10.0, 1.5) == 15.0
        assert ac.lerp(0.0, 10.0, -0.5) == -5.0


class TestBreakdownVec:
    def test_midpoint(self):
        a = (0.0, 0.0, 0.0)
        b = (2.0, 4.0, 6.0)
        assert ac.breakdown_vec(a, b, 0.5) == (1.0, 2.0, 3.0)

    def test_endpoints(self):
        a = (1.0, 2.0, 3.0)
        b = (4.0, 5.0, 6.0)
        assert ac.breakdown_vec(a, b, 0.0) == a
        assert ac.breakdown_vec(a, b, 1.0) == b


class TestBreakdownQuat:
    def test_identical_quats(self):
        result = ac.breakdown_quat(Q_ID, Q_ID, 0.5)
        assert result == pytest.approx(Q_ID)

    def test_result_normalised(self):
        a = (1.0, 0.0, 0.0, 0.0)
        b = (0.0, 1.0, 0.0, 0.0)  # 180° about X
        result = ac.breakdown_quat(a, b, 0.5)
        norm = math.sqrt(sum(c * c for c in result))
        assert norm == pytest.approx(1.0)

    def test_shortest_arc_flip(self):
        # b negated represents the same rotation; nlerp should take short arc
        a = (1.0, 0.0, 0.0, 0.0)
        b = (-0.9999, 0.0, 0.0, 0.01)  # nearly -identity
        result = ac.breakdown_quat(a, b, 0.5)
        # Should stay near identity (w positive), not flip to ~ -1
        assert result[0] > 0


class TestTransformsDiffer:
    def test_identical(self):
        t = ((0, 0, 0), Q_ID, (1, 1, 1))
        assert not ac.transforms_differ(t, t)

    def test_location_differs(self):
        a = ((0, 0, 0), Q_ID, (1, 1, 1))
        b = ((1, 0, 0), Q_ID, (1, 1, 1))
        assert ac.transforms_differ(a, b)

    def test_within_tolerance(self):
        a = ((0, 0, 0), Q_ID, (1, 1, 1))
        b = ((1e-6, 0, 0), Q_ID, (1, 1, 1))
        assert not ac.transforms_differ(a, b)

    def test_rotation_differs(self):
        a = ((0, 0, 0), (1.0, 0.0, 0.0, 0.0), (1, 1, 1))
        b = ((0, 0, 0), (0.7071, 0.7071, 0.0, 0.0), (1, 1, 1))  # 90° about X
        assert ac.transforms_differ(a, b)

    def test_scale_differs(self):
        a = ((0, 0, 0), Q_ID, (1, 1, 1))
        b = ((0, 0, 0), Q_ID, (1.5, 1, 1))
        assert ac.transforms_differ(a, b)


class TestDiffPose:
    def test_matching_poses_empty(self):
        pose = {
            "spine": ((0, 0, 0), Q_ID, (1, 1, 1)),
            "head": ((0, 0, 1), Q_ID, (1, 1, 1)),
        }
        assert ac.diff_pose(pose, pose) == []

    def test_popping_bone_detected(self):
        a = {"hand.L": ((0, 0, 0), Q_ID, (1, 1, 1))}
        b = {"hand.L": ((0.5, 0, 0), Q_ID, (1, 1, 1))}
        diffs = ac.diff_pose(a, b)
        assert len(diffs) == 1
        assert diffs[0].bone == "hand.L"
        assert diffs[0].loc_delta == pytest.approx(0.5)

    def test_sorted_worst_first(self):
        a = {
            "a": ((0, 0, 0), Q_ID, (1, 1, 1)),
            "b": ((0, 0, 0), Q_ID, (1, 1, 1)),
        }
        b = {
            "a": ((0.1, 0, 0), Q_ID, (1, 1, 1)),
            "b": ((0.9, 0, 0), Q_ID, (1, 1, 1)),
        }
        diffs = ac.diff_pose(a, b)
        assert diffs[0].bone == "b"  # bigger delta first
        assert diffs[1].bone == "a"

    def test_missing_bone_skipped(self):
        a = {"spine": ((0, 0, 0), Q_ID, (1, 1, 1)), "extra": ((9, 9, 9), Q_ID, (1, 1, 1))}
        b = {"spine": ((0, 0, 0), Q_ID, (1, 1, 1))}
        # 'extra' isn't in b → skipped, not crashed
        assert ac.diff_pose(a, b) == []


class TestStripRootTranslation:
    def test_zeroes_xy_keeps_z(self):
        keys = [(1, 1.0, 2.0, 0.5), (10, 3.0, 4.0, 0.8)]
        out = ac.strip_root_translation(keys, keep_z=True)
        assert out == [(1, 0.0, 0.0, 0.5), (10, 0.0, 0.0, 0.8)]

    def test_zeroes_all_when_keep_z_false(self):
        keys = [(1, 1.0, 2.0, 0.5)]
        out = ac.strip_root_translation(keys, keep_z=False)
        assert out == [(1, 0.0, 0.0, 0.0)]

    def test_empty(self):
        assert ac.strip_root_translation([]) == []


class TestRootMotionDelta:
    def test_forward_travel(self):
        keys = [(1, 0.0, 0.0, 0.0), (30, 0.0, 1.4, 0.0)]
        dx, dy = ac.root_motion_delta(keys)
        assert dx == pytest.approx(0.0)
        assert dy == pytest.approx(1.4)

    def test_single_key_no_delta(self):
        assert ac.root_motion_delta([(1, 5.0, 5.0, 0.0)]) == (0.0, 0.0)

    def test_empty_no_delta(self):
        assert ac.root_motion_delta([]) == (0.0, 0.0)


class TestFitPreviewRange:
    def test_normal_order(self):
        assert ac.fit_preview_range(1, 30) == (1, 30)

    def test_reversed_swapped(self):
        assert ac.fit_preview_range(30, 1) == (1, 30)

    def test_floats_rounded(self):
        assert ac.fit_preview_range(1.4, 29.6) == (1, 30)
