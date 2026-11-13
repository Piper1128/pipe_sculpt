"""Marv -> Unity in one call: mv-cli body + joints, then marv_to_unity, then a manifest.

The chain this replaces was typed by hand five times on 2026-11-13 (trunk,
arms-out, shoulder, viewmodel x2): Marv's mv-cli writes joints.json and the
body OBJ, tools/marv_to_unity.py rigs and exports it, and the md5 of every
file is what says which body went into Unity. No bpy here: the Blender step
runs in its own process.

    python tools/marv_pipeline.py OUT_DIR --mv-cli PATH [--sex male|female ...]
        [--height MM] [--pose "arms 12 legs 20"] [--split-viewmodel]
        (--blender PATH | --bpy-python PATH)
        [--marv-repo DIR] [--require-quantity NAME] [--expect-obj-md5 SEX=MD5]
        [--name STEM]

Per sex it writes STEM-SEX.json, STEM-SEX.obj, STEM-SEX.fbx, STEM-SEX.report.json
and one manifest.json for the run (commands, md5s, the mv-cli binary's path
and age, the commits of both repos when they can be read).

The body is the Marv lab's (lab/experiments/humanoid_exterior.py and
humanoid_trunk.py at marv 204e909): `joints`, `exterior`, `mesh` on a cube
whose faces miss round millimetres, `collapse` at a 0.2 mm floor, `obj`.

--require-quantity (default shoulder_joint_centre_below_acromion, de Leva's
shoulder, marv 50149b0) refuses a body whose joints.json lacks that quantity:
it asks the binary what it computes, so a build from before the change is
refused whatever its file date. A first version compared the binary's mtime
with the commit time instead, and refused the cloud's mv-cli, built from the
working tree 12 s before 50149b0 was committed; the date says nothing about
what was compiled. --marv-repo only records the commit in the manifest.

Exit 0 = every body built and exported; 1 = mv-cli refused, an md5 did not
match, the required quantity is missing, or marv_to_unity failed; 2 = could not run (no
mv-cli, no Blender, unreadable arguments). Nothing that could not run is
reported as a result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

_TOOLS = os.path.dirname(os.path.abspath(__file__))
_ADDON_ROOT = os.path.dirname(_TOOLS)

# ANSUR II (75) Stature means, the scale-1 bodies the Marv lab builds
# (marv lab/experiments/humanoid_exterior.py STATURE, 204e909).
STATURE = {"male": 1756.2, "female": 1628.5}
DEPTH = 8          # the certificate's depth on a cube: cell = side / 2**DEPTH
FLOOR_MM = 0.2     # collapse floor, H049/H052's
NODE_BUDGET = 1000000
# marv 50149b0 (H063): joints.json carries this quantity only from that change on
DEFAULT_REQUIRED_QUANTITY = "shoulder_joint_centre_below_acromion"


def mesh_box(height_mm):
    """The Marv lab's mesh cube and cell for a body of height_mm.

    Copied from marv lab/experiments/humanoid_exterior.py mesh_box (204e909):
    a cube from just under the floor to above the vertex, offsets chosen so no
    face or grid plane falls on a round millimetre (mv-cli refuses those with
    corner_sign_undecided).
    """
    side = height_mm + 24.33
    y0 = -3.13
    box = (-side / 2 - 1.54, side / 2 - 1.54, y0, y0 + side,
           -side / 2 + 30.41, side / 2 + 30.41)
    return box, side / 2 ** DEPTH * 1.01


def parse_pose(text):
    """'' or 'arms A [legs L]' / 'legs L' -> normalised mv-cli suffix.

    Raises ValueError on anything else, so a typo is refused here and not
    passed to mv-cli as part of a verb line.
    """
    tokens = text.split()
    if not tokens:
        return ""
    if len(tokens) % 2:
        raise ValueError("pose needs pairs: arms DEG / legs DEG, got %r" % text)
    seen = {}
    for key, val in zip(tokens[::2], tokens[1::2]):
        if key not in ("arms", "legs") or key in seen:
            raise ValueError("pose key %r is not arms/legs or repeats" % key)
        seen[key] = float(val)
    return " ".join("%s %r" % (k, seen[k]) for k in ("arms", "legs") if k in seen)


def marv_script(sex, height_mm, pose, joints_path, obj_path):
    """The mv-cli script that writes joints_path and obj_path."""
    if sex not in STATURE:
        raise ValueError("sex must be male or female, got %r" % sex)
    box, cell = mesh_box(height_mm)
    opt = (" " + pose) if pose else ""
    return ("joints %s %s %r%s\n"
            "exterior B %s %r%s\n"
            "mesh M B %s %r %d\n"
            "collapse C M %r\n"
            "obj C %s\n"
            % (joints_path, sex, height_mm, opt, sex, height_mm, opt,
               " ".join("%r" % x for x in box), cell, NODE_BUDGET,
               FLOOR_MM, obj_path))


def blender_cmd(blender, script, script_args):
    """Blender headless command line. --python-exit-code must precede
    --python, or Blender exits 0 when the script raises."""
    return [blender, "-b", "--factory-startup", "--python-exit-code", "1",
            "--python", script, "--"] + list(script_args)


def to_unity_args(joints, fbx, obj, report, split):
    a = [joints, fbx, "--obj", obj, "--report", report]
    if split:
        a.append("--split-viewmodel")
    return a


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def has_quantity(joints_doc, name):
    """True when the joints document's quantities name `name`."""
    return any(q.get("name") == name for q in joints_doc.get("quantities", []))


