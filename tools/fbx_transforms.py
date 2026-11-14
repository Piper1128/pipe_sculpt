"""Read an FBX's unit and every Model's local transform, without Blender's importer.

    python tools/fbx_transforms.py FILE.fbx [--json] [--require-unit-scale]

Prints GlobalSettings' UnitScaleFactor (cm per file unit) and, per Model node, its type,
Lcl Translation / Rotation / Scaling, PreRotation and its parent. These are the numbers
Unity's importer starts from: an armature whose Lcl Scaling is 100 under a file in
centimetres comes into Unity with localScale 100 (GHT lab/data/0064, 2026-11-14).

The FBX binary is read with Blender's own parser (io_scene_fbx/parse_fbx.py): run it
under Blender's Python or a Python with pip's bpy (the package's __init__ imports bpy);
--parser-dir names the io_scene_fbx directory when it cannot be found from bpy.

--require-unit-scale exits 1 unless every Model's Lcl Scaling is 1 (to 1e-5), 0 when it
is, 2 when the file cannot be read. It is the check marv_pipeline runs after export. A
rotated top-level armature Null is printed with its children, not judged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SCALE_TOL = 1e-5  # float32 in the file: a bone reads 1.0000017
ROT_TOL = 1e-4


def _parser(parser_dir):
    dirs = [parser_dir] if parser_dir else []
    try:
        import bpy  # noqa: F401  -- only to find the bundled addon directory
        # bpy is <version>/scripts/modules/bpy/__init__.py, in Blender and in pip's bpy
        scripts = os.path.dirname(os.path.dirname(os.path.dirname(bpy.__file__)))
        dirs.append(os.path.join(scripts, "addons_core", "io_scene_fbx"))
    except ImportError:
        pass
    for d in dirs:
        if os.path.isfile(os.path.join(d, "parse_fbx.py")):
            # parse_fbx imports its siblings relatively, so it is loaded as part of
            # the io_scene_fbx package
            sys.path.insert(0, os.path.dirname(d))
            from io_scene_fbx import parse_fbx  # noqa: E402
            return parse_fbx
    return None


def _props(elem):
    out = {}
    for c in elem.elems:
        if c.id == b"Properties70":
            for p in c.elems:
                if p.id == b"P":
                    name = p.props[0].decode("utf-8", "replace")
                    vals = [v for v in p.props[4:]]
                    out[name] = vals[0] if len(vals) == 1 else vals
    return out


def _find(elem, name):
    for c in elem.elems:
        if c.id == name:
            return c
    return None


def read(path, parser_dir=""):
    pf = _parser(parser_dir)
    if pf is None:
        raise RuntimeError("no parse_fbx.py (give --parser-dir or a Python with bpy)")
    root, version = pf.parse(path)
    gs = _find(root, b"GlobalSettings")
    unit = _props(gs).get("UnitScaleFactor") if gs is not None else None
    models = {}
    objs = _find(root, b"Objects")
    for e in objs.elems if objs is not None else []:
        if e.id != b"Model":
            continue
        uid = e.props[0]
        name = e.props[1].split(b"\x00\x01")[0].decode("utf-8", "replace")
        kind = e.props[2].decode("utf-8", "replace")
        p = _props(e)
        models[uid] = {
            "name": name, "type": kind,
            "translation": list(p.get("Lcl Translation", [0.0, 0.0, 0.0])),
            "rotation": list(p.get("Lcl Rotation", [0.0, 0.0, 0.0])),
            "scaling": list(p.get("Lcl Scaling", [1.0, 1.0, 1.0])),
            "prerotation": list(p.get("PreRotation", [0.0, 0.0, 0.0])),
            "parent": None,
        }
    conns = _find(root, b"Connections")
    for c in conns.elems if conns is not None else []:
        # A bone is also connected to its skin cluster (child bone, parent Deformer): only
        # a Model parent is the hierarchy
        if (c.id == b"C" and c.props[0] == b"OO" and c.props[1] in models
                and c.props[2] in models):
            models[c.props[1]]["parent"] = models[c.props[2]]["name"]
    return {"version": version, "unit_scale_factor": unit,
            "models": sorted(models.values(), key=lambda m: m["name"])}


def faults(doc):
    """Every Model whose Lcl Scaling is not 1: what comes into Unity with a scale."""
    return ["%s (%s): Lcl Scaling %s" % (m["name"], m["type"], m["scaling"])
            for m in doc["models"] if any(abs(x - 1.0) > SCALE_TOL for x in m["scaling"])]


def turned_tops(doc):
    """Top-level Null/LimbNode Models with a rotation, and their children's rotations.

    Blender writes an armature's axis conversion as a -90 deg x on the armature's Null
    and +90 on its root bone; Unity shows them as 270 and 90 (GHT lab/data/0064). They
    are reported, not judged: whether Unity needs them gone is measured there.
    """
    out = []
    for m in doc["models"]:
        if m["type"] in ("Null", "LimbNode") and m["parent"] is None and any(
                abs(r) > ROT_TOL for r in m["rotation"]):
            kids = [(k["name"], k["rotation"]) for k in doc["models"] if k["parent"] == m["name"]]
            out.append((m["name"], m["rotation"], kids))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("fbx")
    p.add_argument("--json", action="store_true")
    p.add_argument("--require-unit-scale", action="store_true")
    p.add_argument("--parser-dir", default="")
    if argv is None:
        # under Blender (blender -b --python this.py -- FILE ...) the script's own
        # arguments follow the "--"
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    a = p.parse_args(argv)
    try:
        doc = read(a.fbx, a.parser_dir)
    except (OSError, RuntimeError, Exception) as e:  # an unreadable file is not a verdict
        print("fbx_transforms: could not run: %s" % e)
        return 2
    if a.json:
        print(json.dumps(doc, indent=1))
    else:
        print("UnitScaleFactor %r (cm per unit), FBX %s" % (doc["unit_scale_factor"],
                                                           doc["version"]))
        for m in doc["models"]:
            print("  %-40s %-9s parent %-28s rot %s scale %s" % (
                m["name"], m["type"], m["parent"], [round(x, 4) for x in m["rotation"]],
                [round(x, 6) for x in m["scaling"]]))
    if a.require_unit_scale:
        for name, rot, kids in turned_tops(doc):
            print("turned top: %s rot %s; children %s" % (
                name, [round(x, 4) for x in rot],
                ", ".join("%s %s" % (k, [round(x, 4) for x in r]) for k, r in kids)))
        bad = faults(doc)
        for b in bad:
            print("NOT UNIT: " + b)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
