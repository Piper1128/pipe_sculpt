"""viewmodel_core: which renderer a face of a skinned body goes to."""
import viewmodel_core as vc


def test_arm_bones_go_to_arms_and_the_clavicle_stays():
    for b in ("upper_arm.L", "forearm.R", "hand.L"):
        assert vc.part_of_bone(b) == vc.ARMS
    assert vc.part_of_bone("clavicle.L") == vc.BODY
    assert vc.part_of_bone("head") == vc.HEAD
    assert vc.part_of_bone("neck") == vc.BODY


def test_the_heaviest_bone_over_the_face_names_the_part():
    # Two vertices lean to the chest, one hard to the upper arm: the sum decides.
    w = [{"chest": 0.6, "upper_arm.L": 0.4}, {"chest": 0.6, "upper_arm.L": 0.4},
         {"upper_arm.L": 1.0}]
    assert vc.face_part(w) == vc.ARMS  # 1.8 against 1.2
    w[2] = {"chest": 1.0}
    assert vc.face_part(w) == vc.BODY  # 2.2 against 0.8


def test_ties_and_unweighted_faces_go_to_the_body():
    assert vc.face_part([{"hand.L": 0.5, "chest": 0.5}]) == vc.BODY
    assert vc.face_part([{}, {"head": 0.0}]) == vc.BODY
    # A tie between two arm bones is still the arms.
    assert vc.face_part([{"hand.L": 0.5, "forearm.L": 0.5}]) == vc.ARMS


def test_split_faces_keeps_every_face_once():
    weights = [{"head": 1.0}, {"hand.R": 1.0}, {"spine": 1.0}, {"head": 1.0}]
    faces = [(0, 3, 2), (1, 1, 2), (2, 2, 2), (0, 1, 2)]
    s = vc.split_faces(faces, weights)
    assert sorted(s[vc.ARMS] + s[vc.HEAD] + s[vc.BODY]) == [0, 1, 2, 3]
    assert s[vc.HEAD] == [0]
    assert s[vc.ARMS] == [1]
    assert s[vc.BODY] == [2, 3]
