"""Marv import — pure Python reader for a Marv body (OBJ + joints.json).

Born Clean: NO bpy import. Parses the two files Marv writes across the file
boundary and turns them into the same data GTR already consumes:

  - a bone table (id, parent, head, tail, kind) in Blender space
    (metres, +Z up, character facing -Y, character's right at -X),
    serialised exactly like
    rigging._serialize_bones so Generate Rig reads it unchanged;
  - a per-vertex bone tag (index into rigging.DEFORM_BONE_NAMES), taken
    from the OBJ group of the vertex's faces.

The bpy side (marv_import_ops.py) only builds the mesh, writes the tag
attribute + metadata, and hands over to Generate Rig.

joints.json (schema "marv.joints/1"):

    {
      "schema": "marv.joints/1",
      "unit": "mm" | "m",                 # applies to the OBJ too
      "up": "+Z", "forward": "-Y",        # Marv's frame: all three axes are
      "right": "-X",                      # required (handedness is not assumed)
      "rest_pose": "arms_down",           # informational, stored on the mesh
      "mesh": "body.obj",                 # optional, relative to joints.json
      "joints": [
        {"name": "Hips", "parent": null, "center": [x, y, z],
         "tail": [x, y, z],               # required unless exactly one child
         "provenance": ...},              # opaque, copied through
        ...
      ]
    }

Joint names are Unity HumanBodyBones names. A joint's centre is the head of
its bone (Unity's own convention: a bone's transform sits at its proximal
joint). The tail is the only child's centre, or the explicit "tail".

OBJ: one `g <name>` per bone, same names as joints.json. A vertex takes the
group held by the majority of its faces; a tie goes to the group that
appears first in the file. A face outside any group is an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from . import validator_core
except ImportError:  # loaded as a top-level module by tests/conftest.py
    import validator_core


SCHEMA = "marv.joints/1"

UNIT_SCALE = {"mm": 0.001, "m": 1.0}

# Unity HumanBodyBones name -> PipeSculpt bone id. The required set is the
# inverse of validator_core.PIPESCULPT_TO_UNITY; toes are optional in Unity.
UNITY_TO_PIPESCULPT = {u: p for p, u in validator_core.PIPESCULPT_TO_UNITY.items()}
UNITY_TO_PIPESCULPT.update({"LeftToes": "toes.L", "RightToes": "toes.R"})

# Blender target frame: +Z up, character faces -Y (see validator_core.rule_facing_axis),
# character's right at -X (PipeSculpt's .L bones sit at +X).
_TARGET_UP = (2, 1.0)
_TARGET_FORWARD = (1, -1.0)
_TARGET_RIGHT = (0, -1.0)

# Root control bone, like HUMANOID's 'root': on the floor below the hips.
ROOT_BONE = "root"
ROOT_LENGTH = 0.20


class MarvImportError(ValueError):
    """The input files violate the format. The message names the offending item."""


@dataclass
class ObjMesh:
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)   # 0-based
    face_groups: list[int] = field(default_factory=list)          # index into groups
    groups: list[str] = field(default_factory=list)               # file order


@dataclass
class MarvBody:
    bones: list[dict]                    # rigging._serialize_bones shape
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]
    vertex_tags: list[int]               # index into DEFORM_BONE_NAMES
    provenance: dict                     # bone id -> provenance as given
    rest_pose: str | None


# --- axes -------------------------------------------------------------------

def _parse_axis(text: str, what: str) -> tuple[int, float]:
    if not isinstance(text, str) or len(text) != 2 or text[0] not in "+-" or text[1] not in "XYZ":
        raise MarvImportError(f"'{what}' must be one of +X -X +Y -Y +Z -Z, got {text!r}")
    return "XYZ".index(text[1]), (1.0 if text[0] == "+" else -1.0)


def axis_matrix(up: str, forward: str, right: str) -> tuple[tuple[float, float, float], ...]:
    """Matrix (rows) taking the source frame to Blender's (+Z up, facing -Y, right -X).

    All three axes are declared, so a left-handed source (e.g. Unity's: up +Y,
    forward +Z, right +X) gives determinant -1: a change of handedness, not a
    rotation. Without 'right' that frame would be read as its mirror image and
    every .L bone would land on the character's right side.
    """
    axes = [_parse_axis(up, "up"), _parse_axis(forward, "forward"), _parse_axis(right, "right")]
    if len({a[0] for a in axes}) != 3:
        raise MarvImportError(f"'up' {up}, 'forward' {forward} and 'right' {right} must use three different axes")
    targets = (_TARGET_UP, _TARGET_FORWARD, _TARGET_RIGHT)
    rows = [[0.0, 0.0, 0.0] for _ in range(3)]
    for (src_i, src_sign), (dst_i, dst_sign) in zip(axes, targets):
        rows[dst_i][src_i] = src_sign * dst_sign
    return tuple(tuple(r) for r in rows)


def determinant(m) -> float:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _transform(m, scale, p):
    return tuple(scale * (m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2]) for i in range(3))


# --- joints.json ------------------------------------------------------------

def _point(value, where: str) -> tuple[float, float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)):
        raise MarvImportError(f"{where} must be [x, y, z] numbers, got {value!r}")
    return float(value[0]), float(value[1]), float(value[2])


def parse_joints(doc: dict) -> dict:
    """Validate a joints.json document. Returns a normalised dict (source frame)."""
    if not isinstance(doc, dict):
        raise MarvImportError("joints.json must be a JSON object")
    if doc.get("schema") != SCHEMA:
        raise MarvImportError(f"schema must be '{SCHEMA}', got {doc.get('schema')!r}")
    unit = doc.get("unit")
    if unit not in UNIT_SCALE:
        raise MarvImportError(f"unit must be one of {sorted(UNIT_SCALE)}, got {unit!r}")
    matrix = axis_matrix(doc.get("up"), doc.get("forward"), doc.get("right"))
    joints = doc.get("joints")
    if not isinstance(joints, list) or not joints:
        raise MarvImportError("'joints' must be a non-empty list")

    by_name: dict[str, dict] = {}
    for i, j in enumerate(joints):
        if not isinstance(j, dict):
            raise MarvImportError(f"joints[{i}] must be an object")
        name = j.get("name")
        if name not in UNITY_TO_PIPESCULPT:
            raise MarvImportError(
                f"joints[{i}].name {name!r} is not a supported Unity Humanoid bone "
                f"(supported: {', '.join(sorted(UNITY_TO_PIPESCULPT))})"
            )
        if name in by_name:
            raise MarvImportError(f"joint '{name}' appears twice")
        entry = {
            "name": name,
            "parent": j.get("parent"),
            "center": _point(j.get("center"), f"joint '{name}'.center"),
            "tail": _point(j["tail"], f"joint '{name}'.tail") if j.get("tail") is not None else None,
            "provenance": j.get("provenance"),
        }
        by_name[name] = entry

    roots = [n for n, j in by_name.items() if j["parent"] is None]
    if roots != ["Hips"]:
        raise MarvImportError(f"exactly one root joint, 'Hips', expected; got {roots}")
    children: dict[str, list[str]] = {n: [] for n in by_name}
    for n, j in by_name.items():
        p = j["parent"]
        if p is None:
            continue
        if p not in by_name:
            raise MarvImportError(f"joint '{n}' has unknown parent {p!r}")
        children[p].append(n)
    # Every joint must reach Hips (no cycles, no islands).
    for n in by_name:
        seen = set()
        cur = n
        while cur is not None:
            if cur in seen:
                raise MarvImportError(f"joint '{n}' sits in a parent cycle")
            seen.add(cur)
            cur = by_name[cur]["parent"]

    for n, j in by_name.items():
        if j["tail"] is None:
            if len(children[n]) != 1:
                raise MarvImportError(
                    f"joint '{n}' has {len(children[n])} children and no 'tail'; "
                    "give 'tail' explicitly"
                )
            j["tail"] = by_name[children[n][0]]["center"]
        if j["tail"] == j["center"]:
            raise MarvImportError(f"joint '{n}' has zero length (tail == center)")

    return {
        "unit": unit,
        "scale": UNIT_SCALE[unit],
        "matrix": matrix,
        "rest_pose": doc.get("rest_pose"),
        "joints": by_name,
        "order": [j["name"] for j in joints],
    }


def bones_from_joints(parsed: dict) -> tuple[list[dict], dict]:
    """Bone table in Blender space (rigging._serialize_bones shape) + provenance map."""
    m, s = parsed["matrix"], parsed["scale"]
    joints = parsed["joints"]
    hips = _transform(m, s, joints["Hips"]["center"])
    floor_z = min(
        min(_transform(m, s, j["center"])[2], _transform(m, s, j["tail"])[2])
        for j in joints.values()
    )
    bones = [{
        "id": ROOT_BONE, "parent": None,
        "head": [hips[0], hips[1], floor_z],
        "tail": [hips[0], hips[1], floor_z + ROOT_LENGTH],
        "kind": 'C',
    }]
    provenance = {}
    for name in parsed["order"]:
        j = joints[name]
        bone_id = UNITY_TO_PIPESCULPT[name]
        parent = UNITY_TO_PIPESCULPT[j["parent"]] if j["parent"] else ROOT_BONE
        bones.append({
            "id": bone_id,
            "parent": parent,
            "head": list(_transform(m, s, j["center"])),
            "tail": list(_transform(m, s, j["tail"])),
            "kind": 'D',
        })
        provenance[bone_id] = j["provenance"]
    return bones, provenance


# --- OBJ --------------------------------------------------------------------

def parse_obj(text: str) -> ObjMesh:
    """Minimal OBJ reader: v, f (any of v, v/vt, v//vn, v/vt/vn), g. Rest ignored."""
    mesh = ObjMesh()
    group_index: dict[str, int] = {}
    current = -1
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            if len(parts) < 4:
                raise MarvImportError(f"OBJ line {lineno}: vertex needs x y z")
            try:
                mesh.vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except ValueError:
                raise MarvImportError(f"OBJ line {lineno}: bad vertex {line!r}") from None
        elif tag == "g":
            if len(parts) != 2:
                raise MarvImportError(f"OBJ line {lineno}: 'g' needs exactly one name, got {line!r}")
            name = parts[1]
            if name not in group_index:
                group_index[name] = len(mesh.groups)
                mesh.groups.append(name)
            current = group_index[name]
        elif tag == "f":
            if current < 0:
                raise MarvImportError(f"OBJ line {lineno}: face before any 'g' group")
            idx = []
            for tok in parts[1:]:
                try:
                    k = int(tok.split("/", 1)[0])
                except ValueError:
                    raise MarvImportError(f"OBJ line {lineno}: bad face index {tok!r}") from None
                k = k - 1 if k > 0 else len(mesh.vertices) + k
                if not 0 <= k < len(mesh.vertices):
                    raise MarvImportError(f"OBJ line {lineno}: face index {tok} out of range")
                idx.append(k)
            if len(idx) < 3:
                raise MarvImportError(f"OBJ line {lineno}: face needs at least 3 vertices")
            mesh.faces.append(tuple(idx))
            mesh.face_groups.append(current)
    if not mesh.faces:
        raise MarvImportError("OBJ has no faces")
    return mesh


def vertex_groups(mesh: ObjMesh) -> list[int]:
    """Group per vertex: majority of incident faces, tie -> first group in file. -1 if unused."""
    counts: list[dict[int, int]] = [dict() for _ in mesh.vertices]
    for face, g in zip(mesh.faces, mesh.face_groups):
        for v in face:
            counts[v][g] = counts[v].get(g, 0) + 1
    out = []
    for c in counts:
        if not c:
            out.append(-1)
            continue
        out.append(min(c, key=lambda g: (-c[g], g)))
    return out


# --- both -------------------------------------------------------------------

def build_body(joints_doc: dict, obj_text: str, bone_index: dict[str, int]) -> MarvBody:
    """Join joints.json and the OBJ into a MarvBody.

    bone_index is rigging.BONE_NAME_TO_INDEX (passed in so this module stays
    bpy-free). Every OBJ group must name a joint; unused vertices are an error,
    since Generate Rig would leave them unskinned.
    """
    parsed = parse_joints(joints_doc)
    bones, provenance = bones_from_joints(parsed)
    mesh = parse_obj(obj_text)

    unknown = [g for g in mesh.groups if g not in parsed["joints"]]
    if unknown:
        raise MarvImportError(f"OBJ groups without a joint in joints.json: {', '.join(unknown)}")
    tag_of_group = []
    for g in mesh.groups:
        bone_id = UNITY_TO_PIPESCULPT[g]
        if bone_id not in bone_index:
            raise MarvImportError(f"bone '{bone_id}' has no GTR tag index")
        tag_of_group.append(bone_index[bone_id])

    per_vertex = vertex_groups(mesh)
    loose = sum(1 for g in per_vertex if g < 0)
    if loose:
        raise MarvImportError(f"OBJ has {loose} vertices used by no face")

    m, s = parsed["matrix"], parsed["scale"]
    # A handedness change mirrors the winding; reverse it so normals stay outward.
    faces = mesh.faces if determinant(m) > 0 else [tuple(reversed(f)) for f in mesh.faces]
    return MarvBody(
        bones=bones,
        vertices=[_transform(m, s, v) for v in mesh.vertices],
        faces=faces,
        vertex_tags=[tag_of_group[g] for g in per_vertex],
        provenance=provenance,
        rest_pose=parsed["rest_pose"],
    )
