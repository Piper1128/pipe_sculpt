# Spike: slotted-action / additive-layer API in Blender 5.1

**Purpose:** answer ANIMATION_MODULE_PLAN.md §6's three spike questions
empirically (run in Blender 5.1, not read from docs) before planning
Phase 3 (clip manager / additive layers / onion skinning).

**Method:** headless scripts against the installed Blender 5.1 binary,
building a real GTR humanoid rig + actions and inspecting / evaluating the
API. Scripts are throwaway; the findings are below.

**Verdict up front:** Phase 3 additive layers + clip manager are **feasible**,
but must be built on the **NLA** (tracks + strips with `blend_type`), NOT on
the new layered-action model — which in 5.1 allows only **one layer per
action**. The NLA path is the stable, established one, so we sidestep the
"API still stabilizing" risk the plan flagged.

---

## Q1 — Can we create / read slots via the new API?

**Yes, but slots are for multi-object binding, not multi-clip layering.**

- `action.slots` exists; `armature.animation_data.action_slot` resolves the
  active slot. (We already use this in `anim_ops._action_fcurves`.)
- `action.slots.new(id_type, name)` — signature confirmed; `id_type` is
  required (e.g. `'OBJECT'`).
- A slot binds one animated datablock to the action. Multiple slots = one
  action driving several objects. **Slots do NOT give us multiple stacked
  clips on one rig.**

→ For a **clip manager** (§E), "multiple clips per character" stays on the
established model: multiple `Action` datablocks + the NLA / Action editor,
not a slot-per-clip model.

## Q2 — Can we add an additive layer and blend it? (the decisive one)

**Within the layered-action model: NO.**
- `action.layers` count is always 1.
- `action.layers.new()` raises: **"An Action may not have more than one
  layer."**
- The single layer and its strip expose **no** `blend_type` / `influence` /
  `mix` attributes.
- So the layered-action system in 5.1 is a container for one layer's
  channelbags — it is NOT a multi-layer additive stack yet.

**Via NLA: YES, and it evaluates correctly.**
- `NlaStrip.blend_type` options: `REPLACE, COMBINE, ADD, SUBTRACT, MULTIPLY`.
- Built base track (REPLACE) + additive track and evaluated the real
  depsgraph pose:
  - **COMBINE**: base 40° + additive 20° → **60.0°** ✓ (correct additive for
    rotations — quaternion-aware).
  - **ADD**: base 40° + additive 20° → 0.0° ✗ — raw component add is wrong
    for full-rotation quaternions. **Use COMBINE, not ADD, for rotation
    layers.**
- `strip.influence` + `strip.use_animated_influence` exist. Influence is
  controllable but has a nuance: with `use_animated_influence=False` the
  strip uses its auto-computed (blend-in/out) influence; turning it on reads
  an influence **fcurve**, so a constant partial influence needs either a
  one-key influence curve or blend-in/out shaping. **Resolve the exact
  influence recipe when building §G — it's controllable, just not a single
  property poke.**

→ **Additive layers (§G)** = NLA tracks, base REPLACE + layer(s) COMBINE.
This is the standard Blender additive-animation workflow; we'd make it
one-click for GTR rigs (push base to NLA, drop recoil/breathing as a
COMBINE track, expose influence).

## Q3 — Is the old F-curve API still needed / when does it go?

**`action.fcurves` is ALREADY GONE in 5.1.** Accessing it raises
"'Action' object has no attribute 'fcurves'". F-curves live in channelbags:
`action.layers[].strips[].channelbag(slot).fcurves`. We already handle this
in `anim_ops._action_fcurves()` (legacy direct path fallback for <4.4).

---

## Consequence for Phase 3 planning

| §  | Feature | Feasible in 5.1? | Built on |
|----|---------|------------------|----------|
| E  | Clip manager | Yes | multiple `Action` datablocks + NLA push/pull; channelbag fcurves |
| G  | Additive layers | Yes | NLA tracks, base REPLACE + **COMBINE** layers, influence |
| F  | Onion skinning | Unchanged by this spike | still depsgraph mesh-eval per ghost frame or GPU overlay — the plan's "expensive / uncertain" item |

**Recommended Phase 3 order (unchanged from plan):** E (clip manager) →
G (additive layers) → F (onion skinning). E and G are now de-risked: both
sit on stable NLA + channelbag APIs, not on the not-yet-multi-layer
layered-action model. F remains the expensive, uncertain one.

**Build-time notes for G:**
- Default additive blend = `COMBINE` (correct for quaternion rotations).
- Offer `ADD` only for location/scale-only additive layers if ever needed.
- Influence: implement as a single-key influence fcurve (or blend-in/out)
  so the user gets a 0–100% dial; a bare `strip.influence` poke with
  `use_animated_influence=False` is overridden by auto-influence.
