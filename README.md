# PipeSculpt

A Blender 5.x addon that turns the sculpt-to-Unity pipeline into a few clicks.
Pie menus for brushes, preset-driven workflow, Genesis-Tracked Rigging, manual
retopology helper, and a Unity 6-aware FBX exporter.

> **New to Blender?** Read [`MANUAL.md`](MANUAL.md) for a step-by-step tutorial
> from install to Unity export. This README is the technical reference.

## Features

### Pie menus
- `Q` — primary 8-slot pie (Draw, Clay Strips, Grab, Smooth, Crease Sharp,
  Inflate/Deflate, Flatten/Contrast, Mask)
- `Shift+Q` — secondary 8-slot pie (Clay, Blob, Snake Hook, Pinch/Magnify,
  Scrape/Fill, Fill/Deepen, Elastic Grab, Draw Sharp)
- Slot names are user-editable in addon Preferences. Custom names survive
  addon updates.

### Workflow pipeline
Three presets — **Character**, **Bust+Face**, **Prop** — driving four
sequential operators in the N-panel:

1. **Start Sculpt** — enters sculpt mode, sets voxel size from bbox (with a
   safety cap on Character so fingers don't fuse), applies symmetry, runs
   an initial voxel remesh, and strips the starter's Subsurf modifier so
   the sculpt base doesn't double-detail.
2. **Add Detail** — steps Multires up by one level toward the preset target.
3. **Retopo** — duplicates and runs Quadriflow (organic) or Decimate Collapse
   (props), applies Multires, drops Subsurf, transfers GTR bone tags from
   the high-poly to the new low-poly via KDTree, and cleans up if the
   remesh fails.
4. **Bake Maps** — bakes Normal + AO (and optional Position) from high-poly
   to low-poly with a bmesh-built cage, MikkTSpace tangent normals,
   preset-driven 1K/2K/4K/8K resolution, and PNG output to
   `<blend_dir>/textures/`.

### Starter meshes
- **Sphere** / **Head** — quad-sphere topology (cube + tosphere), no UV-sphere
  poles, multires-friendly.
- **Bust** — head + neck + shoulders block; voxel remesh fuses on Start Sculpt.
- **Humanoid** — 90+ tagged primitives in T-pose: torso/limbs/face anchors/
  fingers (5×3 phalanges per hand). Voxel remesh fuses into one mesh while
  Genesis-Tracked Rigging preserves per-vertex bone tags.

### Genesis-Tracked Rigging (GTR)
Each Humanoid primitive carries a per-vertex bone-id integer attribute. The
attribute survives voxel remesh via KDTree nearest-neighbour transfer, and
**Generate Rig** reads the tags to build:

- Armature with 50+ bones (root, spine, head, jaw, ears, clavicles, arms,
  legs, 30 finger phalanges, 4 IK targets + 4 pole bones)
- Initial vertex weights from the bone tags (one bone per vertex, 1.0)
- Smoothed weights (3 iterations of vertex_group_smooth)
- IK constraints on arms and legs with pole_angle computed from rest-pose
  geometry; bone roll pinned to 0 for predictable IK math

Tags are also transferred through Retopo automatically, so you can sculpt →
retopo → rig in any order.

### Manual retopology helper
For cases where Quadriflow gives bad topology (faces, hard-surface, mech):

- **Setup Manual Retopo** — duplicates a starter plane, adds Mirror +
  Shrinkwrap to the high-poly, locks the high-poly's selectability,
  enables Blender 5.x Retopology overlay, configures Face Project snap
  (the Blender Secrets-style "snap chaos" fix), enters Edit Mode with X
  symmetry on.
- **Relax Geometry** — switches the active retopo mesh into Sculpt Mode
  with the Relax Slide brush activated, so you can paint-equalise bunched
  topology without changing silhouette.
- **Finish Manual Retopo** — applies Mirror + Shrinkwrap, transfers GTR
  bone tags from the paired high-poly via KDTree, hides high-poly, and
  resets snap state.

### Unity 6 FBX export
Wraps Blender's FBX exporter with two selectable axis modes:

- **Baked** (default) — `bake_space_transform=True`, axis -Z/Y. The -90° X
  rotation is baked into mesh data; the default Unity 6 importer reads the
  FBX correctly with no tweak. Best for static / bind-pose exports.
- **Declared** — `bake_space_transform=False`, axis -Z/Y. Mesh stays in Z-up;
  FBX header declares Y-up. Unity 6 must have **Bake Axis Conversion = ON**
  in the model importer. Animation curves stay aligned with the Blender
  source.

Constants: MikkTSpace tangents (`mesh_smooth_type='FACE'`, `use_tspace=True`),
SRGB vertex colors, `use_armature_deform_only=True` (control bones stripped),
no leaf bones, optional sticky Triangulate modifier so Unity doesn't
re-triangulate against the bake.

## Install (Blender 5.0+)

1. Run `python pack.py` to build `pipe_sculpt.zip`.
2. Blender → Edit → Preferences → Get Extensions → Install from Disk → pick
   the zip.
3. Enable "PipeSculpt".

For development, drop the folder into
`<blender_user_dir>/extensions/user_default/` and restart Blender.

## Status

v0.9.0 — full bug-fix pass after a two-round audit. All P0/P1/P2 issues
in the audit are addressed; remaining P3 items (unverified IK pole-angle
math, non-humanoid feature gap, DECLARED axis mode round-trip) are
documented in code as known limitations.

Verified end-to-end in Blender 5.1 background mode (Start → Add Detail
→ Retopo → Bake → Generate Rig).

This release renames the addon from "SculptKit" to "PipeSculpt" to avoid
collision with an unrelated Unity Asset Store product. Old SculptKit
installs must be disabled and uninstalled in Blender before installing
PipeSculpt — they have different extension IDs and won't auto-upgrade.

## License & legal

Licensed under **GPL-3.0-or-later** (see [`LICENSE`](LICENSE)) to match Blender's
own license. You may use, modify, and redistribute PipeSculpt under those terms.

The name "PipeSculpt" is also used by an unrelated Unity Asset Store product;
PipeSculpt (this addon) is not affiliated with that or any other product. If
you fork and publish, consider renaming to avoid confusion.

References to *Blender*, *Unity 6*, and *FBX* are nominative use under their
respective trademark holders' fair-use guidelines and indicate compatibility
only. The "Blender Secrets" reference in `manual_retopo_ops.py` is editorial
attribution for an inspirational tutorial; no code is copied.

## Known limitations

- Q / Shift+Q only override Quick Favorites in **Sculpt** mode.
- Brush slot names map to Blender 5.x `essentials_brushes-mesh_sculpt.blend`
  asset names. The pie falls back to the `ALL` asset library if a brush
  isn't found in `ESSENTIALS`.
- Initial voxel remesh is skipped in `bpy.app.background` mode (sculpt
  undo stack isn't initialised without UI). Subsurf is preserved in this
  case so background tests don't end up with raw low-poly geometry.
- Multi-slot low-poly meshes only get bake output on faces using
  `<low.name>_BakeMat` — the bake operator warns when other slots are
  present. Each baked mesh gets its own per-mesh bake material so the
  active texture preview doesn't flip when you re-bake another mesh.
- Curvature is not baked: Cycles has no native pass and Substance Painter
  generates a better one client-side from the baked normal.
- **GTR is humanoid-only.** Bust/Head starters get no bones; quadrupeds
  / birds / mech need a different bone definition table (not yet shipped).
- **IK pole-angle math is empirically derived** for the hardcoded HUMANOID
  rest pose. Editing bones manually before Generate Rig can twist the IK
  rest pose. Verified for default Humanoid; not for custom edits.
- **DECLARED FBX axis mode is not yet round-trip verified in Unity 6**
  — use BAKED (the default) until verified.

## Workflow

1. **Starter Meshes** panel → pick **Humanoid** (or another starter).
2. **Workflow Pipeline** panel → preset (Character/Bust/Prop) → **Start Sculpt**.
3. Sculpt with `Q` / `Shift+Q` pies. Click **Add Detail** for multires steps.
4. **Retopo** (auto: Quadriflow / Decimate) **or** **Setup Manual Retopo**
   (when auto-retopo gives poor topology) → produces a low-poly with GTR
   tags carried through.
5. **Generate Rig** (if Humanoid) → armature + IK + initial weights.
6. **Bake Maps** → PNGs in `<blend_dir>/textures/`.
7. **Export FBX (Unity)** → drop the FBX + textures into Unity 6.

For a beginner-friendly walkthrough with screenshots-style explanations,
see [`MANUAL.md`](MANUAL.md).
