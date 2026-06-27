"""bpy app handlers — save-time reminders + post-load setup.

Bpy app handlers must be marked @persistent or they're cleared when a
new .blend loads. Each handler is a thin observer — actual logic stays
in the relevant module's core where possible.
"""
from __future__ import annotations

import bpy
from bpy.app.handlers import persistent


def _has_dirty_paint_textures() -> tuple[int, list[str]]:
    """Count images that are marked dirty AND look like paint output.

    'Looks like paint output' = generated_type='BLANK' (not loaded from disk
    via image.load) OR has 'albedo'/'normal'/'roughness'/'metallic' suffix.
    Returns (count, sample_names). Sample is capped at 5 names so the
    user-facing message stays readable.
    """
    paint_suffixes = ('_albedo', '_normal', '_roughness', '_metallic', '_BakeMat')
    dirty = []
    for img in bpy.data.images:
        if not img.is_dirty:
            continue
        # Skip Render Result / Viewer Node — they're always dirty
        if img.type in {'RENDER_RESULT', 'COMPOSITING'}:
            continue
        if img.source not in {'GENERATED', 'FILE'}:
            continue
        # Only paint-shape images
        if not (img.source == 'GENERATED' or any(s in img.name for s in paint_suffixes)):
            continue
        dirty.append(img.name)

    return len(dirty), dirty[:5]


@persistent
def warn_unsaved_paint_on_save(_dummy):
    """save_pre handler — warn if there are dirty paint textures."""
    count, sample = _has_dirty_paint_textures()
    if count == 0:
        return
    # Print to system console for visibility — operator reports won't fire
    # during a save handler. The save itself still proceeds.
    names_str = ", ".join(sample) + ("..." if count > len(sample) else "")
    print(
        f"\n[PipeSculpt] {count} paint texture(s) are dirty and packed "
        f"into the .blend ({names_str}). Run UV & Paint → Save Painted "
        "Textures to write them to disk as PNGs.\n"
    )


@persistent
def warn_unsaved_paint_on_load(_dummy):
    """load_pre handler — warn if the file being CLOSED has dirty paint.

    Catches the 'opened a new file without saving' case that load_post
    would miss because by then bpy.data is for the new file.
    """
    count, sample = _has_dirty_paint_textures()
    if count == 0:
        return
    names_str = ", ".join(sample) + ("..." if count > len(sample) else "")
    print(
        f"\n[PipeSculpt] Closing file with {count} unsaved paint texture(s): "
        f"{names_str}. Paint work lives in RAM until saved — make sure you "
        "ran Save Painted Textures before this.\n"
    )


_handlers = (
    (bpy.app.handlers.save_pre, warn_unsaved_paint_on_save),
    (bpy.app.handlers.load_pre, warn_unsaved_paint_on_load),
)


def register():
    for handler_list, fn in _handlers:
        if fn not in handler_list:
            handler_list.append(fn)


def unregister():
    for handler_list, fn in _handlers:
        if fn in handler_list:
            handler_list.remove(fn)
