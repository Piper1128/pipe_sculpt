# Pose Library — test checklist (v0.23.0)

Programmatic standard poses you can **apply** to the rig or **insert as
keyframes** into chosen frames — plus **save your own** poses to disk.

## New in v0.23.0
- **Save your own poses** — pose the rig by hand, click **Save Current Pose**,
  give it a name. It's written as a `.json` asset (like a Unity
  ScriptableObject) and shows up in the list under **★**. Re-save the same name
  to update it (pose → tweak → re-save). Trash icon deletes a ★ pose.
  Folder is set in Preferences ▸ Add-ons ▸ PipeSculpt ▸ *User Pose Folder*
  (empty = Blender's config folder).
- **Elbow now bends when you drag** — the IK was set to *stretch* (so dragging
  the hand telescoped the arm instead of bending it). Fixed to rigid bones.
  **⚠ Re-run Generate Rig** to get the fix on an existing character.
- **Longer strides** on Walk/Run contact (with a small body-dip so the planted
  foot still reaches).

## What it is
- 18 curated poses in three groups — **Stance**, **Locomotion**, **Action**.
- **Apply Pose**: snap the rig to a pose (no keyframe).
- **Insert at Frame**: jump to a frame, apply, and keyframe the whole rig
  there. An **Advance** field auto-steps the frame so you can block a pose per
  key.
- **Mirror** and **Influence** (0–100 %, blend from rest) on every apply.

## How poses work on this rig (important)
The rig is IK-driven, so a pose moves the **IK controls** (the coloured
cube/diamond widgets — run *Style Controls* to see them) and the **FK** torso;
the arms/legs then **solve via IK**. So:
- You need a **generated rig**, in **Pose Mode**.
- Only the controls + FK bones are keyed — the IK-solved limb bones are left to
  the solver (correct for baking to Unity later).

> The pose *data* and all directions (which arm waves, which hip hikes, L/R
> symmetry, nothing beyond reach) were verified headless. What a headless
> Blender **can't** judge is whether a pose *looks* good — that's this test.

## Where
Pose Mode on the armature → **PipeSculpt ▸ Pose Library** panel.

## Test A — apply
1. Add a body → **Generate Rig** → (optional) **Style Controls**.
2. Select the armature, enter **Pose Mode**.
3. Pose Library ▸ pick **Relaxed Idle** ▸ **Apply Pose**.
   - ✅ the rig takes the pose; arms/legs bend naturally via IK.
4. Try **Mirror** on an asymmetric one (**Waving Hello**) — the wave flips to
   the other arm.
5. Drag **Influence** to ~0.5 and Apply — a half-strength pose.

## Test B — insert keyframes / block a sequence
1. Set **Frame = 1**, **Advance = 8**.
2. Pick **T-Pose** ▸ **Insert at Frame** (keys frame 1, frame → 9).
3. Pick **Reach Overhead** ▸ **Insert at Frame** (keys frame 9, frame → 17).
4. Pick **Victory / Cheer** ▸ **Insert at Frame** (keys frame 17…).
5. Play back — the character animates through the three poses.
   - ✅ each pose is a full keyframe; the timeline blends between them.

## Test C — save your own pose (the SO-like bit)
1. **Re-run Generate Rig** (to get the elbow fix), Style Controls, Pose Mode.
2. Pose the rig by hand — grab a **coloured cube** (hand_ik) and move it; the
   elbow now **bends** instead of the arm stretching. To aim the elbow which
   way it points, grab the **diamond** (elbow_pole).
3. **Save Current Pose** → name it "My Idle" → it appears under **★ My Idle**.
4. Move to a fresh frame, reset, then pick **★ My Idle** ▸ **Apply** — your
   pose comes back exactly.
5. Tweak it, **Save Current Pose** with the *same name* → it updates the file.
6. The 🗑 next to Save deletes the selected ★ pose.

### Bending the elbow when you drag (quick how-to)
- Grab **hand_ik** (cube) and pull it **toward the body** → the elbow bends.
  Moving the hand around at full arm's length keeps the arm straight — that's
  correct IK; the bend appears when the hand comes closer than the arm's reach.
- Grab **elbow_pole** (diamond) to point the elbow a specific direction.
- If dragging still felt like the arm *stretched* — you're on an old rig;
  re-run **Generate Rig**.

## The 18 poses
- **Stance**: T-Pose · A-Pose · Relaxed Idle · Contrapposto · Power Stance
  (arms crossed) · Crouch / Sneak · Sitting · Aim / Ready (2-hand)
- **Locomotion**: Walk Contact · Walk Passing · Run Contact
- **Action**: Reach Forward · Reach Overhead · Waving Hello · Victory / Cheer ·
  Thinking (hand-on-chin) · Dramatic Reach · Hit React (flinch)

## What to look for (tell me if any is off)
- **Crouch / Sitting** are deliberately deep — if they fold too far, say so and
  I'll raise them.
- **Contrapposto** shifts weight to the **left** leg (left hip up) — flag if it
  looks inverted.
- Any hand/foot that looks like it's *reaching but not arriving* (limb locked
  straight) — I can pull that target in.
- Want more poses, or different ones? The catalog is regenerable from
  `tools/pose_catalog.json` via `tools/author_poses.py`.
