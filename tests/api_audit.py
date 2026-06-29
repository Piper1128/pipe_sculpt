"""Deprecation / API audit — register the addon in the installed Blender and
exercise the version-sensitive API calls, so any deprecation warning or
removed/changed-API error surfaces against the real binary.

This is the harness that caught the Curves.remove_curves() keyword change
in Blender 5.1. Re-run it whenever Blender updates to catch API drift before
it reaches users.

Run:
  "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" ^
      --background --python tests/api_audit.py

Exit code is non-zero if any check fails, so it can gate CI.
"""
import os
import sys
import importlib
import traceback

import bpy

# Addon root = parent of this tests/ folder.
_ADDON = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_ADDON)
for p in (_ADDON, _PARENT):
    if p not in sys.path:
        sys.path.insert(0, p)

SEP = "=" * 64
problems = []


def check(label, fn):
    try:
        fn()
        print(f"  OK   {label}")
    except Exception as e:
        print(f"  FAIL {label}: {e}")
        problems.append((label, str(e)))


print("\n" + SEP)
print("API AUDIT — Blender", bpy.app.version_string)
print(SEP)

bpy.ops.wm.read_factory_settings(use_empty=True)

print("\n[1] Addon registration")
try:
    mod = importlib.import_module("pipe_sculpt")
    mod.register()
    print("  OK   pipe_sculpt.register()")
except Exception:
    traceback.print_exc()
    problems.append(("register", "see traceback"))

print("\n[2] Version-sensitive API surface")


def _calc_loop_tris():
    bpy.ops.mesh.primitive_cube_add()
    m = bpy.context.active_object.data
    m.calc_loop_triangles()
    _ = list(m.loop_triangles)


check("Mesh.calc_loop_triangles()", _calc_loop_tris)


def _vertex_normals():
    _ = bpy.context.active_object.data.vertices[0].normal


check("Mesh vertex .normal (auto-computed 4.1+)", _vertex_normals)


def _hair_curves_api():
    hc = bpy.data.hair_curves.new("AuditHair")
    hc.add_curves([4, 4, 4])
    assert len(hc.curves) == 3
    assert len(hc.points) == 12
    hc.points.foreach_set("position", [0.0] * 36)
    hc.remove_curves()  # no-args = remove all (5.1 rejects positional None)
    assert len(hc.curves) == 0


check("HairCurves add_curves / foreach_set / remove_curves", _hair_curves_api)


def _curves_surface():
    bpy.ops.mesh.primitive_uv_sphere_add()
    sphere = bpy.context.active_object
    hc = bpy.data.hair_curves.new("AuditHair2")
    hc.surface = sphere
    assert hc.surface is sphere


check("HairCurves.surface binding", _curves_surface)

print("\n[3] Operator smoke test (real addon operators)")


def _starter_and_rig():
    bpy.ops.pipe_sculpt.starter_humanoid()
    bpy.ops.pipe_sculpt.generate_rig()


check("starter_humanoid + generate_rig", _starter_and_rig)


def _unwrap():
    bpy.ops.mesh.primitive_monkey_add()
    bpy.ops.pipe_sculpt.uv_smart_unwrap()


check("uv_smart_unwrap", _unwrap)
check("uv_checker_toggle", lambda: bpy.ops.pipe_sculpt.uv_checker_toggle())
check("uv_texel_density (report)", lambda: bpy.ops.pipe_sculpt.uv_texel_density(apply_scale=False))


def _validate_rigged():
    # Rig first so the validator passes — we're testing the data-extraction
    # API path, not deliberately tripping UNSKINNED_VERTS. (A reporting
    # operator that hits self.report({'ERROR'}) makes bpy.ops raise.)
    bpy.ops.pipe_sculpt.starter_humanoid()
    mesh = bpy.context.active_object
    bpy.ops.pipe_sculpt.generate_rig()
    # Generate Rig leaves the armature active; validate_unity needs the mesh
    bpy.ops.object.select_all(action='DESELECT')
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = mesh
    bpy.ops.pipe_sculpt.validate_unity('EXEC_DEFAULT', weight_limit=4)


check("validate_unity (on rigged mesh)", _validate_rigged)


