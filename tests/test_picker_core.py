"""Headless tests for picker_core — bone-picker layout classification."""
from __future__ import annotations

import picker_core as pc  # noqa: E402 (preloaded by conftest.py)


class TestColumn:
    def test_left(self):
        assert pc.classify_bone("upper_arm.L").column == 'L'

    def test_right(self):
        assert pc.classify_bone("upper_arm.R").column == 'R'

    def test_center(self):
        assert pc.classify_bone("spine").column == 'C'
        assert pc.classify_bone("head").column == 'C'

    def test_underscore_side(self):
        assert pc.classify_bone("Hand_L").column == 'L'
        assert pc.classify_bone("Hand_R").column == 'R'


class TestGroup:
    def test_head_group(self):
        for n in ("head", "neck", "jaw", "ear.L", "beak"):
            assert pc.classify_bone(n).group == 'head', n

    def test_torso_group(self):
        for n in ("pelvis", "spine", "chest", "tail"):
            assert pc.classify_bone(n).group == 'torso', n

    def test_arm_group(self):
        for n in ("clavicle.L", "upper_arm.R", "forearm.L"):
            assert pc.classify_bone(n).group == 'arm', n

    def test_hand_group(self):
        assert pc.classify_bone("hand.L").group == 'hand'

    def test_fingers_group(self):
        for n in ("thumb_01.L", "index_02.R", "pinky_03.L"):
            assert pc.classify_bone(n).group == 'fingers', n

    def test_leg_group(self):
        for n in ("upper_leg.L", "lower_leg.R", "foot.L", "toes.R"):
            assert pc.classify_bone(n).group == 'leg', n

    def test_control_group(self):
        for n in ("root", "hand_ik.L", "foot_ik.R", "elbow_pole.L", "knee_pole.R"):
            assert pc.classify_bone(n).group == 'control', n

    def test_hand_ik_not_confused_with_hand(self):
        # 'hand_ik' must classify as control, not hand
        assert pc.classify_bone("hand_ik.L").group == 'control'
        assert pc.classify_bone("hand.L").group == 'hand'

    def test_unknown_is_other(self):
        assert pc.classify_bone("mystery_bone").group == 'other'


class TestRowOrdering:
    def test_head_above_feet(self):
        head = pc.classify_bone("head").row
        foot = pc.classify_bone("foot.L").row
        assert head < foot

    def test_chest_above_pelvis(self):
        assert pc.classify_bone("chest").row < pc.classify_bone("pelvis").row

    def test_upper_arm_above_forearm(self):
        assert pc.classify_bone("upper_arm.L").row < pc.classify_bone("forearm.L").row


class TestLabels:
    def test_suffix_stripped(self):
        assert ".L" not in pc.classify_bone("upper_arm.L").label
        assert ".R" not in pc.classify_bone("forearm.R").label

    def test_abbreviations(self):
        assert pc.classify_bone("upper_arm.L").label == "U.Arm"
        assert pc.classify_bone("clavicle.R").label == "Clav"

    def test_simple_titlecase(self):
        assert pc.classify_bone("spine").label == "Spine"
        assert pc.classify_bone("head").label == "Head"


class TestBuildLayout:
    def test_count_matches(self):
        names = ["head", "spine", "upper_arm.L", "upper_arm.R", "hand.L"]
        assert len(pc.build_picker_layout(names)) == len(names)


class TestBodyColumns:
    def test_buckets_by_column(self):
        names = ["head", "upper_arm.L", "upper_arm.R", "spine"]
        cols = pc.body_columns(pc.build_picker_layout(names))
        assert [s.bone for s in cols['C']] == ["head", "spine"] or \
               [s.bone for s in cols['C']] == ["spine", "head"]  # both center
        assert cols['L'][0].bone == "upper_arm.L"
        assert cols['R'][0].bone == "upper_arm.R"

    def test_column_sorted_by_row(self):
        names = ["foot.L", "upper_leg.L", "lower_leg.L"]
        cols = pc.body_columns(pc.build_picker_layout(names))
        rows = [s.row for s in cols['L']]
        assert rows == sorted(rows)

    def test_fingers_excluded_from_body(self):
        names = ["hand.L", "thumb_01.L", "index_02.L"]
        cols = pc.body_columns(pc.build_picker_layout(names))
        body_bones = [s.bone for col in cols.values() for s in col]
        assert "hand.L" in body_bones
        assert "thumb_01.L" not in body_bones  # fingers go in their own grid

    def test_controls_excluded_from_body(self):
        names = ["hand.L", "hand_ik.L", "root"]
        cols = pc.body_columns(pc.build_picker_layout(names))
        body_bones = [s.bone for col in cols.values() for s in col]
        assert "hand.L" in body_bones
        assert "hand_ik.L" not in body_bones
        assert "root" not in body_bones


class TestFingerSlots:
    def test_only_fingers(self):
        names = ["hand.L", "thumb_01.L", "index_02.R", "spine"]
        fingers = pc.finger_slots(pc.build_picker_layout(names))
        assert {s.bone for s in fingers} == {"thumb_01.L", "index_02.R"}

    def test_sorted_by_side(self):
        names = ["index_01.R", "thumb_01.L"]
        fingers = pc.finger_slots(pc.build_picker_layout(names))
        # L sorts before R
        assert fingers[0].column == 'L'


class TestControlSlots:
    def test_only_controls(self):
        names = ["hand_ik.L", "foot_ik.R", "spine", "hand.L"]
        ctrls = pc.control_slots(pc.build_picker_layout(names))
        assert {s.bone for s in ctrls} == {"hand_ik.L", "foot_ik.R"}
