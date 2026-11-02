"""Webbing check on an exported FBX: raise both upper arms 80 degrees and count
torso/thigh vertices (dominant weight on pelvis, spine, chest or upper_leg) that
move more than 2 cm. Arms fused to the torso drag those vertices into a web.

Run (pip bpy or Blender):
    python tests/verify_webbing.py character.fbx

Known cases (2026-10-19, Marv bodies through tools/marv_to_unity.py):
arms down, fused to the torso: male 252 verts dragged (max 34.2 cm), female 500
(max 42.5 cm); arms turned 12 deg out (marv adf8dcd): 0 and 0 (max 0.5 cm).
"""
import sys, math, bpy, bmesh
from mathutils import Matrix, Vector
fbx = sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx)
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
me = next(o for o in bpy.data.objects if o.type == 'MESH')
bm = bmesh.new(); bm.from_mesh(me.data)
euler = len(bm.verts) - len(bm.edges) + len(bm.faces); bm.free()
names = {g.index: g.name for g in me.vertex_groups}
dom = []
for v in me.data.vertices:
    dom.append(names[max(v.groups, key=lambda g: g.weight).group] if v.groups else None)
dg = bpy.context.evaluated_depsgraph_get()
rest = [me.matrix_world @ v.co for v in me.evaluated_get(dg).to_mesh().vertices]
for side in ("L", "R"):
    pb = arm.pose.bones[f"upper_arm.{side}"]
    # world direction that lifts the arm sideways: away from the body midline and up
    head = arm.matrix_world @ pb.bone.head_local
    out = Vector((1 if head.x > 0 else -1, 0, 0))
    axis_world = (arm.matrix_world.to_3x3() @ (pb.bone.tail_local - pb.bone.head_local)).normalized().cross(out).normalized()
    # rotate so the arm swings toward 'out': try both signs, keep the one raising the hand
    best = None
    for sgn in (1, -1):
        pb.rotation_mode = 'QUATERNION'
        q_world = Matrix.Rotation(sgn * math.radians(80), 3, axis_world)
        local = (arm.matrix_world.to_3x3() @ pb.bone.matrix_local.to_3x3()).inverted() @ q_world @ (arm.matrix_world.to_3x3() @ pb.bone.matrix_local.to_3x3())
        pb.rotation_quaternion = local.to_quaternion()
        bpy.context.view_layer.update()
        tail_z = (arm.matrix_world @ pb.tail).z
        if best is None or tail_z > best[0]: best = (tail_z, pb.rotation_quaternion.copy())
    pb.rotation_quaternion = best[1]
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
posed = [me.matrix_world @ v.co for v in me.evaluated_get(dg).to_mesh().vertices]
torso = {"pelvis", "spine", "chest", "upper_leg.L", "upper_leg.R"}
moved = [i for i, d in enumerate(dom) if d in torso and (posed[i] - rest[i]).length > 0.02]
mx = max(((posed[i] - rest[i]).length for i, d in enumerate(dom) if d in torso), default=0)
print(f"{fbx.split('/')[-2]}/{fbx.split('/')[-1]}: Euler {euler}, torso verts dragged >2 cm: {len(moved)} of {sum(1 for d in dom if d in torso)}, max {mx*100:.1f} cm")
