"""Headless tests for setup_core — rig-styling classification."""
from __future__ import annotations

import setup_core as sc  # noqa: E402 (preloaded by conftest.py)


class TestWidgetForControl:
    def test_hand_ik(self):
        assert sc.widget_for_control("hand_ik.L") == ('CUBE', 0.12)

    def test_foot_ik(self):
        assert sc.widget_for_control("foot_ik.R") == ('CUBE', 0.12)

    def test_pole(self):
        assert sc.widget_for_control("elbow_pole.L")[0] == 'DIAMOND'
        assert sc.widget_for_control("knee_pole.R")[0] == 'DIAMOND'

    def test_root(self):
        assert sc.widget_for_control("root")[0] == 'RING'

    def test_deform_none(self):
        assert sc.widget_for_control("upper_arm.L") is None
        assert sc.widget_for_control("spine") is None


class TestIsControl:
    def test_controls(self):
        for n in ("hand_ik.L", "foot_ik.R", "elbow_pole.L", "knee_pole.R", "root"):
            assert sc.is_control(n), n

    def test_non_controls(self):
        for n in ("upper_arm.L", "spine", "hand.L", "thumb_01.L"):
            assert not sc.is_control(n), n


class TestIsFinger:
    def test_fingers(self):
        for n in ("thumb_01.L", "index_02.R", "pinky_03.L"):
            assert sc.is_finger(n), n

    def test_non_fingers(self):
        assert not sc.is_finger("hand.L")
        assert not sc.is_finger("spine")


class TestThemeForBone:
    def test_left_control_blue(self):
        assert sc.theme_for_bone("hand_ik.L") == 'THEME04'

    def test_right_control_red(self):
        assert sc.theme_for_bone("hand_ik.R") == 'THEME01'

    def test_center_control_yellow(self):
        assert sc.theme_for_bone("root") == 'THEME09'

    def test_deform_default(self):
        assert sc.theme_for_bone("upper_arm.L") == 'DEFAULT'
        assert sc.theme_for_bone("spine") == 'DEFAULT'


class TestCollectionForBone:
    def test_control(self):
        assert sc.collection_for_bone("hand_ik.L") == 'Controls'

    def test_finger(self):
        assert sc.collection_for_bone("thumb_01.L") == 'Fingers'

    def test_deform(self):
        assert sc.collection_for_bone("upper_arm.L") == 'Deform'
        assert sc.collection_for_bone("spine") == 'Deform'


class TestWidgetScale:
    def test_control_scale(self):
        assert sc.widget_scale("hand_ik.L") == 0.12

    def test_multiplier(self):
        assert sc.widget_scale("hand_ik.L", 2.0) == 0.24

    def test_deform_none(self):
        assert sc.widget_scale("spine") is None

    def test_multiplier_floor(self):
        # A zero/negative multiplier is clamped so widgets never vanish
        assert sc.widget_scale("hand_ik.L", 0.0) > 0
