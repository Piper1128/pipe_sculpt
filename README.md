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
Each tagged primitive carries a per-vertex bone-id integer attribute. The
attribute survives voxel remesh via KDTree nearest-neighbour transfer, and
**Generate Rig** reads the tags to build the rig appropriate for the starter:

| Starter | Bones | IK |
|---|---|---|
| Humanoid | 50+ (root, spine, head, jaw, ears, clavicles, arms, legs, 30 finger phalanges, 4 IK targets + 4 pole bones) | arms + legs |
| Bust | 7 (root, spine, neck, head, jaw, ear.L, ear.R) | none |
| Head | 2 (root, head) | none |
| Quadruped | 17 (spine, neck, head, tail, 4 legs × 3 segments) | none |
| Bird | 16 (spine, neck, head, beak, tail, 2 wings × 3 segments, 2 legs × 2 segments) | none |
| Mech | 17 deform + 8 IK control (humanoid topology, no fingers/jaw/ears) | arms + legs |

Generate Rig produces:
- Armature with the bones above, parented to mesh
- Initial vertex weights from the bone tags (one bone per vertex, 1.0)
- Smoothed weights (3 iterations of vertex_group_smooth)
- IK constraints with pole_angle computed from rest-pose geometry; bone
  roll pinned to 0 for predictable IK math (Humanoid only)

Tags are also transferred through Retopo automatically, so you can sculpt →
retopo → rig in any order. Re-running Generate Rig nukes the prior armature
and rebuilds — no orphan rigs left behind.

### UV & Paint
Removes the 5+ click texture-paint setup that loses Blender beginners.

**UV operators:**
- **Smart Unwrap** — preset-driven (Character / Hardsurface / Prop). Auto-marks
  sharp edges as seams, runs Angle-Based unwrap (or Smart UV Project for
  props), averages island scale for uniform texel density, packs with
  resolution-aware margin.
- **Auto-Seam by Angle** — slider for the dihedral threshold; marks every
  edge sharper than that as a seam.
- **Mirror X** — for X-symmetric meshes: copies UVs from +X half to -X half
  via KDTree vertex pairing. Both halves overlap in UV space → texture
  painted on one side appears on both.
- **UV Checker Toggle** — adds/removes a procedural checker material so
  beginners can see stretching at a glance. Auto-switches to Material Preview.
- **Stretch Heatmap Toggle** — flips the UV editor's Display Stretch overlay
  with a clear hint if no UV editor is open.
- **Texel Density** — compute or apply px/m. Default 1024 px/m matches AAA
  character standards.

**Paint operators:**
- **Setup Paint Mode** — single-channel albedo. Creates `<name>_albedo`
  image, wires to a per-mesh paint material's BSDF Base Color, sets it as
  the active canvas, switches to Texture Paint mode.
- **Setup PBR Channels** — same but for albedo + normal + roughness +
  metallic, all with correct color spaces (sRGB for albedo, Non-Color for
  the rest) and BSDF wiring (normals through a Normal Map node for tangent-
  space reading).
- **Save Painted Textures** — saves all dirty paint textures on the active
  mesh to `<blend_dir>/textures/`. Reports save / overwrite / skip counts.

### Animation (Phase 1)
An "Animate" panel (pose-mode only) with pose / keying / loop quick-tools
for animating GTR rigs toward Unity export. Pure logic in `anim_core.py`
(headless-tested), thin operators in `anim_ops.py`.

- **Pose:** Copy / Paste / Paste-Flipped / Mirror (one-click L↔R) / Breakdown
  Slider / Reset to rest. Mirror uses `(w, x, -y, -z)` quaternion + negated-X
  location, verified correct for GTR's mirror-symmetric `.L`/`.R` bones. The
  Breakdown Slider is a modal tween machine — drag to blend selected bones
  between their previous and next keys (also has a scriptable `blend` value).
- **Key:** Key Whole Rig / Key Selected / Toggle Stepped↔Spline (blocking vs
  spline interpolation) / Fit Preview Range.
- **Loop:** Validate Loop (diffs first vs last frame, reports the bones that
  "pop" — loop errors visible in Blender, not Unity), Make Cyclic (closes the
  loop + Cycles modifier), Bake In-Place (strips root XY translation for Unity
  Bake-Into-Pose; keeps Z).

Built on a spike of Blender 5.1's slotted-action API: `action.fcurves` was
removed in 5.x, so F-curves are accessed via channelbags
(`action.layers[].strips[].channelbag(slot).fcurves`) with a legacy fallback.

**Bone Picker** (pose-mode panel) — a clickable, body-shaped grid built
automatically from the armature's bone names. No per-rig setup: bones are
classified by name into a left/center/right silhouette with separate Controls
and Fingers sub-grids. Click selects a pose bone, Shift-click extends; quick
All/L/R/None buttons. Works for humanoid / quadruped / bird / mech rigs.

**Clip Manager** (Clips panel) — manage a character's animation clips without
the dope-sheet action editor. New / Activate / Duplicate / Rename / Push-to-NLA
/ Delete, with the active clip highlighted and the NLA stash count shown.
Built on the Action + NLA model (a [spike](SPIKE_SLOTTED_ACTIONS.md) confirmed
Blender 5.1's layered actions cap at one layer, so clips stay Actions).
Manager-created clips get a fake user so they survive a save while inactive.

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
- **All built-in starter types now produce rigs** (Humanoid, Bust, Head,
  Quadruped, Bird, Mech). Adding more (e.g. dragon, snake, fish) is a
  single-table edit in `rigging.py` since `_RIG_TABLES` dispatches via
  rig type id.
- **IK pole-angle math is empirically derived** for the hardcoded HUMANOID
  rest pose. Editing bones manually before Generate Rig can twist the IK
  rest pose. Verified for default Humanoid; not for custom edits.
- **DECLARED FBX axis mode** ships with a verification helper:
  *Verify Axis Mode* button under Export writes both modes plus a
  Unity 6 test procedure to a folder. Run it once, follow the README,
  and you'll know whether DECLARED is safe for your importer settings.

## Workflow

1. **Starter Meshes** panel → pick **Humanoid** (or another starter).
2. **Workflow Pipeline** panel → preset (Character/Bust/Prop) → **Start Sculpt**.
3. Sculpt with `Q` / `Shift+Q` pies. Click **Add Detail** for multires steps.
4. **Retopo** (auto: Quadriflow / Decimate) **or** **Setup Manual Retopo**
   (when auto-retopo gives poor topology) → produces a low-poly with GTR
   tags carried through.
5. **UV → Smart Unwrap** → preset-driven UV layout with auto-seaming and
   pack-islands. Optional: **Mirror X** for symmetric characters,
   **Checker** to verify stretch, **Texel Density** to set px/m.
6. **Setup Paint Mode** (or **Setup PBR Channels** for full PBR) → single-
   click texture paint setup. Paint, then **Save Painted Textures**.
7. **Generate Rig** (Humanoid/Bust/Quadruped/Bird/Mech) → armature + weights.
8. **Bake Maps** → PNGs in `<blend_dir>/textures/`.
9. **Export FBX (Unity)** → drop the FBX + textures into Unity 6.

For a beginner-friendly walkthrough with screenshots-style explanations,
see [`MANUAL.md`](MANUAL.md).
