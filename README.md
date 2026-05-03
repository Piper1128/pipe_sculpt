# SculptKit

Pie-menus and a workflow pipeline for character and face sculpting in Blender 5.0+.

## Scope

- **Brush pie-menus** — `Q` for 8 primary brushes, `Shift+Q` for 8 secondary. Replaces Blender's default Quick Favorites.
- **Workflow pipeline** — three presets (Character / Bust+Face / Prop) with one-click Start Sculpt → Add Detail → Retopo → Bake.

## Install (Blender 5.0+)

1. Zip the `sculpt_kit/` folder.
2. Blender → Edit → Preferences → Get Extensions → Install from Disk → pick the zip.
3. Enable "SculptKit".

For development, you can also drop the folder directly into `<blender_user_dir>/extensions/user_default/` and restart Blender.

## Status

MVP — verified in Blender 5.1 background mode end-to-end (Start → Add Detail → Retopo → Bake) on a default cube. Visual smoke test in interactive Blender still pending.

## Known limitations

- Q / Shift+Q only override Quick Favorites in **Sculpt** mode. Outside sculpt mode the default Quick Favorites menu is unchanged.
- Brush slot names map to Blender 5.x `essentials_brushes-mesh_sculpt.blend` asset names. If Blender renames a default brush, edit the slot name in addon preferences.
- Initial voxel remesh is skipped in `bpy.app.background` mode to avoid a Blender crash (sculpt undo stack not initialised without UI).
- Bake resolution hardcoded to 2048×2048 for the MVP — to be made configurable.
- Bake assumes a single bake-target material; if the low-poly already has multiple material slots, Blender will warn but still produce the output image.

## Workflow

1. Select a base mesh.
2. In the 3D View N-panel → "SculptKit" tab → pick preset (Bust / Character / Prop) → **Start Sculpt**.
3. Sculpt freely with `Q` / `Shift+Q` pies. Click **Add Detail** when you want a multires step up.
4. **Retopo** duplicates and quadriflows; original is hidden, new active object is `<name>_retopo`.
5. **Bake Maps** auto-pairs `<name>_retopo` with `<name>` for normal-map bake at 2048².
