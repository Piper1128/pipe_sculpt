"""Onion-skinning core — pure Python, no Blender dependencies.

Born Clean per IronCore conventions: NO bpy import. The ghost-frame
selection, fade/tint math, and naming are pure and headless-tested; the
bpy adapter in onion_ops.py snapshots the deformed mesh at each ghost
frame and draws it.

Background (SPIKE: §F): onion skinning captures the *deformed* mesh at
neighbouring frames as static "ghost" objects. The deform-capture works
in interactive Blender; in headless background mode IK constraints block
the armature→mesh eval (so headless tests pose FK bones). The pure logic
here is fully testable regardless.

Public API:
  ghost_frames(current, before, after, step, fmin, fmax) -> list[int]
  ghost_tint(frame, current, max_dist, base_alpha)       -> (r,g,b,a)
  ghost_name(prefix, frame)                              -> str
  PAST_COLOR, FUTURE_COLOR
"""
from __future__ import annotations


# Default ghost tints: past frames cool (blue), future frames warm (orange).
PAST_COLOR = (0.20, 0.45, 1.00)
FUTURE_COLOR = (1.00, 0.35, 0.15)


def ghost_frames(current, before, after, step=1, frame_min=None, frame_max=None):
    """Frames to snapshot around `current` (excluded), clamped to a range.

    before / after: how many ghosts on each side.
    step: frame gap between ghosts (1 = every frame, 2 = every other, ...).
    frame_min / frame_max: optional scene bounds; frames outside are dropped.

    Returns a sorted list of unique integer frames. Because frames march
    monotonically away from `current`, we stop a side as soon as it leaves
    the range.
    """
    current = int(round(current))
    step = max(1, int(step))
    frames = []
    for i in range(1, int(before) + 1):
        f = current - i * step
        if frame_min is not None and f < frame_min:
            break
        frames.append(f)
    for i in range(1, int(after) + 1):
        f = current + i * step
        if frame_max is not None and f > frame_max:
            break
        frames.append(f)
    return sorted(set(frames))


def ghost_tint(frame, current, max_dist, base_alpha=0.5,
               past=PAST_COLOR, future=FUTURE_COLOR):
    """RGBA tint for a ghost frame.

    Colour: past (frame < current) vs future. Alpha fades with distance so
    the nearest ghost reads strongest and far ghosts recede. The nearest
    ghost (distance 1) keeps full base_alpha; the farthest fades toward a
    15% floor so it never vanishes entirely.
    """
    frame = int(round(frame))
    current = int(round(current))
    dist = abs(frame - current)
    if max_dist and max_dist > 0:
        fade = max(0.15, 1.0 - (max(0, dist - 1) / max_dist) * 0.7)
    else:
        fade = 1.0
    rgb = past if frame < current else future
    return (rgb[0], rgb[1], rgb[2], base_alpha * fade)


def ghost_name(prefix, frame):
    """Stable name for a ghost object/mesh at a frame."""
    return f"{prefix}_f{int(round(frame))}"
