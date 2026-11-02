"""Known case for the Marv import: the Humanoid starter, sent through Marv's files.

Run (Blender or pip bpy):
    python tests/verify_marv_roundtrip.py [--voxel 0.02]
    blender -b --python tests/verify_marv_roundtrip.py -- [--voxel 0.02]

1. Builds the HUMANOID starter, voxel-remeshes it (connected surface, tags kept).
2. Folds the bones Unity Humanoid has no slot for here (fingers -> hand,
   jaw/ears -> head), then rigs it the native way: Generate Rig.
3. Writes the same mesh as Marv would: OBJ in mm with one group per bone
   (face group = majority tag of its vertices; --face-rule first = first
   vertex) + joints.json from the starter's bone table.
4. Imports those files with Import Marv Body, rigs, and compares with step 2.

Prints: vertices whose tag the OBJ round trip changed (per-face groups
cannot always carry a per-vertex tag), bone head/tail error, and the
largest weight difference per vertex. Exit 1 if bones differ or a vertex
whose tag survived ends up on a different dominant bone.
--oracle-tags restores the native tags after import (self-test: must PASS).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADDON_NAME = os.path.basename(_ADDON_ROOT)
sys.path.insert(0, os.path.dirname(_ADDON_ROOT))

import bpy  # noqa: E402

addon = __import__(_ADDON_NAME)
addon.register()
rigging = sys.modules[f"{_ADDON_NAME}.rigging"]
core = sys.modules[f"{_ADDON_NAME}.marv_import_core"]

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
VOXEL = float(argv[argv.index("--voxel") + 1]) if "--voxel" in argv else 0.02
# Face group rule when writing the OBJ: tag of the first vertex, or majority of the face.
FACE_RULE = argv[argv.index("--face-rule") + 1] if "--face-rule" in argv else "majority"

FOLD = {"jaw": "head", "ear.L": "head", "ear.R": "head"}
for suffix in ("L", "R"):
    for finger in rigging.FINGER_NAMES:
        for i in range(1, 4):
            FOLD[rigging._finger_bone_name(finger, i, suffix)] = f"hand.{suffix}"
PIPE_TO_UNITY = {p: u for u, p in core.UNITY_TO_PIPESCULPT.items()}


def weights(obj):
    names = {g.index: g.name for g in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        out.append({names[g.group]: g.weight for g in v.groups if g.weight > 1e-6})
    return out


def rig(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    assert bpy.ops.pipe_sculpt.generate_rig() == {'FINISHED'}
    return obj.modifiers["GTR Armature"].object


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.pipe_sculpt.starter_humanoid(pose='T_POSE')
native = bpy.context.active_object
native.data.remesh_voxel_size = VOXEL
assert rigging.smart_voxel_remesh(native)

attr = native.data.attributes[rigging.VERTEX_ATTR]
tags = [attr.data[i].value for i in range(len(native.data.vertices))]
fold_idx = {rigging.BONE_NAME_TO_INDEX[a]: rigging.BONE_NAME_TO_INDEX[b] for a, b in FOLD.items()}
tags = [fold_idx.get(t, t) for t in tags]
attr.data.foreach_set("value", tags)
used = {rigging.DEFORM_BONE_NAMES[t] for t in tags if t >= 0}
unmapped = sorted(used - set(PIPE_TO_UNITY))
assert not unmapped, f"tags without a Unity slot after folding: {unmapped}"

# Native bone table restricted to the 21 bones the Marv path carries.
meta = json.loads(native[rigging.META_PROP])
keep = [b for b in meta["bones"] if b["id"] in PIPE_TO_UNITY or b["id"] == "root"]
native[rigging.META_PROP] = json.dumps({"bones": keep, "ik": []})
native_arm = rig(native)
native_w = weights(native)

# --- write Marv's files (mm, Blender frame) -----------------------------------
tmp = tempfile.mkdtemp(prefix="marv_roundtrip_")
joints = [{
    "name": PIPE_TO_UNITY[b["id"]],
    "parent": PIPE_TO_UNITY.get(b["parent"]) if b["parent"] in PIPE_TO_UNITY else None,
    "center": [c * 1000.0 for c in b["head"]],
    "tail": [c * 1000.0 for c in b["tail"]],
    "provenance": "PipeSculpt HUMANOID starter",
} for b in keep if b["id"] != "root"]
doc = {"schema": core.SCHEMA, "unit": "mm", "up": "+Z", "forward": "-Y",
       "rest_pose": "T_POSE", "mesh": "body.obj", "joints": joints}
with open(os.path.join(tmp, "joints.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f)

def face_tag(verts):
    if FACE_RULE == "first":
        return tags[verts[0]]
    counts = {}
    for v in verts:
        counts[tags[v]] = counts.get(tags[v], 0) + 1
    return min(counts, key=lambda t: (-counts[t], t))


by_group: dict[str, list] = {}
for p in native.data.polygons:
    by_group.setdefault(PIPE_TO_UNITY[rigging.DEFORM_BONE_NAMES[face_tag(p.vertices)]], []).append(p.vertices)
lines = [f"v {v.co.x * 1000.0!r} {v.co.y * 1000.0!r} {v.co.z * 1000.0!r}" for v in native.data.vertices]
for g, faces in by_group.items():
    lines.append(f"g {g}")
    lines.extend("f " + " ".join(str(i + 1) for i in f) for f in faces)
with open(os.path.join(tmp, "body.obj"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

# --- import through the Marv path --------------------------------------------
assert bpy.ops.pipe_sculpt.import_marv(filepath=os.path.join(tmp, "joints.json")) == {'FINISHED'}
marv = bpy.context.active_object
if "--oracle-tags" in argv:
    # Self-test of this check: hand the import the native tags. Must then PASS
    # with zero weight difference, or the comparison below is broken.
    marv.data.attributes[rigging.VERTEX_ATTR].data.foreach_set("value", tags)
marv_tags = [marv.data.attributes[rigging.VERTEX_ATTR].data[i].value for i in range(len(marv.data.vertices))]
marv_arm = rig(marv)
marv_w = weights(marv)

n = len(tags)
changed = [i for i in range(n) if marv_tags[i] != tags[i]]
bone_err = max(
    max((marv_arm.data.bones[b.name].head_local - b.head_local).length,
        (marv_arm.data.bones[b.name].tail_local - b.tail_local).length)
    for b in native_arm.data.bones if b.use_deform
)
diff = []
for a, b in zip(native_w, marv_w):
    keys = set(a) | set(b)
    diff.append(max((abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys), default=0.0))
kept = [i for i in range(n) if i not in set(changed)]
dominant_moved = [i for i in kept if max(native_w[i], key=native_w[i].get) != max(marv_w[i], key=marv_w[i].get)]

print(f"voxel {VOXEL} m, face rule {FACE_RULE}: {n} verts, {len(native.data.polygons)} faces, files in {tmp}")
print(f"tags changed by the OBJ round trip: {len(changed)} ({100.0 * len(changed) / n:.2f} %)")
print(f"bone head/tail max error: {bone_err:.3e} m")
print(f"weight max |diff| over all verts: {max(diff):.4f}; on verts with unchanged tag: "
      f"{max((diff[i] for i in kept), default=0.0):.4f}")
print(f"verts with unchanged tag whose dominant bone moved: {len(dominant_moved)}")
ok = bone_err < 1e-6 and not dominant_moved
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
