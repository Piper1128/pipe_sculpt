# Hair that follows pose — test checklist (v0.21.0)

Two things were broken and are now fixed:

1. **"Invalid UV map: UV islands must not overlap"** when sculpting hair.
2. **Hair didn't follow pose / animation.**

Root cause: the old Setup created a bare Hair Curves object with no
*Deform Curves on Surface* modifier and bound it to whatever UV was active
(a Mirror-X paint UV overlaps → the sculpt error). The new Setup uses
Blender's native hair creation, gives hair its **own** non-overlapping UV,
and stores the `rest_position` / `surface_uv_coordinate` data the deform
modifier needs.

> These can only be verified **in the GUI** — in `--background` the mesh
> itself doesn't deform, so the automated tests only check the *setup* is
> correct, not the follow. That's what this checklist is for.

## Install
1. Blender ▸ Edit ▸ Preferences ▸ Add-ons ▸ install `pipe_sculpt.zip` (v0.21.0),
   or Disable+Enable if already installed, then restart if in doubt.

## Test A — no more UV overlap error
1. Add a body (or `Add T-Pose Humanoid`) and **Generate Rig**.
2. Select the **body mesh**.
3. (Optional, to reproduce the old bug) UV ▸ Smart Unwrap, then **Mirror X**.
4. Hair & Fur ▸ **1. Setup Hair**.
5. Hair & Fur ▸ **3. Sculpt / Comb** → try the **Add** brush on the scalp.
   - ✅ PASS: strands appear, **no** "UV islands must not overlap" error.
   - Your paint UV is untouched — Setup made a separate `PipeSculpt_HairUV`.

## Test B — hair follows pose
1. Same body with a rig + some hair (Setup, then **2. Spawn (Preset)** = Scalp,
   or brush a patch with the Add brush).
2. The panel should read **"Follows pose ✓"** while the hair object is selected.
3. Select the **armature**, enter **Pose Mode**.
4. Rotate the **head** bone (or an arm if you put fur on it).
   - ✅ PASS: the hair rotates/moves **with** the surface.
   - ❌ FAIL: hair stays floating in the rest position → tell me, and say
     whether the hair was **spawned** or **brushed**.
5. Scrub the timeline over an animation — hair should track every frame.

## Test C — export stays clean
1. Select the hair, Hair & Fur ▸ **4. → Hair Cards**.
2. Export ▸ FBX to Unity as usual.
   - The extra `PipeSculpt_HairUV` lives on the *body* mesh (a second UV
     channel); it's harmless in Unity. Shout if you'd rather it be stripped
     on export.

## Notes
- Spawn at **rest pose** (frame with no deform) for the cleanest bind.
- Keep hair on the **retopo low-poly**, not the multires sculpt (same reason
  posing multires is slow).
