"""tools/fbx_transforms.py's judgement, on documents shaped like its read().

The known case is GHT lab/data/0064 (2026-11-14): Marv's armature Null with Lcl Scaling
100 in a file in centimetres, which Unity imported with lossyScale 100.
"""
import fbx_transforms as ft


def _doc(arm_scale, root_rot=(90.0, 0.0, 0.0)):
    return {"version": 7400, "unit_scale_factor": 1.0, "models": [
        {"name": "m_Armature", "type": "Null", "translation": [0, 0, 0],
         "rotation": [-90.0, 0.0, 0.0], "scaling": list(arm_scale), "prerotation": [0, 0, 0],
         "parent": None},
        {"name": "root", "type": "LimbNode", "translation": [0, 0, 0],
         "rotation": list(root_rot), "scaling": [1.0, 1.0, 1.0], "prerotation": [0, 0, 0],
         "parent": "m_Armature"},
        {"name": "upper_leg.L", "type": "LimbNode", "translation": [0, 0, 0],
         "rotation": [0, 0, 0], "scaling": [1.0000016689300537, 1.000000238418579, 1.0],
         "prerotation": [0, 0, 0], "parent": "root"},
        {"name": "m_Body", "type": "Mesh", "translation": [0, 0, 0], "rotation": [0, 0, 0],
         "scaling": [1.0, 1.0, 1.0], "prerotation": [0, 0, 0], "parent": None},
    ]}


def test_the_known_case_is_refused():
    bad = ft.faults(_doc((100.0, 100.0, 100.0)))
    assert bad == ["m_Armature (Null): Lcl Scaling [100.0, 100.0, 100.0]"]


def test_unit_scale_passes_and_float32_noise_is_not_a_scale():
    assert ft.faults(_doc((1.0, 1.0, 1.0))) == []


def test_a_scale_just_past_float32_noise_is_caught():
    assert ft.faults(_doc((1.0001, 1.0, 1.0)))


def test_the_turned_armature_is_reported_with_its_child():
    tops = ft.turned_tops(_doc((1.0, 1.0, 1.0)))
    assert tops == [("m_Armature", [-90.0, 0.0, 0.0], [("root", [90.0, 0.0, 0.0])])]
