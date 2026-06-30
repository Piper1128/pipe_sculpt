# Onion Skin — interactive test checklist

§F onion skinning is **headless-verified for the FK deform path** (ghosts
capture different deformed poses, frame restores, re-show rebuilds, clear
leaks nothing). But the deform-capture for **IK-driven** poses can only be
confirmed in interactive Blender — in headless background mode IK constraints
block the armature→mesh eval (a Blender background-mode limitation, not a bug
in the feature). Run this checklist in the GUI to confirm §F end-to-end.

## Setup
1. Open Blender 5.1, install/enable the latest PipeSculpt (`python pack.py`
   → `pipe_sculpt.zip` → Install from Disk; disable any older version first).
2. N-panel → PipeSculpt → Starter Meshes → **Humanoid**.
3. Workflow Pipeline → **Start Sculpt**, then **Generate Rig**.
4. Select the armature, enter **Pose Mode**.

## A. Basic FK onion skin
1. Pose `upper_arm.L` (rotate it), at frame 1 key the rig (Animate → Key Rig).
2. Go to frame 20, rotate the arm further, Key Rig again.
3. Go to a middle frame (e.g. 10).
4. PipeSculpt → **Onion Skin** panel → **Show Onion Skin**.
5. ✅ EXPECT: translucent ghost copies of the body appear at the surrounding
   frames — blue/cool on the *past* side, warm/orange on the *future* side,
   fading with distance. Switch viewport to **Material Preview** if they look
   flat in Solid mode.
6. ✅ The arm should be at a *different angle* in each ghost (the motion arc).
7. **Clear Onion Skin** → all ghosts gone, nothing left in the Outliner under
   "PipeSculpt Onion Skin".

## B. IK-driven onion skin (the headless-unverifiable case)
1. Move an IK target (`hand_ik.L` or `foot_ik.L`) and key it across two frames
   so the limb bends via IK.
2. Mid-frame → **Show Onion Skin**.
3. ✅ EXPECT: the ghosts show the IK-deformed limb at each frame (the bend
   follows the IK target). *This is the case that can't be tested headless —
   confirm it works here.*

## C. Robustness spot-checks
1. **Re-show**: with ghosts visible, change Before/After and click Show again
   → ghosts rebuild at the new range, not accumulate.
2. **Frame restore**: note the current frame before Show; after Show the
   playhead should be back on the same frame.
3. **Render hidden**: the ghosts must NOT appear in a render (F12) — they're
   reference only.
4. **Save/reload**: save the .blend, reopen — ghosts are static meshes; they
   persist (Clear to remove). Acceptable.
5. **No animation**: on a rig with no keys, Show produces identical ghosts (no
   arc) — not useful but should not error.

## If something's wrong
- Ghosts don't deform (all identical despite animation): the deform-capture
  isn't seeing the pose — note whether it's FK or IK, and the shading mode.
- Ghosts invisible: try Material Preview / Rendered shading (the ghost
  material is alpha-blended; Solid mode may not show transparency).
- Leftover objects after Clear: report which (object / mesh / material /
  collection names start with "Onion" / "PipeSculpt Onion Skin").
