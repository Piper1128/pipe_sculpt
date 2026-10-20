"""Headless Marv -> Unity Humanoid FBX: import, retopo, UV, Generate Rig, validate, export.

Runs the addon's own operators in order, so it measures the shipped code,
not a copy. Works in Blender or with the `bpy` module from pip:

    blender -b --python tools/marv_to_unity.py -- joints.json out.fbx [options]
    python  tools/marv_to_unity.py joints.json out.fbx [options]      # pip bpy

Options:
    --obj PATH           body mesh (default: 'mesh' field in joints.json)
    --target-faces N     retopo target; skipped if the mesh is already below it
    --retopo METHOD      QUADRIFLOW (default) or DECIMATE
    --report PATH        write the measured report as JSON
    --fixture DIR        write tests/marv_fixture.py's body to DIR first and use it
    --fixture-drop NAME  leave a bone out of the fixture (repeatable)
    --box-mesh MM        no OBJ yet: write one axis-aligned box per joint (head..tail,
                         grown by MM in the file's unit) and use it. Tests the joints
                         and the chain, not a body.

Exit code 0 = validator passed and the FBX re-imports with every deform
bone; 1 = it did not; 2 = import failed. The report says which.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADDON_PARENT = os.path.dirname(_ADDON_ROOT)
_ADDON_NAME = os.path.basename(_ADDON_ROOT)


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(prog="marv_to_unity")
    p.add_argument("joints")
    p.add_argument("fbx")
    p.add_argument("--obj", default="")
    p.add_argument("--target-faces", type=int, default=22000)
    p.add_argument("--retopo", choices=("QUADRIFLOW", "DECIMATE"), default="QUADRIFLOW")
    p.add_argument("--report", default="")
    p.add_argument("--fixture", default="")
    p.add_argument("--fixture-drop", action="append", default=[])
    p.add_argument("--box-mesh", type=float, default=0.0)
    return p.parse_args(argv)


def _write_fixture(directory, drop):
    sys.path.insert(0, os.path.join(_ADDON_ROOT, "tests"))
    import marv_fixture
    os.makedirs(directory, exist_ok=True)
    doc = marv_fixture.joints_doc(drop=tuple(drop))
    doc["mesh"] = "body.obj"
    joints = os.path.join(directory, "joints.json")
    with open(joints, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    with open(os.path.join(directory, "body.obj"), "w", encoding="utf-8") as f:
        f.write(marv_fixture.obj_text(drop=tuple(drop)))
    return joints


def _write_box_mesh(joints_path, half_width):
    """One box per joint from its centre to its tail (only child's centre if absent)."""
    import tempfile
    with open(joints_path, encoding="utf-8") as f:
        doc = json.load(f)
    by_name = {j["name"]: j for j in doc["joints"]}
    children = {}
    for j in doc["joints"]:
        children.setdefault(j.get("parent"), []).append(j["name"])
    lines = [f"# box mesh from {os.path.basename(joints_path)}, half-width {half_width}"]
    base = 1
    for j in doc["joints"]:
        c = j["center"]
        t = j.get("tail") or by_name[children[j["name"]][0]]["center"]
        lo = [min(c[i], t[i]) - half_width for i in range(3)]
        hi = [max(c[i], t[i]) + half_width for i in range(3)]
        lines.append(f"g {j['name']}")
        for x in (lo[0], hi[0]):
            for y in (lo[1], hi[1]):
                for z in (lo[2], hi[2]):
                    lines.append(f"v {x!r} {y!r} {z!r}")
        for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            lines.append("f " + " ".join(str(base + k) for k in q))
        base += 8
    path = os.path.join(tempfile.mkdtemp(prefix="marv_boxes_"), "boxes.obj")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _run(args, report):
    import bpy
    sys.path.insert(0, _ADDON_PARENT)
    # Factory settings first: it resets preferences, which would drop the addon.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import addon_utils
    addon = addon_utils.enable(_ADDON_NAME, default_set=True)
    if addon is None:  # enable() reports and returns None on failure
        raise RuntimeError(f"could not enable addon '{_ADDON_NAME}' from {_ADDON_PARENT}")
    rigging = sys.modules[f"{_ADDON_NAME}.rigging"]
    validator_core = sys.modules[f"{_ADDON_NAME}.validator_core"]
    validator_ops = sys.modules[f"{_ADDON_NAME}.validator_ops"]

    t0 = time.perf_counter()

    def step(name, call):
        # An operator that reports ERROR raises RuntimeError under bpy; keep its text.
        entry = {"step": name}
        try:
            result = call()
        except RuntimeError as e:
            result, entry["error"] = {'CANCELLED'}, str(e).strip()
        entry.update(result=sorted(result), t_s=round(time.perf_counter() - t0, 3))
        report["steps"].append(entry)
        return result == {'FINISHED'}

    if not step("import_marv", lambda: bpy.ops.pipe_sculpt.import_marv(filepath=args.joints, obj_path=args.obj)):
        return 2
    src = bpy.context.active_object
    report["source"] = {"verts": len(src.data.vertices), "faces": len(src.data.polygons)}

    mesh = src
    if len(src.data.polygons) > args.target_faces:
        bpy.context.scene.pipe_sculpt_preset = 'CHARACTER'
        prefs = bpy.context.preferences.addons.get(_ADDON_NAME)
        if prefs is not None:
            prefs.preferences.target_faces_character = args.target_faces
        else:
            report["notes"].append(
                f"addon preferences absent; retopo uses the preset default target")
        if not step("workflow_retopo", lambda: bpy.ops.pipe_sculpt.workflow_retopo(method=args.retopo)):
            return 1
        mesh = bpy.context.active_object
        if len(mesh.data.polygons) > args.target_faces * 1.5:
            report["notes"].append(
                f"retopo left {len(mesh.data.polygons)} faces for a target of {args.target_faces}")
            return 1
    report["mesh"] = {"verts": len(mesh.data.vertices), "faces": len(mesh.data.polygons)}

    bpy.context.view_layer.objects.active = mesh
    step("uv_smart_unwrap", bpy.ops.pipe_sculpt.uv_smart_unwrap)
    bpy.context.view_layer.objects.active = mesh
    if not step("generate_rig", bpy.ops.pipe_sculpt.generate_rig):
        return 1
    arm = mesh.modifiers["GTR Armature"].object
    report["armature"] = {
        "bones": len(arm.data.bones),
        "deform": sorted(b.name for b in arm.data.bones if b.use_deform),
    }

    influences = [sum(1 for g in v.groups if g.weight > 0.001) for v in mesh.data.vertices]
    group_names = {g.index: g.name for g in mesh.vertex_groups}
    populated = {group_names[g.group] for v in mesh.data.vertices for g in v.groups if g.weight > 0.001}
    report["weights"] = {
        "multi_influence_verts": sum(1 for n in influences if n > 1),
        "max_influences": max(influences, default=0),
        "deform_bones_without_vertices": sorted(set(report["armature"]["deform"]) - populated),
    }

    data = validator_ops._gather_validator_data(mesh)
    result = validator_core.validate(data)
    report["validator"] = {
        "passing": result.is_passing,
        "issues": [str(i) for i in result.issues],
        "tris": data["mesh_tris"],
        "unskinned": data["unskinned_vert_count"],
        "facing_y": data["mesh_facing_y"],
    }

    bpy.context.view_layer.objects.active = mesh
    if not step("export_unity_fbx", lambda: bpy.ops.pipe_sculpt.export_unity_fbx(filepath=args.fbx)):
        return 1
    report["fbx"] = {"path": args.fbx, "bytes": os.path.getsize(args.fbx)}

    # Round trip: what actually reached the file.
    deform = set(report["armature"]["deform"])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=args.fbx)
    fbx_bones, fbx_groups = set(), set()
    for ob in bpy.data.objects:
        if ob.type == 'ARMATURE':
            fbx_bones |= {b.name for b in ob.data.bones}
        elif ob.type == 'MESH':
            fbx_groups |= {g.name for g in ob.vertex_groups}
    report["fbx"].update({
        "bones": sorted(fbx_bones),
        "missing_deform_bones": sorted(deform - fbx_bones),
        "extra_bones": sorted(fbx_bones - deform),
        "vertex_groups": len(fbx_groups),
    })
    ok = result.is_passing and not report["fbx"]["missing_deform_bones"]
    return 0 if ok else 1


def main():
    args = _args()
    if args.fixture:
        args.joints = _write_fixture(args.fixture, args.fixture_drop)
    if args.box_mesh > 0 and not args.obj:
        args.obj = _write_box_mesh(args.joints, args.box_mesh)
    report = {"joints": args.joints, "obj": args.obj, "steps": [], "notes": []}
    try:
        code = _run(args, report)
    except Exception as e:  # report the failure instead of a bare traceback
        report["exception"] = f"{type(e).__name__}: {e}"
        code = 2
    report["exit"] = code
    text = json.dumps(report, indent=1)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    sys.exit(code)


if __name__ == "__main__":
    main()