def _args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("out")
    p.add_argument("--mv-cli", default=os.environ.get("MARV_CLI", ""))
    p.add_argument("--sex", action="append", choices=sorted(STATURE))
    p.add_argument("--height", type=float, default=0.0,
                   help="mm; default the sex's ANSUR II stature mean")
    p.add_argument("--pose", default="")
    p.add_argument("--split-viewmodel", action="store_true")
    p.add_argument("--blender", default="")
    p.add_argument("--bpy-python", default="",
                   help="a Python with the bpy module, instead of --blender")
    p.add_argument("--marv-repo", default="")
    p.add_argument("--require-quantity", default=DEFAULT_REQUIRED_QUANTITY,
                   help="refuse a joints.json without it; '' to skip")
    p.add_argument("--expect-obj-md5", action="append", default=[],
                   help="SEX=MD5, refuse when that body's OBJ differs")
    p.add_argument("--name", default="marv")
    return p.parse_args(argv)


def main(argv=None):
    try:
        a = _args(sys.argv[1:] if argv is None else argv)
        pose = parse_pose(a.pose)
        expect = dict(e.split("=", 1) for e in a.expect_obj_md5)
    except (ValueError, SystemExit) as e:
        print("marv_pipeline: could not run: %s" % e)
        return 2
    sexes = a.sex or ["male"]
    if not a.mv_cli or not os.path.isfile(a.mv_cli):
        print("marv_pipeline: could not run: no mv-cli at %r" % a.mv_cli)
        return 2
    if bool(a.blender) == bool(a.bpy_python):
        print("marv_pipeline: could not run: give exactly one of --blender, --bpy-python")
        return 2
    runner = a.blender or a.bpy_python
    if not os.path.isfile(runner):
        print("marv_pipeline: could not run: no Blender/Python at %r" % runner)
        return 2

    os.makedirs(a.out, exist_ok=True)
    cli_mtime = os.path.getmtime(a.mv_cli)
    manifest = {
        "tool": "pipe_sculpt tools/marv_pipeline.py",
        "pipe_sculpt_commit": _git(_ADDON_ROOT, "rev-parse", "HEAD"),
        "mv_cli": {"path": os.path.abspath(a.mv_cli), "md5": md5(a.mv_cli),
                   "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(cli_mtime))},
        "marv_commit": None, "pose": pose, "split_viewmodel": a.split_viewmodel,
        "runner": os.path.abspath(runner), "bodies": {}, "verdict": None,
    }

    def finish(code, why):
        manifest["verdict"] = {"exit": code, "why": why}
        with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
        print("marv_pipeline: exit %d -- %s" % (code, why))
        return code

    if a.marv_repo:
        manifest["marv_commit"] = _git(a.marv_repo, "rev-parse", "HEAD")

    to_unity = os.path.join(_TOOLS, "marv_to_unity.py")
    for sex in sexes:
        h = a.height or STATURE[sex]
        stem = os.path.join(a.out, "%s-%s" % (a.name, sex)).replace(os.sep, "/")
        joints, obj, fbx, rep = (stem + ext for ext in (".json", ".obj", ".fbx", ".report.json"))
        script = marv_script(sex, h, pose, joints, obj)
        body = {"height_mm": h, "mv_cli_script": script}
        manifest["bodies"][sex] = body
        p = subprocess.run([a.mv_cli, "run", "-"], input=script.encode(),
                           capture_output=True, timeout=3600)
        try:
            d = json.loads(p.stdout.decode("utf-8", "replace"))
        except ValueError:
            return finish(1, "%s: mv-cli exit %d, no JSON: %s"
                          % (sex, p.returncode, p.stderr.decode(errors="replace")[-400:]))
        if not d.get("ok"):
            return finish(1, "%s: mv-cli refused: %s" % (sex, json.dumps(d.get("refusal"))))
        body["obj_md5"], body["joints_md5"] = md5(obj), md5(joints)
        with open(joints, encoding="utf-8") as f:
            jdoc = json.load(f)
        if a.require_quantity and not has_quantity(jdoc, a.require_quantity):
            return finish(1, "%s: joints.json has no %r: mv-cli predates that change, rebuild it"
                          % (sex, a.require_quantity))
        if sex in expect and expect[sex] != body["obj_md5"]:
            return finish(1, "%s: OBJ md5 %s, expected %s" % (sex, body["obj_md5"], expect[sex]))

        args = to_unity_args(joints, fbx, obj, rep, a.split_viewmodel)
        cmd = (blender_cmd(a.blender, to_unity, args) if a.blender
               else [a.bpy_python, to_unity] + args)
        body["to_unity_cmd"] = cmd
        q = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        body["to_unity_exit"] = q.returncode
        if q.returncode != 0 or not os.path.isfile(fbx):
            body["to_unity_tail"] = (q.stdout + q.stderr)[-2000:]
            return finish(1, "%s: marv_to_unity exit %d" % (sex, q.returncode))
        body["fbx_md5"] = md5(fbx)
        with open(rep, encoding="utf-8") as f:
            r = json.load(f)
        body["validator_passing"] = r.get("validator", {}).get("passing")
        body["viewmodel_meshes"] = r.get("viewmodel_meshes")
    return finish(0, "%d bod%s built" % (len(sexes), "y" if len(sexes) == 1 else "ies"))


if __name__ == "__main__":
    sys.exit(main())
