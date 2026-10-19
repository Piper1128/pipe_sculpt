"""Headless tests for marv_import_core (Marv OBJ + joints.json -> GTR data)."""
from __future__ import annotations

import copy
import os
import sys

import pytest

import marv_import_core as mic  # noqa: E402  (preloaded by conftest.py)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marv_fixture as fx  # noqa: E402

# Stand-in for rigging.BONE_NAME_TO_INDEX (rigging imports bpy). The real
# table is exercised by tools/marv_to_unity.py inside Blender.
INDEX = {b: i for i, b in enumerate(sorted(mic.UNITY_TO_PIPESCULPT.values()))}


def _body(doc=None, obj=None):
    return mic.build_body(doc or fx.joints_doc(), obj or fx.obj_text(), INDEX)


class TestAxes:
    def test_identity_for_blender_frame(self):
        assert mic.axis_matrix("+Z", "-Y") == ((1, 0, 0), (0, 1, 0), (0, 0, 1))

    def test_y_up_frame(self):
        # Y-up, facing +Z (Unity/glTF style): up must land on +Z, forward on -Y.
        m = mic.axis_matrix("+Y", "+Z")
        apply = lambda p: tuple(sum(m[i][j] * p[j] for j in range(3)) for i in range(3))
        assert apply((0, 1, 0)) == (0, 0, 1)
        assert apply((0, 0, 1)) == (0, -1, 0)

    def test_rotation_not_reflection(self):
        m = mic.axis_matrix("+Y", "+Z")
        det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
               - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
               + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
        assert det == 1

    @pytest.mark.parametrize("up,fwd", [("+Z", "-Z"), ("Z", "-Y"), ("+W", "-Y")])
    def test_bad_axes(self, up, fwd):
        with pytest.raises(mic.MarvImportError):
            mic.axis_matrix(up, fwd)


class TestJoints:
    def test_fixture_parses(self):
        p = mic.parse_joints(fx.joints_doc())
        assert len(p["joints"]) == 21
        # single child -> tail is the child's centre
        assert p["joints"]["LeftUpperArm"]["tail"] == (190.0, 0.0, 1130.0)

    def test_bones_in_metres_with_root(self):
        bones, prov = mic.bones_from_joints(mic.parse_joints(fx.joints_doc()))
        by = {b["id"]: b for b in bones}
        assert by["root"]["kind"] == 'C' and by["root"]["parent"] is None
        assert by["pelvis"]["parent"] == "root"
        assert by["upper_arm.L"]["head"] == pytest.approx([0.18, 0.0, 1.43])
        assert by["upper_arm.L"]["parent"] == "clavicle.L"
        assert by["root"]["head"][2] == pytest.approx(0.02)  # lowest point = toes
        assert prov["hand.L"]["kind"] == "Assumed"

    def test_spine_and_chest_both_kept(self):
        bones, _ = mic.bones_from_joints(mic.parse_joints(fx.joints_doc()))
        by = {b["id"]: b for b in bones}
        assert by["chest"]["parent"] == "spine" and by["neck"]["parent"] == "chest"

    def test_multi_child_without_tail_is_rejected(self):
        doc = fx.joints_doc()
        next(j for j in doc["joints"] if j["name"] == "Chest").pop("tail")
        with pytest.raises(mic.MarvImportError, match="Chest.*3 children"):
            mic.parse_joints(doc)

    def test_leaf_without_tail_is_rejected(self):
        doc = fx.joints_doc()
        next(j for j in doc["joints"] if j["name"] == "Head").pop("tail")
        with pytest.raises(mic.MarvImportError, match="Head.*0 children"):
            mic.parse_joints(doc)

    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(schema="marv.joints/2"), "schema"),
        (lambda d: d.update(unit="cm"), "unit"),
        (lambda d: d["joints"].append(copy.deepcopy(d["joints"][1])), "twice"),
        (lambda d: d["joints"][1].update(name="Spine1"), "not a supported"),
        (lambda d: d["joints"][1].update(parent="Nope"), "unknown parent"),
        (lambda d: d["joints"][0].update(parent="Spine"), "root"),
        (lambda d: d["joints"][1].update(center=[0, 0]), "center"),
        (lambda d: d["joints"][4].update(tail=d["joints"][4]["center"]), "zero length"),
    ])
    def test_rejects(self, mutate, match):
        doc = fx.joints_doc()
        mutate(doc)
        with pytest.raises(mic.MarvImportError, match=match):
            mic.parse_joints(doc)

    def test_cycle_is_rejected(self):
        doc = fx.joints_doc()
        by = {j["name"]: j for j in doc["joints"]}
        by["Spine"]["parent"] = "Neck"   # Spine -> Neck -> Chest -> Spine
        with pytest.raises(mic.MarvImportError, match="cycle"):
            mic.parse_joints(doc)


