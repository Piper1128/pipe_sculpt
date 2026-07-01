"""Headless unit tests for pose_library_core (pure, no bpy)."""
from __future__ import annotations

import math

import pytest

import pose_library_core as plc  # preloaded by conftest via importlib


IDENT = (1.0, 0.0, 0.0, 0.0)


class TestCatalog:
    def test_t_pose_exists_and_empty(self):
        t = plc.get_pose("T_POSE")
        assert t.category == "Stance"
        assert t.channels == {}

    def test_unknown_pose_raises(self):
        with pytest.raises(KeyError):
            plc.get_pose("NOT_A_POSE")

    def test_pose_names_contains_t_pose(self):
        assert "T_POSE" in plc.pose_names()

    def test_names_are_unique(self):
        names = plc.pose_names()
        assert len(names) == len(set(names))

    def test_categories_bucket(self):
        cats = plc.poses_by_category()
        assert "T_POSE" in [p.name for p in cats["Stance"]]

    def test_every_catalog_pose_is_valid(self):
        # Whatever ends up in the shipped catalog must pass validation.
        for p in plc.POSE_LIBRARY:
            assert plc.validate_pose(p) == [], f"{p.name} invalid"

    def test_no_catalog_pose_stores_ik_solved_bone(self):
        for p in plc.POSE_LIBRARY:
            assert not (set(p.channels) & plc.IK_SOLVED_BONES), p.name


class TestIKSolvedSet:
    def test_eight_ik_solved_bones(self):
        assert plc.IK_SOLVED_BONES == frozenset({
            "upper_arm.L", "upper_arm.R", "forearm.L", "forearm.R",
            "upper_leg.L", "upper_leg.R", "lower_leg.L", "lower_leg.R",
        })


class TestMirror:
    def test_mirror_transform_negates_x_and_yz(self):
        loc, quat = plc.mirror_transform((0.5, 0.2, 0.3), (0.9, 0.1, 0.2, 0.3))
        assert loc == pytest.approx((-0.5, 0.2, 0.3))
        assert quat == pytest.approx((0.9, 0.1, -0.2, -0.3))

    def test_mirror_channels_swaps_side(self):
        ch = {"hand_ik.L": ((0.1, 0.0, 0.5), IDENT)}
        m = plc.mirror_channels(ch)
        assert "hand_ik.R" in m and "hand_ik.L" not in m
        assert m["hand_ik.R"][0] == pytest.approx((-0.1, 0.0, 0.5))

    def test_mirror_channels_centre_stays_named(self):
        ch = {"chest": ((0.0, 0.0, 0.0), (0.99, 0.0, 0.0, 0.14))}
        m = plc.mirror_channels(ch)
        assert "chest" in m
        # centre bone mirrored in place: quat Y,Z negated
        assert m["chest"][1] == pytest.approx((0.99, 0.0, 0.0, -0.14))

    def test_mirror_is_involution(self):
        ch = {"hand_ik.L": ((0.3, -0.1, 0.4), (0.8, 0.1, -0.2, 0.55))}
        back = plc.mirror_channels(plc.mirror_channels(ch))
        assert "hand_ik.L" in back
        assert back["hand_ik.L"][0] == pytest.approx(ch["hand_ik.L"][0])
        assert back["hand_ik.L"][1] == pytest.approx(ch["hand_ik.L"][1])


class TestExpandSymmetric:
    def test_expands_left_to_right(self):
        ch = {"hand_ik.L": ((0.2, 0.0, 0.3), IDENT), "chest": ((0, 0, 0), IDENT)}
        full = plc.expand_symmetric(ch)
        assert "hand_ik.R" in full
        assert full["hand_ik.R"][0] == pytest.approx((-0.2, 0.0, 0.3))
        # centre untouched (no twin)
        assert full["chest"] == ch["chest"]

    def test_does_not_clobber_existing_right(self):
        ch = {"hand_ik.L": ((0.2, 0, 0.3), IDENT),
              "hand_ik.R": ((-0.9, 0, 0.1), IDENT)}
        full = plc.expand_symmetric(ch)
        assert full["hand_ik.R"][0] == pytest.approx((-0.9, 0, 0.1))


class TestBlend:
    def test_blend_zero_is_rest(self):
        loc, quat = plc.blend_from_rest((1.0, 2.0, 3.0), (0.7071, 0.7071, 0, 0), 0.0)
        assert loc == pytest.approx((0, 0, 0))
        assert quat == pytest.approx(IDENT)

    def test_blend_one_is_pose(self):
        target_q = (0.7071, 0.7071, 0.0, 0.0)
        loc, quat = plc.blend_from_rest((1.0, 2.0, 3.0), target_q, 1.0)
        assert loc == pytest.approx((1.0, 2.0, 3.0))
        assert quat == pytest.approx(target_q, abs=1e-4)

    def test_blend_half_location(self):
        loc, _ = plc.blend_from_rest((1.0, 0.0, 0.0), IDENT, 0.5)
        assert loc == pytest.approx((0.5, 0.0, 0.0))

    def test_blend_channels_full_returns_copy(self):
        ch = {"chest": ((0, 0, 0), (0.9, 0.1, 0.2, 0.3))}
        out = plc.blend_channels(ch, 1.0)
        assert out == ch and out is not ch

    def test_blend_channels_half(self):
        ch = {"hand_ik.L": ((1.0, 0.0, 0.0), IDENT)}
        out = plc.blend_channels(ch, 0.5)
        assert out["hand_ik.L"][0] == pytest.approx((0.5, 0.0, 0.0))


class TestValidate:
    def test_catches_ik_solved_bone(self):
        bad = plc.PoseSpec("X", "X", "Stance", "d",
                           channels={"forearm.L": ((0, 0, 0), IDENT)})
        issues = plc.validate_pose(bad)
        assert any("IK-solved" in i for i in issues)

    def test_catches_unnormalised_quat(self):
        bad = plc.PoseSpec("X", "X", "Stance", "d",
                           channels={"chest": ((0, 0, 0), (2.0, 0.0, 0.0, 0.0))})
        issues = plc.validate_pose(bad)
        assert any("normalised" in i for i in issues)

    def test_catches_unknown_bone_when_known_given(self):
        bad = plc.PoseSpec("X", "X", "Stance", "d",
                           channels={"nose.L": ((0, 0, 0), IDENT)})
        issues = plc.validate_pose(bad, known_bones={"chest", "head"})
        assert any("not on the rig" in i for i in issues)

    def test_valid_pose_no_issues(self):
        good = plc.PoseSpec("X", "X", "Stance", "d",
                            channels={"chest": ((0, 0, 0), IDENT)})
        assert plc.validate_pose(good, known_bones={"chest"}) == []
