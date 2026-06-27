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


# ======================================================================
# Native spawn — surface sampling + strand geometry generation
#
# All pure Python (plain float tuples, no mathutils — that's Blender-only).
# Randomness is injected via a `random.Random`-like rng so spawning is
# deterministic and unit-testable (IRandom convention from IronCore).
# The bpy wrapper extracts triangle data from the evaluated mesh, calls
# sample_surface_strands() + strand_polyline(), then builds Curves geometry.
# ======================================================================

Vec3 = tuple  # (float, float, float) — documented alias


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a: Vec3) -> float:
    import math
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(a: Vec3) -> Vec3:
    ln = _length(a)
    if ln < 1e-12:
        return (0.0, 0.0, 1.0)  # degenerate → default up
    return (a[0] / ln, a[1] / ln, a[2] / ln)


def triangle_area(v0: Vec3, v1: Vec3, v2: Vec3) -> float:
    """Area of a triangle from its three corner positions."""
    return 0.5 * _length(_cross(_sub(v1, v0), _sub(v2, v0)))


@dataclass(frozen=True)
class SampledStrand:
    """One spawned strand: a root position on the surface + growth normal."""
    root: Vec3
    normal: Vec3


def build_area_cdf(tri_areas: Sequence[float]) -> list[float]:
    """Cumulative distribution (normalised to 1.0) of triangle areas.

    Used to pick a triangle weighted by its area so strands distribute
    uniformly over the *surface*, not uniformly per-triangle (which would
    over-populate small triangles).
    """
    total = sum(tri_areas)
    if total <= 0:
        return []
    cdf = []
    running = 0.0
    for a in tri_areas:
        running += a
        cdf.append(running / total)
    cdf[-1] = 1.0  # guard against float drift
    return cdf


def pick_triangle(cdf: Sequence[float], r: float) -> int:
    """Binary-search the area CDF for the triangle containing fraction `r`."""
    if not cdf:
        return -1
    lo, hi = 0, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if r <= cdf[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def sample_barycentric(r1: float, r2: float) -> tuple[float, float, float]:
    """Uniform barycentric coordinates inside a triangle from two [0,1] rands.

    The standard fold trick: if r1+r2 > 1, reflect into the lower triangle
    so the distribution stays uniform over the whole triangle.
    """
    if r1 + r2 > 1.0:
        r1 = 1.0 - r1
        r2 = 1.0 - r2
    return (1.0 - r1 - r2, r1, r2)


def _bary_interp(a: Vec3, b: Vec3, c: Vec3, w: tuple[float, float, float]) -> Vec3:
    return _add(_add(_scale(a, w[0]), _scale(b, w[1])), _scale(c, w[2]))


def sample_surface_strands(triangles: Sequence, count: int, rng) -> list[SampledStrand]:
    """Sample `count` strand roots over the triangulated surface.

    triangles: sequence of (v0, v1, v2, n0, n1, n2) where v* are corner
               positions and n* are corner normals (all Vec3 tuples).
    rng:       a random.Random-like object exposing .random() → [0,1).

    Returns a list of SampledStrand (root position + interpolated, normalised
    growth normal). Area-weighted so strands cover the surface uniformly.
    """
    if count <= 0 or not triangles:
        return []

    areas = [triangle_area(t[0], t[1], t[2]) for t in triangles]
    cdf = build_area_cdf(areas)
    if not cdf:
        return []

    strands: list[SampledStrand] = []
    for _ in range(count):
        tri_idx = pick_triangle(cdf, rng.random())
        if tri_idx < 0:
            continue
        t = triangles[tri_idx]
        w = sample_barycentric(rng.random(), rng.random())
        root = _bary_interp(t[0], t[1], t[2], w)
        normal = _normalize(_bary_interp(t[3], t[4], t[5], w))
        strands.append(SampledStrand(root, normal))
    return strands


def strand_polyline(
    root: Vec3,
    normal: Vec3,
    length: float,
    segments: int,
    jitter_amount: float,
    rng,
) -> list[Vec3]:
    """Build the (segments+1) points of one strand growing along `normal`.

    Point 0 is the root on the surface; the rest step outward along the
    (optionally jittered) normal. jitter_amount in [0,1] perturbs the
    growth direction and per-strand length for a natural look — 0 gives
    perfectly straight, uniform strands (eyebrows / feathers).
    """
    segs = max(1, segments)
    direction = normal
    actual_length = length

    if jitter_amount > 0.0:
        # Perturb direction by a small random offset, re-normalise
        jx = (rng.random() - 0.5) * jitter_amount
        jy = (rng.random() - 0.5) * jitter_amount
        jz = (rng.random() - 0.5) * jitter_amount
        direction = _normalize(_add(normal, (jx, jy, jz)))
        # Vary length ±jitter_amount * 30 %
        length_var = 1.0 + (rng.random() - 0.5) * jitter_amount * 0.6
        actual_length = length * length_var

    points: list[Vec3] = []
    for i in range(segs + 1):
        t = i / segs
        points.append(_add(root, _scale(direction, actual_length * t)))
    return points


def build_strands_geometry(
    triangles: Sequence,
    count: int,
    preset: HairPreset,
    rng,
    mesh_scale: float = 1.0,
) -> list[list[Vec3]]:
    """Full native-spawn pipeline: sample roots → build every strand polyline.

    Returns a list of strands, each a list of (segments+1) Vec3 points.
    The bpy wrapper flattens this into a Curves datablock. mesh_scale
    scales strand length so a 0.5x mesh gets proportional hair.
    """
    sampled = sample_surface_strands(triangles, count, rng)
    jitter = 0.4 if preset.use_jitter else 0.0
    length = preset.strand_length * max(mesh_scale, 0.0001)
    return [
        strand_polyline(s.root, s.normal, length, preset.segments, jitter, rng)
        for s in sampled
    ]
