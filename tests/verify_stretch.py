"""Stretch check on an exported FBX: raise upper_arm.R 150 degrees sideways, then
(from rest) bend upper_leg.L 90 degrees forward, and count triangles with an edge
stretched more than 2.5x against the rest mesh. Narrow weight blends between
bones tear the skin at shoulder and hip; this counts the tear.

Run (pip bpy or Blender):
    python tests/verify_stretch.py character.fbx [--max N]

--max N: exit 1 if either pose has more than N stretched triangles.

Known cases (2026-11-01, Marv trunk bodies, Quadriflow 22k, measured on the rig
before export with the same poses): GTR Tags weights male 162 (arm) / 169 (hip),
female 176 / 274; Heat weights uncapped male 2 / 0, female 22 / 0. On the exported
FBX with the 4-bone cap (marv_to_unity's default): Heat male 24 / 10, female
75 / 37 (README, reproduced 2026-11-11). Unity's own measure on
the GTR FBXs (Grenade Throw clip) put them at 0.7-1.4 % of triangles stretched,
against 0.09 % for GHT's SK_Military_Survivalist.
"""
import math
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
fbx = argv[0]
limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx)
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
me = next(o for o in bpy.data.objects if o.type == 'MESH')
A = arm.matrix_world


def world_head_tail(name):
    pb = arm.pose.bones[name]
    return A @ pb.head, A @ pb.tail


def evaluated():
    dg = bpy.context.evaluated_depsgraph_get()
    m = me.evaluated_get(dg).to_mesh()
    return [me.matrix_world @ v.co for v in m.vertices]


# Body frame from the skeleton itself, not from the file's axis settings.
up = (world_head_tail("head")[0] - world_head_tail("pelvis")[0]).normalized()
fh, ft = world_head_tail("foot.L")
forward = (ft - fh) - up * (ft - fh).dot(up)
forward.normalize()
side = up.cross(forward).normalized()


def rotate(name, axis, deg, score):
    """Rotate a pose bone about a world axis through its head; keep the sign that maximises score(tail)."""
    pb = arm.pose.bones[name]
    best = None
    for sgn in (1, -1):
        pb.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()
        head = A @ pb.head
        R = Matrix.Translation(head) @ Matrix.Rotation(math.radians(sgn * deg), 4, axis) @ Matrix.Translation(-head)
        pb.matrix = A.inverted() @ R @ A @ pb.matrix
        bpy.context.view_layer.update()
        s = score(A @ pb.tail)
        if best is None or s > best[0]:
            best = (s, pb.matrix_basis.copy())
    pb.matrix_basis = best[1]
    bpy.context.view_layer.update()


me.data.calc_loop_triangles()
tris = [tuple(t.vertices) for t in me.data.loop_triangles]
for pb in arm.pose.bones:
    pb.matrix_basis = Matrix.Identity(4)
bpy.context.view_layer.update()
rest = evaluated()


def count(posed):
    n, worst = 0, 0.0
    for t in tris:
        r = 0.0
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            l0 = (rest[a] - rest[b]).length
            if l0 > 1e-9:
                r = max(r, (posed[a] - posed[b]).length / l0)
        n += r > 2.5
        worst = max(worst, r)
    return n, worst


results = {}
for label, bone, axis, deg, score in (
    ("arm_up_150", "upper_arm.R", forward, 150, lambda t: t.dot(up)),
    ("hip_flex_90", "upper_leg.L", side, 90, lambda t: t.dot(forward)),
):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    rotate(bone, axis, deg, score)
    results[label] = count(evaluated())

name = "/".join(fbx.replace("\\", "/").split("/")[-2:])
print(f"{name}: {len(tris)} tris; " + "; ".join(
    f"{k}: {n} stretched >2.5x, max {w:.2f}x" for k, (n, w) in results.items()))
if limit is not None and any(n > limit for n, _ in results.values()):
    sys.exit(1)