class TestObj:
    def test_parse_counts(self):
        m = mic.parse_obj(fx.obj_text())
        assert len(m.vertices) == 21 * 8 and len(m.faces) == 21 * 6
        assert m.groups[0] == "Hips"

    def test_face_index_forms(self):
        text = "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\ng A\nf 1/1 2//3 3/4/5\nf -1 -2 -3\n"
        m = mic.parse_obj(text)
        assert m.faces == [(0, 1, 2), (3, 2, 1)]

    def test_majority_vote_and_tie(self):
        # vertex 0 is in 2 faces of B and 1 of A -> B; vertex 1: 1 A, 1 B -> A (first in file)
        text = ("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nv 2 0 0\n"
                "g A\nf 1 2 3\ng B\nf 1 3 4\nf 1 2 5\n")
        m = mic.parse_obj(text)
        assert mic.vertex_groups(m)[:2] == [1, 0]

    @pytest.mark.parametrize("text,match", [
        ("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", "before any 'g'"),
        ("v 0 0 0\ng A\nf 1 2 9\n", "out of range"),
        ("v 0 0 0\nv 1 0 0\ng A\nf 1 2\n", "at least 3"),
        ("v 0 0 0\n", "no faces"),
        ("g A B\n", "exactly one name"),
    ])
    def test_rejects(self, text, match):
        with pytest.raises(mic.MarvImportError, match=match):
            mic.parse_obj(text)


class TestBody:
    def test_fixture_body(self):
        b = _body()
        assert len(b.vertices) == 168 and len(b.vertex_tags) == 168
        assert b.vertex_tags[:8] == [INDEX["pelvis"]] * 8
        assert b.rest_pose == "arms_down"
        assert b.vertices[0][2] == pytest.approx(1.0 - 0.14)  # mm -> m

    def test_group_without_joint_is_rejected(self):
        # Kontrol: drop the joint but keep its OBJ group -> must fail, not skip.
        with pytest.raises(mic.MarvImportError, match="LeftUpperArm"):
            _body(doc=fx.joints_doc(drop=("LeftUpperArm",)))

    def test_loose_vertex_is_rejected(self):
        with pytest.raises(mic.MarvImportError, match="1 vertices used by no face"):
            _body(obj=fx.obj_text() + "v 9 9 9\n")

    def test_yup_input_lands_like_zup(self):
        # Same body written Y-up, facing +Z: after conversion it must match.
        doc = fx.joints_doc()
        swap = lambda p: [p[0], p[2], -p[1]]   # Blender (x,y,z) -> Y-up facing +Z
        for j in doc["joints"]:
            j["center"] = swap(j["center"])
            if "tail" in j:
                j["tail"] = swap(j["tail"])
        doc.update(up="+Y", forward="+Z")
        lines = []
        for line in fx.obj_text().splitlines():
            if line.startswith("v "):
                x, y, z = map(float, line.split()[1:])
                lines.append("v %r %r %r" % tuple(swap((x, y, z))))
            else:
                lines.append(line)
        a, b = _body(), _body(doc=doc, obj="\n".join(lines))
        assert [pytest.approx(v) for v in a.vertices] == b.vertices
        assert a.bones == [dict(x, head=pytest.approx(x["head"]), tail=pytest.approx(x["tail"])) for x in b.bones]
