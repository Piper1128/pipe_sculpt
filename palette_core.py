"""Quick color palette — pure Python serialization.

Born Clean: the bpy adapter in palette_ops.py just calls these for
encoding/decoding palette entries between Python tuples and the JSON
string stored on the scene custom property.
"""
from __future__ import annotations

import json


# Max palette slots — fits a 4×4 grid in the panel. Larger palettes
# become hard to scan visually; if the user wants more, they can have
# multiple scenes with different palettes.
MAX_SLOTS = 16


def empty_palette() -> list[tuple[float, float, float]]:
    """Return a fresh palette with MAX_SLOTS neutral-grey entries."""
    return [(0.5, 0.5, 0.5)] * MAX_SLOTS


def serialize_palette(colors: list) -> str:
    """Encode a list of RGB tuples as JSON for storage on a scene prop."""
    # Truncate / pad to exactly MAX_SLOTS so reads always get the same shape
    capped: list[tuple[float, float, float]] = []
    for c in colors[:MAX_SLOTS]:
        if len(c) >= 3:
            capped.append((float(c[0]), float(c[1]), float(c[2])))
        else:
            capped.append((0.5, 0.5, 0.5))
    while len(capped) < MAX_SLOTS:
        capped.append((0.5, 0.5, 0.5))
    return json.dumps(capped)


def deserialize_palette(blob: str) -> list[tuple[float, float, float]]:
    """Decode a JSON palette string back to a list of RGB tuples.

    Returns an empty palette if the blob is malformed — defensive against
    corrupted scene props.
    """
    if not blob:
        return empty_palette()
    try:
        data = json.loads(blob)
    except (ValueError, TypeError):
        return empty_palette()
    if not isinstance(data, list):
        return empty_palette()

    result: list[tuple[float, float, float]] = []
    for entry in data[:MAX_SLOTS]:
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            try:
                result.append((
                    _clamp01(float(entry[0])),
                    _clamp01(float(entry[1])),
                    _clamp01(float(entry[2])),
                ))
                continue
            except (TypeError, ValueError):
                pass
        result.append((0.5, 0.5, 0.5))
    while len(result) < MAX_SLOTS:
        result.append((0.5, 0.5, 0.5))
    return result


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def update_slot(
    palette: list[tuple[float, float, float]],
    slot_index: int,
    color: tuple[float, float, float],
) -> list[tuple[float, float, float]]:
    """Return a NEW palette with slot[slot_index] replaced. Out-of-range = no-op."""
    if slot_index < 0 or slot_index >= MAX_SLOTS:
        return list(palette)
    out = list(palette)
    out[slot_index] = (_clamp01(color[0]), _clamp01(color[1]), _clamp01(color[2]))
    return out
