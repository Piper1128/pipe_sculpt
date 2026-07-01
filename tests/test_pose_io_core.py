"""Headless unit tests for pose_io_core (pure, no bpy)."""
from __future__ import annotations

import pytest

import pose_io_core as io
import pose_library_core as plc


IDENT = (1.0, 0.0, 0.0, 0.0)


def _spec():
    return plc.PoseSpec(
        name="MY_POSE", label="My Pose", category="User", description="hi",
        channels={"hand_ik.L": ((0.1, 0.2, 0.3), (0.99, 0.0, 0.14, 0.0))},
    )


class TestSlug:
    def test_basic(self):
        assert io.slugify("My Cool Pose!") == "my_cool_pose"

    def test_empty_falls_back(self):
        assert io.slugify("  ***  ") == "pose"

    def test_pose_id_upper(self):
        assert io.normalise_pose_id("my cool pose") == "MY_COOL_POSE"


class TestRoundTrip:
    def test_to_dict_shape(self):
        d = io.pose_to_dict(_spec())
        assert d["format"] == io.FORMAT
        assert d["name"] == "MY_POSE"
        assert d["channels"]["hand_ik.L"] == [[0.1, 0.2, 0.3], [0.99, 0.0, 0.14, 0.0]]

    def test_round_trip_preserves_channels(self):
        back = io.pose_from_dict(io.pose_to_dict(_spec()))
        assert back.name == "MY_POSE"
        loc, quat = back.channels["hand_ik.L"]
        assert loc == pytest.approx((0.1, 0.2, 0.3))
        assert quat == pytest.approx((0.99, 0.0, 0.14, 0.0))
        assert isinstance(loc, tuple) and isinstance(quat, tuple)

    def test_from_dict_drops_ik_solved(self):
        d = io.pose_to_dict(_spec())
        d["channels"]["forearm.L"] = [[0, 0, 0], list(IDENT)]  # sneaky bad bone
        back = io.pose_from_dict(d)
        assert "forearm.L" not in back.channels
        assert "hand_ik.L" in back.channels


class TestValidate:
    def test_good_dict(self):
        assert io.validate_dict(io.pose_to_dict(_spec())) == []

    def test_wrong_format(self):
        assert any("format" in i for i in io.validate_dict({"name": "x", "channels": {}}))

    def test_missing_name(self):
        d = io.pose_to_dict(_spec()); d["name"] = ""
        assert any("name" in i for i in io.validate_dict(d))

    def test_malformed_channel(self):
        d = io.pose_to_dict(_spec())
        d["channels"]["hand_ik.L"] = [[0, 0], [1, 0, 0, 0]]  # loc too short
        assert any("malformed" in i for i in io.validate_dict(d))

    def test_from_dict_raises_on_invalid(self):
        with pytest.raises(ValueError):
            io.pose_from_dict({"format": "nope", "name": "x", "channels": {}})
