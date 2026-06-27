"""Hair/fur core — pure Python logic, no Blender dependencies.

Born Clean per IronCore conventions: this module imports NO bpy, no
Blender types. All hair-related calculations (density presets, surface
area → strand count, hair-card UV layouts) live here so they can be
unit-tested headlessly with pytest.

The bpy-side wrapper lives in hair_ops.py — it calls into this module
for calculations, then translates the results into Hair Curves operator
calls and material setup.

Public API (stable):
  - HAIR_PRESETS: tuple of HairPreset
  - get_preset(name) -> HairPreset
  - strand_count_for(surface_area_m2, preset) -> int
  - default_strand_radius_for(preset, scale) -> float
  - hair_card_uv_layout(strand_count, card_aspect) -> list of (u, v) quads
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class HairPreset:
    """Configuration for one hair / fur archetype.

    All units are SI (m, m², strands per m²) so the same preset works on
    any mesh scale. The hair_ops bpy wrapper applies obj.scale as needed.
    """
    name: str
    label: str
    description: str
    # Strands per m² of surface area. Real-world references:
    #   human scalp ~150 000/m², dog fur ~25 000/m², stubble ~5 000/m²
    density_per_m2: float
    # Default strand length in metres
    strand_length: float
    # Default strand root radius (m). Tip radius is always 0.
    root_radius: float
    # Default segment count along each strand — more = smoother curves,
    # more memory. 6-12 is typical for real-time, 20+ for cinematic.
    segments: int
    # Whether the preset wants slight randomisation in length/direction
    use_jitter: bool


HAIR_PRESETS: tuple[HairPreset, ...] = (
    HairPreset(
        name='SCALP',
        label="Scalp Hair",
        description="Dense human head hair — 150k strands/m², 15 cm length",
        density_per_m2=150_000.0,
        strand_length=0.15,
        root_radius=0.0001,  # 0.1 mm — typical human hair
        segments=12,
        use_jitter=True,
    ),
    HairPreset(
        name='BEARD',
        label="Beard / Stubble",
        description="Coarser facial hair — 50k strands/m², 3 cm length",
        density_per_m2=50_000.0,
        strand_length=0.03,
        root_radius=0.00015,
        segments=6,
        use_jitter=True,
    ),
    HairPreset(
        name='EYEBROW',
        label="Eyebrow / Lashes",
        description="Short directional hair — 80k strands/m², 1 cm length",
        density_per_m2=80_000.0,
        strand_length=0.01,
        root_radius=0.0001,
        segments=4,
        use_jitter=False,
    ),
    HairPreset(
        name='FUR_SHORT',
        label="Short Fur (cat / mouse)",
        description="Dense short fur — 200k strands/m², 1.5 cm length",
        density_per_m2=200_000.0,
        strand_length=0.015,
        root_radius=0.00008,
        segments=4,
        use_jitter=True,
    ),
    HairPreset(
        name='FUR_LONG',
        label="Long Fur (wolf / bear)",
        description="Long thick fur — 25k strands/m², 8 cm length",
        density_per_m2=25_000.0,
        strand_length=0.08,
        root_radius=0.00025,
        segments=10,
        use_jitter=True,
    ),
    HairPreset(
        name='FEATHERS',
        label="Feathers (bird)",
        description="Sparse feathers — 5k strands/m², 12 cm length",
        density_per_m2=5_000.0,
        strand_length=0.12,
        root_radius=0.0005,
        segments=8,
        use_jitter=False,
    ),
)


def get_preset(name: str) -> HairPreset:
    """Look up a preset by name. Raises KeyError if unknown."""
    for p in HAIR_PRESETS:
        if p.name == name:
            return p
    raise KeyError(f"Unknown hair preset '{name}'. Known: {[p.name for p in HAIR_PRESETS]}")


def preset_names() -> tuple[str, ...]:
    return tuple(p.name for p in HAIR_PRESETS)


# Bounds on what the bpy wrapper will accept — guards against runaway
# strand counts that would freeze Blender.
MIN_STRANDS = 1
MAX_STRANDS = 5_000_000


def strand_count_for(surface_area_m2: float, preset: HairPreset) -> int:
    """How many strands to spawn for the given surface area.

    Clamped to [MIN_STRANDS, MAX_STRANDS] so a user with a denormalised
    mesh (m² in the millions) doesn't accidentally try to spawn 30 billion
    hairs.
    """
    if surface_area_m2 <= 0:
        return MIN_STRANDS
    raw = int(round(surface_area_m2 * preset.density_per_m2))
    return max(MIN_STRANDS, min(MAX_STRANDS, raw))


def default_strand_radius_for(preset: HairPreset, mesh_scale: float = 1.0) -> float:
    """Strand root radius scaled to the mesh's world scale.

    A mesh imported at 0.5x scale should get strands 0.5x as thick so they
    visually match real-world proportions of the preset.
    """
    return preset.root_radius * max(mesh_scale, 0.0001)


def estimate_memory_mb(strand_count: int, segments: int, bytes_per_vert: int = 32) -> float:
    """Rough memory estimate for a hair curves dataset, in megabytes.

    bytes_per_vert default 32 covers position (12) + radius (4) + tangent (12)
    + a 4-byte alignment pad. Use to warn the user before they hit OOM.
    """
    total_verts = strand_count * (segments + 1)
    return (total_verts * bytes_per_vert) / (1024.0 * 1024.0)


def hair_card_uv_layout(
    strand_count: int,
    card_aspect: float = 4.0,
    margin: float = 0.005,
) -> list[tuple[float, float, float, float]]:
    """Pack `strand_count` hair-card quads into [0,1]² UV space.

    Returns a list of (u_min, v_min, u_max, v_max) tuples — one quad per
    hair card. The bpy wrapper iterates this list when converting hair
    curves to mesh hair-cards for real-time export to Unity.

    Packs in a regular grid: width = ceil(sqrt(strand_count / aspect)),
    height = ceil(strand_count / width). Cards are `card_aspect`-tall
    rectangles (typical real-time hair cards are 4:1 to 8:1 ratio).
    """
    import math

    if strand_count <= 0:
        return []

    # Solve cols × rows ≈ strand_count with card_aspect = card_h / card_w.
    # Each card occupies width × (width × card_aspect) UV space; we want
    # total area ≈ 1.0 so card_w = sqrt(1.0 / (strand_count * card_aspect)).
    card_w_target = math.sqrt(1.0 / (strand_count * card_aspect))
    cols = max(1, int(round(1.0 / card_w_target)))
    rows = max(1, math.ceil(strand_count / cols))

    card_w = (1.0 - margin * (cols + 1)) / cols
    card_h = (1.0 - margin * (rows + 1)) / rows

    layout = []
    for idx in range(strand_count):
        col = idx % cols
        row = idx // cols
        u0 = margin + col * (card_w + margin)
        v0 = margin + row * (card_h + margin)
        layout.append((u0, v0, u0 + card_w, v0 + card_h))
    return layout


def select_density_for_painted_area(
    area_m2: float,
    base_preset: HairPreset,
    density_multiplier: float = 1.0,
) -> int:
    """Strand count for a brush-painted area, with multiplier.

    The bpy hair-painting wrapper calls this each brush stroke: the user
    paints density 0..1, area is computed from polygon coverage, and we
    spawn the right number of strands. density_multiplier scales the
    preset's base density (0.5 = half-thick fur, 2.0 = double).
    """
    scaled = HairPreset(
        name=base_preset.name,
        label=base_preset.label,
        description=base_preset.description,
        density_per_m2=base_preset.density_per_m2 * max(0.0, density_multiplier),
        strand_length=base_preset.strand_length,
        root_radius=base_preset.root_radius,
        segments=base_preset.segments,
        use_jitter=base_preset.use_jitter,
    )
    return strand_count_for(area_m2, scaled)
