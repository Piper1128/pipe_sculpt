"""Headless verifikation af GTR-skelettets roll, lokale akser og spine-kæde.

Kør:
    "<sti>\\blender.exe" --background --python tests\\verify_rig_axes.py

Bygger HUMANOID-armaturet med præcis samme logik som Generate Rig (roll=0),
og rapporterer FAKTISKE tal så vi kan be- eller afkræfte review-fundene:

  Fund A — roll=0 og lokale akser pr. bend-bone
  Fund B — spine-kædens længde (pelvis..head)
  Fund C — hvilke kind='C' bones der vil forurene en FBX-export

Scriptet rører ikke en .blend-fil og gemmer intet — ren rapport til stdout.
Det importerer bone-tabellerne direkte fra addon'ets rigging.py, så det
tester de RIGTIGE data, ikke en kopi.
"""
import os
import sys
import math

import bpy
import mathutils

# Gør addon-roden importérbar (scriptet ligger i tests/).
_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ADDON_ROOT not in sys.path:
    sys.path.insert(0, _ADDON_ROOT)

import rigging  # noqa: E402


SEP = "=" * 70


def _fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _build_humanoid_armature():
    """Replikér Generate Rig's edit-bone-bygning (inkl. roll=0) headless."""
    bones, _ik, origin = rigging._RIG_TABLES["HUMANOID"]
    serialized = rigging._serialize_bones(bones, origin)

    arm_data = bpy.data.armatures.new("VerifyArm")
    arm_obj = bpy.data.objects.new("VerifyArm", arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    by_id = {}
    for b in serialized:
        e = eb.new(b["id"])
        e.head = b["head"]
        e.tail = b["tail"]
        e.use_deform = (b["kind"] == "D")
        e.roll = 0.0  # samme som rigging.py:661
        by_id[b["id"]] = e
    for b in serialized:
        if b["parent"]:
            by_id[b["id"]].parent = by_id[b["parent"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj, serialized


def _fmt(v):
    return f"({v.x:+.3f}, {v.y:+.3f}, {v.z:+.3f})"


def _report_axes(arm_obj):
    print(SEP)
    print("FUND A — roll og lokale akser (rest-pose)")
    print(SEP)
    print("Bonen peger altid langs lokal Y (head->tail). roll bestemmer X/Z.")
    print("For en ren bend-bone vil vi at bøje-aksen er EN af de lokale akser.\n")

    watch = ["spine", "forearm.L", "lower_leg.L", "hand.L",
             "index_02.L", "upper_arm.L"]
    for name in watch:
        bone = arm_obj.data.bones.get(name)
        if bone is None:
            print(f"  {name:<14} (mangler)")
            continue
        m = bone.matrix_local.to_3x3()
        x_axis = m.col[0]
        y_axis = m.col[1]
        z_axis = m.col[2]
        # roll aflæses i edit-mode; her viser vi i stedet akserne direkte.
        print(f"  {name:<14} Y(dir)={_fmt(y_axis)}  "
              f"X={_fmt(x_axis)}  Z={_fmt(z_axis)}")
    print("\nTolkning:")
    print("  - forearm.L/lower_leg.L: tjek om en lokal akse ~ verdens akse")
    print("    som bend sker om. Hvis ja -> ren enkelt-akse-rotation (godt).")
    print("  - For Unity HUMANOID er roll i praksis irrelevant (muscle space).")
    print("    For GENERIC (quad/bird/mech) betyder det her noget.\n")


def _report_spine(serialized):
    print(SEP)
    print("FUND B — spine-kæde (pelvis..head)")
    print(SEP)
    chain = [b["id"] for b in serialized
             if b["id"] in ("pelvis", "spine", "chest", "neck", "head")]
    spine_segments = [b for b in serialized
                      if b["id"] in ("spine", "chest", "spine_01",
                                     "spine_02", "spine_03")]
    print(f"  Kæde: {' -> '.join(chain)}")
    print(f"  Antal spine-segmenter mellem pelvis og neck: {len(spine_segments)}")
    if len(spine_segments) <= 1:
        print("  >> BEKRÆFTET: kun 1 spine-bone. Unity Humanoid importerer fint")
        print("     (Chest optional), men 3-spine mocap komprimeres ved retarget,")
        print("     og torso-deformation knækker om ét punkt. Se review pkt. 3.")
    else:
        print("  >> Flere spine-segmenter til stede — Fund B er adresseret.")
    print()


def _report_control_bones(serialized):
    print(SEP)
    print("FUND C — kind='C' bones der eksporteres til FBX medmindre de filtreres")
    print(SEP)
    ctrl = [b["id"] for b in serialized if b["kind"] == "C"]
    deform = [b["id"] for b in serialized if b["kind"] == "D"]
    print(f"  Deform-bones (skal til Unity): {len(deform)}")
    print(f"  Control/IK-bones (BØR filtreres fra FBX): {len(ctrl)}")
    print(f"    -> {', '.join(ctrl)}")
    print("  Anbefaling: deform-only export-filter (drop kind='C').\n")


def _report_table_consistency():
    print(SEP)
    print("BONE-TABLE KONSISTENS — alle rig-typer")
    print(SEP)
    problems = 0
    for rig_type, (bones, ik, _origin) in rigging._RIG_TABLES.items():
        ids = {b[0] for b in bones}
        deform_ids = {b[0] for b in bones if b[4] == 'D'}
        # 1. Every parent reference must resolve to a real bone in the table
        for b in bones:
            parent = b[1]
            if parent is not None and parent not in ids:
                print(f"  [{rig_type}] BONE '{b[0]}' parent '{parent}' MANGLER i tabellen")
                problems += 1
        # 2. Every deform bone must be in DEFORM_BONE_NAMES (else no vertex group)
        for name in deform_ids:
            if name not in rigging.BONE_NAME_TO_INDEX:
                print(f"  [{rig_type}] DEFORM bone '{name}' mangler i DEFORM_BONE_NAMES")
                problems += 1
        # 3. Every IK spec must reference real bones
        for spec in ik:
            for ref in (spec[0], spec[1], spec[2]):
                if ref not in ids:
                    print(f"  [{rig_type}] IK ref '{ref}' findes ikke i bone-tabellen")
                    problems += 1
    if problems == 0:
        print("  >> Alle rig-tabeller konsistente: parents findes, deform-bones")
        print("     er i DEFORM_BONE_NAMES, IK-specs peger på rigtige bones.")
    else:
        print(f"  >> {problems} KONSISTENS-PROBLEM(ER) fundet — se ovenfor.")
    print()


def _report_chest(serialized):
    print(SEP)
    print("FUND B-FIX — chest-bone til stede + spine-kæde-længde")
    print(SEP)
    chain = [b["id"] for b in serialized
             if b["id"] in ("pelvis", "spine", "chest", "neck", "head")]
    spine_segs = [b for b in serialized if b["id"] in ("spine", "chest")]
    print(f"  Kæde: {' -> '.join(chain)}")
    print(f"  Spine-segmenter (spine+chest): {len(spine_segs)}")
    # Confirm clavicles + neck now parent to chest
    for name in ("neck", "clavicle.L", "clavicle.R"):
        b = next((x for x in serialized if x["id"] == name), None)
        if b is not None:
            print(f"  {name:<12} parent = {b['parent']}")
    print()


def main():
    print("\n" + SEP)
    print("GTR RIG VERIFICATION — Blender", bpy.app.version_string)
    print(SEP + "\n")

    _fresh_scene()
    arm_obj, serialized = _build_humanoid_armature()

    _report_axes(arm_obj)
    _report_spine(serialized)
    _report_chest(serialized)
    _report_control_bones(serialized)
    _report_table_consistency()

    print(SEP)
    print("Færdig. Sammenhold tallene med GTR_RIG_REVIEW.md fund A/B/C.")
    print(SEP)


if __name__ == "__main__":
    main()
