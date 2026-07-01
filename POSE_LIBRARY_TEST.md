# Pose Library — test checklist (v0.22.0)

Programmatic standard poses you can **apply** to the rig or **insert as
keyframes** into chosen frames — the answer to "can we make std poses and drop
them into frames?".

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