def _hair_spawn_and_respawn():
    bpy.ops.mesh.primitive_uv_sphere_add(location=(5, 0, 0))
    bpy.ops.pipe_sculpt.uv_smart_unwrap()
    bpy.ops.pipe_sculpt.hair_setup()
    bpy.ops.pipe_sculpt.hair_apply_preset('EXEC_DEFAULT', preset='FUR_SHORT', max_strands=2000, seed=1)
    # Re-spawn hits remove_curves() — the path the keyword bug lived in
    bpy.ops.pipe_sculpt.hair_apply_preset('EXEC_DEFAULT', preset='FUR_SHORT', max_strands=1500, seed=2)


check("hair_setup + spawn + RE-spawn (native curves)", _hair_spawn_and_respawn)


def _fbx_export():
    import tempfile
    bpy.ops.mesh.primitive_cube_add(location=(10, 0, 0))
    out = os.path.join(tempfile.gettempdir(), "_audit_export.fbx")
    bpy.ops.pipe_sculpt.export_unity_fbx('EXEC_DEFAULT', filepath=out)
    if os.path.exists(out):
        os.remove(out)


check("export_unity_fbx", _fbx_export)


def _anim_pose_tools():
    # Exercises context.selected_pose_bones (Bone.select was removed in 5.x)
    bpy.ops.pipe_sculpt.starter_humanoid()
    mesh = bpy.context.active_object
    bpy.ops.pipe_sculpt.generate_rig()
    arm = bpy.context.active_object
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.select_all(action='DESELECT')
    bpy.ops.pipe_sculpt.anim_copy_pose()
    bpy.ops.pipe_sculpt.anim_mirror_pose()
    bpy.ops.pipe_sculpt.anim_reset_pose()
    bpy.ops.object.mode_set(mode='OBJECT')


check("anim pose tools (copy/mirror/reset)", _anim_pose_tools)


def _anim_keying_loop_breakdown():
    # Keys two frames, then exercises the slotted-action fcurve path:
    # key rig, make cyclic, validate loop, toggle interp, breakdown (exec).
    bpy.ops.pipe_sculpt.starter_humanoid()
    bpy.ops.pipe_sculpt.generate_rig()
    arm = bpy.context.active_object
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    sc = bpy.context.scene
    sc.frame_set(1)
    bpy.ops.pipe_sculpt.anim_key_rig()
    pb = arm.pose.bones["upper_arm.L"]
    pb.rotation_mode = 'QUATERNION'
    sc.frame_set(10)
    pb.rotation_quaternion = (0.9, 0.4, 0.0, 0.0)
    bpy.ops.pipe_sculpt.anim_key_rig()
    bpy.ops.pipe_sculpt.anim_fit_range()
    bpy.ops.pipe_sculpt.anim_validate_loop('EXEC_DEFAULT')
    bpy.ops.pipe_sculpt.anim_toggle_interp()
    sc.frame_set(5)
    bpy.ops.pose.select_all(action='SELECT')
    bpy.ops.pipe_sculpt.anim_breakdown('EXEC_DEFAULT', blend=0.5)
    bpy.ops.pipe_sculpt.anim_make_cyclic('EXEC_DEFAULT')
    bpy.ops.object.mode_set(mode='OBJECT')


check("anim keying/loop/breakdown (channelbag fcurves)", _anim_keying_loop_breakdown)


def _bone_picker():
    # Exercises PoseBone.select writes + arm.data.bones.active
    bpy.ops.pipe_sculpt.starter_humanoid()
    bpy.ops.pipe_sculpt.generate_rig()
    arm = bpy.context.active_object
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pipe_sculpt.pick_bone(bone="upper_arm.L", extend=False)
    bpy.ops.pipe_sculpt.pick_bone(bone="hand.R", extend=True)
    bpy.ops.pipe_sculpt.pick_side(side='L')
    bpy.ops.pipe_sculpt.pick_side(side='NONE')
    bpy.ops.object.mode_set(mode='OBJECT')


check("bone picker (pick / extend / side)", _bone_picker)

print("\n" + SEP)
if problems:
    print(f"AUDIT: {len(problems)} PROBLEM(S)")
    for label, err in problems:
        print(f"  - {label}: {err}")
    print(SEP)
    sys.exit(1)
print("AUDIT: all checks passed — no deprecated/removed API in this Blender")
print(SEP)
