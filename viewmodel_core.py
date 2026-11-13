"""Viewmodel split -- pure Python: which renderer each face of a skinned body goes to.

Born Clean: NO bpy import. IronCore's player builder
(IronCorePlayerBuilder.SetupFirstPersonView) puts each SkinnedMeshRenderer on a
camera layer by its NAME: "Arms"/"Hand"/"Glove" -> the viewmodel overlay,
"Head"/"Hair"/... -> hidden from the own camera, the rest -> the body layer.
A body exported as one mesh therefore lands whole on the body layer, and the
own camera sees all of it (GHT lab 0064, 2026-11-13).

This module decides, per face, which of three meshes the face belongs to,
from the skin weights alone: the bone with the largest summed weight over the
face's vertices names the part. A tie goes to the body, so a face is never
moved to the viewmodel on a coin toss.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

ARMS = "Arms"
HEAD = "Head"
BODY = "Body"

# GTR's deform bone names (rigging.DEFORM_BONE_NAMES) per part. The clavicle
# stays with the body: it is the shoulder, which the own camera sees anyway.
ARM_BONES = frozenset({
    "upper_arm.L", "upper_arm.R", "forearm.L", "forearm.R", "hand.L", "hand.R",
})
HEAD_BONES = frozenset({"head"})


def part_of_bone(bone: str) -> str:
    """The part a bone's faces go to."""
    if bone in ARM_BONES:
        return ARMS
    if bone in HEAD_BONES:
        return HEAD
    return BODY


def face_part(vertex_weights: Iterable[Dict[str, float]]) -> str:
    """The part of one face, from its vertices' {bone: weight} maps.

    Weights are summed per bone over the face; the heaviest bone names the
    part. A face with no weight at all, or a tie between bones of different
    parts at the top, goes to the body.
    """
    total: Dict[str, float] = {}
    for w in vertex_weights:
        for bone, x in w.items():
            if x > 0.0:
                total[bone] = total.get(bone, 0.0) + x
    if not total:
        return BODY
    top = max(total.values())
    parts = {part_of_bone(b) for b, x in total.items() if x == top}
    return parts.pop() if len(parts) == 1 else BODY


def split_faces(faces: Sequence[Sequence[int]],
                weights: Sequence[Dict[str, float]]) -> Dict[str, List[int]]:
    """Face indices per part: {"Arms": [...], "Head": [...], "Body": [...]}."""
    out: Dict[str, List[int]] = {ARMS: [], HEAD: [], BODY: []}
    for i, f in enumerate(faces):
        out[face_part(weights[v] for v in f)].append(i)
    return out
