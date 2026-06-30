# PipeSculpt

![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Blender](https://img.shields.io/badge/Blender-5.0%2B-orange?logo=blender&logoColor=white)
![Tests](https://img.shields.io/badge/tests-242%20passing-brightgreen)
![Status](https://img.shields.io/badge/version-0.18.0-informational)

**A Blender 5.x addon for the whole sculpt → retopo → UV → paint → rig →
animate → bake → Unity pipeline, driven from one N-panel.**

PipeSculpt collapses the slow, multi-window parts of character work into
preset-driven one-click operators: voxel-sculpt starters, auto + manual
retopology, preset UV unwrap, one-click PBR paint setup, brush-and-spawn
hair, a tag-based auto-rigger for six creature types, a full pose/keying/
loop/clip/layer/onion animation toolkit, and a Unity 6-aware FBX exporter
with a Humanoid validator.

> **New to Blender?** [`MANUAL.md`](MANUAL.md) is a step-by-step tutorial
> from install to Unity export. This README is the reference + overview.

---

## Contents

- [Highlights](#highlights)
- [Requirements](#requirements)
- [Install](#install)
- [The pipeline](#the-pipeline)
- [Features](#features)
  - [Sculpting](#sculpting)
  - [Retopology](#retopology)
  - [UV & texturing](#uv--texturing)
  - [Hair & fur](#hair--fur)
  - [Genesis-Tracked Rigging](#genesis-tracked-rigging-gtr)
  - [Animation](#animation)
  - [Bake & Unity export](#bake--unity-export)
  - [Helpers](#helpers)
- [Development & tests](#development--tests)
- [Project layout](#project-layout)
- [Status](#status)
- [Known limitations](#known-limitations)
- [License & legal](#license--legal)

---

## Highlights

- **Sculpt starters that voxel-fuse into one mesh** — Sphere, Head, Bust,
  Humanoid, Quadruped, Bird, Mech.
- **Genesis-Tracked Rigging (GTR)** — per-vertex bone tags survive voxel
  remesh and retopo, so *Generate Rig* skins six creature types in one click.
- **Auto + manual retopology** — Quadriflow / Decimate, or a guided manual
  retopo helper with Face-Project snap and bone-tag transfer.
- **One-click UV + PBR paint** — preset unwrap, checker/stretch diagnostics,
  texel-density control, and a 4-channel PBR paint setup with correct color
  spaces.
- **Hair & fur** — real-world density presets, native operator spawn, brush
  sculpting, and hair-card conversion for real-time export.
- **A complete animation toolkit** — pose tools (incl. a modal breakdown
  slider), keying helpers, loop authoring (validate/cyclic/bake-in-place),
  an auto-built bone picker, a clip manager, additive NLA layers, and onion
  skinning.
- **Unity 6 export** — axis-mode-aware FBX, a Humanoid bone validator, and an
  axis-calibration round-trip helper.
- **Born-clean engineering** — pure logic split into `*_core.py` modules with
  242 headless `pytest` tests, plus a Blender API-audit harness.

---

## Requirements

- **Blender 5.0+** (developed and verified against 5.1).
- **Unity 6** on the receiving end if you use the FBX export path (optional).
- Python 3.11+ only to run `pack.py` / the test suite outside Blender
  (Blender's bundled Python works too).

---

## Install

1. Build the zip: `python pack.py` → `pipe_sculpt.zip`.
2. Blender → **Edit → Preferences → Get Extensions → Install from Disk** →
   pick the zip.
3. Enable **PipeSculpt**. A "PipeSculpt" tab appears in the 3D viewport
   N-panel.

For development, drop the folder into
`<blender_user_dir>/extensions/user_default/` and restart Blender.

> Upgrading from the old **SculptKit** name? Disable and uninstall it first —
> the extension IDs differ and won't auto-upgrade.

---

## The pipeline

```
 Reference  ─┐
             ▼
 Starter ─► Start Sculpt ─► Add Detail ─► Retopo ─► UV ─► Paint ─► Generate Rig
   mesh        (voxel)       (multires)   (auto/    (smart  (albedo/    (GTR)
                                          manual)   unwrap)  PBR)         │
                                                                          ▼
                            Export FBX ◄─ Bake Maps ◄─ Animate ◄──────────┘
                            (Unity 6)     (normal/AO)  (pose/loop/
                                                        clips/layers)
```

Each step is one button in the N-panel. Steps are independent — skip or
reorder them; GTR bone tags carry through sculpt, remesh, and retopo so you
can rig at any point.

---

## Features

### Sculpting

- **Brush pies** — `Q` (Draw, Clay Strips, Grab, Smooth, Crease Sharp,
  Inflate/Deflate, Flatten/Contrast, Mask) and `Shift+Q` (Clay, Blob, Snake
  Hook, Pinch/Magnify, Scrape/Fill, Fill/Deepen, Elastic Grab, Draw Sharp).
  Slot names are editable in Preferences and survive updates.
- **Starter meshes** — Sphere / Head use pole-free quad-sphere topology; Bust,
  Humanoid, Quadruped, Bird and Mech are clusters of tagged primitives that
  voxel-fuse into one sculptable mesh on Start Sculpt.
- **Workflow pipeline** — pick a preset (Character / Bust+Face / Prop), then
  **Start Sculpt** (voxel base + symmetry, with a finger-safe voxel cap) and
  **Add Detail** (multires steps toward the preset target).
- **Reference images** — drop front/side/top refs in as positioned, render-
  hidden image empties grouped in a References collection; toggle visibility.

### Retopology

- **Auto** — Quadriflow (organic) or Decimate Collapse (props), preset target
  face count, with GTR bone-tag transfer to the new low-poly and cleanup on
  failure.
- **Manual helper** — spawns a retopo mesh with Mirror + Shrinkwrap, locks the
  high-poly, enables the Retopology overlay, sets Face-Project snap (the
  "snap chaos" fix), and on Finish applies + transfers tags + restores state.
  **Relax Geometry** equalises bunched topology without changing silhouette.

### UV & texturing

- **Smart Unwrap** — preset-driven seam marking + Angle-Based unwrap (or Smart
  UV Project for props), average-islands-scale, resolution-aware pack margin.
- **Auto-Seam by Angle**, **Mirror X** (KDTree vertex pairing so L/R share UV
  space), **UV Checker** and **Stretch Heatmap** toggles, and **Texel Density**
  compute/apply (px per metre).
- **Paint setup** — one click for single-channel **albedo** or a full **PBR**
  set (albedo + normal + roughness + metallic) with correct color spaces and
  BSDF wiring (normals through a Normal Map node). **Save Painted Textures**
  writes dirty maps to `<blend_dir>/textures/`. **Stencil from File** and a
  per-project **Quick Color Palette** round it out.

### Hair & fur

- **Presets** with real-world densities — scalp, beard, eyebrow, short/long
  fur, feathers.
- **Setup Hair** binds a Hair Curves object to the mesh surface; **Spawn
  (Preset)** populates strands area-weighted over the surface (pure-Python
  sampling, seeded + capped); **Sculpt/Comb** enters the native Hair Sculpt
  brushes; **→ Hair Cards** converts to a UV'd card mesh for real-time export.

### Genesis-Tracked Rigging (GTR)

Each tagged primitive carries a per-vertex bone-id attribute that survives
voxel remesh and retopo via KDTree transfer. **Generate Rig** reads the tags
and builds the right armature for the starter:

| Starter   | Bones | IK |
|-----------|-------|----|
| Humanoid  | 50+ (root, spine→chest, head, jaw, ears, clavicles, arms, legs, 30 finger phalanges, 4 IK targets + 4 poles) | arms + legs |
| Bust      | 7 (root, spine, neck, head, jaw, ear.L/R) | — |
| Head      | 2 (root, head) | — |
| Quadruped | 17 (spine, neck, head, tail, 4 legs × 3 segments) | — |
| Bird      | 16 (spine, neck, head, beak, tail, 2 wings × 3, 2 legs × 2) | — |
| Mech      | 17 deform + 8 IK control (humanoid topology, no fingers/jaw/ears) | arms + legs |

Generate Rig assigns initial weights from the tags, smooths them, and adds IK
constraints (Humanoid/Mech) with a rest-pose-derived pole angle. Re-running it
rebuilds cleanly — no orphan armatures. The spine is split into **spine + chest**
(Unity Hips→Spine→Chest→Neck→Head) for better torso deformation and mocap
retarget.

### Animation

A set of pose-mode panels for animating GTR rigs toward Unity. Pure logic
lives in `anim_core.py` / `picker_core.py` / `clip_core.py` / `layer_core.py` /
`onion_core.py` (all headless-tested); the operators are thin bpy shells.

- **Pose** — Copy / Paste / Paste-Flipped / **Mirror** (one-click L↔R) /
  **Breakdown Slider** (modal tween machine; also a scriptable `blend` value) /
  Reset to rest.
- **Key** — Key Rig / Key Selected / **Toggle Stepped↔Spline** / Fit Preview
  Range.
- **Loop** — **Validate Loop** (reports the bones that "pop" so loop errors are
  visible in Blender, not Unity), **Make Cyclic** (closes the loop + Cycles
  modifier), **Bake In-Place** (strips root XY for Unity Bake-Into-Pose).
- **Bone Picker** — a clickable, body-shaped grid built automatically from the
  armature's bone names (L/center/R silhouette + Controls + Fingers). Works for
  every rig type; Shift-click extends; All/L/R/None quick-select.
- **Clip Manager** — New / Activate / Duplicate / Rename / Push-to-NLA / Delete
  on the Action+NLA model. Manager clips get a fake user so they survive saves.
- **Additive Layers** — stack recoil / breathing / flinch on a base cycle via
  NLA **COMBINE** tracks, with per-layer blend mode, mute, and a 0–100%
  influence dial.
- **Onion Skin** — translucent ghost copies of the deformed mesh at surrounding
  frames (past=blue, future=warm, fading with distance) in a render-hidden
  collection; auto-switches to Material Preview so the tint shows.

> The animation module is built on a documented spike of Blender 5.1's slotted-
> action API ([`SPIKE_SLOTTED_ACTIONS.md`](SPIKE_SLOTTED_ACTIONS.md)):
> `action.fcurves` was removed in 5.x (F-curves now live in channelbags), and
> layered actions cap at one layer — so clips and additive layers use the
> stable Action + NLA path.

### Bake & Unity export

- **Bake Maps** — Normal + AO (+ optional Position) from high-poly to low-poly
  with a bmesh-built cage, MikkTSpace tangents, 1K–8K preset resolution, PNG
  output to `<blend_dir>/textures/`.
- **Export FBX (Unity)** — two axis modes: **Baked** (default; no Unity tweak,
  best for static/bind-pose) and **Declared** (needs *Bake Axis Conversion = ON*
  in Unity; keeps animation curves aligned). MikkTSpace tangents, deform-only
  bones, optional sticky Triangulate.
- **Validate Unity** — checks the mesh + rig against Unity Humanoid
  requirements (bone names/hierarchy, scale, applied transforms, skin weights,
  UVs) and reports everything to fix *before* you export.
- **Verify Axis Mode** — exports a reference mesh in both axis modes plus a
  Unity 6 round-trip checklist, so you can confirm which mode your importer
  wants.

### Helpers

- **Project Setup Wizard** — scaffolds a `sculpt/ low/ textures/ exports/
  references/` folder layout with a starter `.blend`.
- **Visualisation overlays** — live polycount and mesh-stat readouts.
- **Save reminder** — nudges you to save painted textures before closing.

---

## Development & tests

PipeSculpt follows a "born clean" split adapted from the author's IronCore
conventions:

- **`*_core.py`** — pure Python, **no `bpy`**: all the testable logic (rig
  tables, UV/texel math, hair surface sampling, animation mirror/loop/breakdown
  math, ghost-frame selection, clip naming). Runs headlessly.
- **`*_ops.py`** — thin Blender operator/panel shells over the core.
- **`tests/`** — **242 `pytest` tests** that run without Blender
  (`python -m pytest tests/`); `conftest.py` loads the core modules directly so
  discovery never imports `bpy`.
- **`tests/api_audit.py`** + **`tests/verify_rig_axes.py`** — Blender-headless
  harnesses (`blender --background --python …`) that register the addon, exercise
  every operator, and assert no deprecated/removed API is used. Re-run on each
  Blender update to catch API drift.

```bash
python -m pytest tests/                                   # pure-logic tests
"<blender>" --background --python tests/api_audit.py      # API + operator smoke
"<blender>" --background --python tests/verify_rig_axes.py # rig/skeleton checks
```

---

## Project layout

| File | Role |
|------|------|
| `starters.py` · `workflow_ops.py` | sculpt starters + Start Sculpt / Add Detail / Retopo |
| `manual_retopo_ops.py` | manual retopology helper |
| `uv_ops.py` · `paint_ops.py` · `palette_ops.py` | UV, texture paint, colour palette |
| `hair_core.py` · `hair_ops.py` | hair/fur presets, spawn, cards |
| `rigging.py` | GTR bone tables + Generate Rig |
| `anim_core/ops` · `picker_*` · `clip_*` · `layer_*` · `onion_*` | animation toolkit |
| `bake_ops.py` · `export_ops.py` · `validator_*` | bake, Unity FBX, Humanoid validator |
| `ref_ops.py` · `project_*` · `viz_ops.py` · `handlers.py` | references, project wizard, overlays, save reminder |
| `pack.py` | build `pipe_sculpt.zip` |
| `MANUAL.md` · `SPIKE_SLOTTED_ACTIONS.md` · `ONION_SKIN_TEST.md` | tutorial + design/spike notes |

---

## Status

**v0.18.0** — the full sculpt-to-Unity pipeline plus the complete animation
module (pose/keying/loop, bone picker, clip manager, additive layers, onion
skin) are implemented and verified in Blender 5.1. 242 headless tests pass and
the API audit is clean.

Onion skinning's FK deform-capture is headless-verified; its **IK-driven**
deform-capture is verified only interactively (in Blender's background mode IK
constraints don't propagate to the mesh — a Blender limitation, not a feature
bug). See [`ONION_SKIN_TEST.md`](ONION_SKIN_TEST.md).

---

## Known limitations

- `Q` / `Shift+Q` only override Quick Favorites in **Sculpt** mode; brush slots
  map to Blender 5.x essentials brush names (with an `ALL`-library fallback).
- Initial voxel remesh is skipped in `--background` mode (no sculpt undo stack);
  Subsurf is preserved there so headless tests don't get raw geometry.
- Bake writes only to faces using the per-mesh bake material; multi-slot meshes
  get a warning. Curvature isn't baked (Substance derives a better one from the
  normal map).
- IK pole-angle math is derived for the default rest pose; editing bones before
  Generate Rig can twist it.
- **DECLARED** FBX axis mode ships with the *Verify Axis Mode* round-trip helper
  rather than a baked-in guarantee — confirm it against your importer once.
- Non-humanoid rigs beyond the six built-in types are a single-table edit in
  `rigging.py` (`_RIG_TABLES`).

---

## License & legal

Licensed under **GPL-3.0-or-later** (see [`LICENSE`](LICENSE)) to match
Blender's own license — use, modify, and redistribute under those terms.

The name "PipeSculpt" is also used by an unrelated Unity Asset Store product;
this addon is not affiliated with it. References to *Blender*, *Unity 6*, and
*FBX* are nominative use indicating compatibility only. The "Blender Secrets"
mention in `manual_retopo_ops.py` is editorial attribution for an inspirational
tutorial; no code is copied.
