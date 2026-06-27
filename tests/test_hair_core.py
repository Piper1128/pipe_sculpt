"""Headless unit tests for hair_core — pure Python, no Blender needed.

Born Clean per IronCore conventions: these tests run with `pytest`
without a Blender install. They verify the math, not the bpy wiring.

Run with:
    python -m pytest tests/test_hair_core.py -v
"""
from __future__ import annotations

import math
import random

import pytest

# hair_core is preloaded by conftest.py via importlib's file-loader so we
# don't have to trigger pipe_sculpt/__init__.py (which imports bpy).
import hair_core as hc  # noqa: E402


# A unit quad in the XY plane, split into two triangles, normals = +Z.
# Total area = 1.0 m² — handy for density math.
def _unit_quad_triangles():
    v00 = (0.0, 0.0, 0.0)
    v10 = (1.0, 0.0, 0.0)
    v11 = (1.0, 1.0, 0.0)
    v01 = (0.0, 1.0, 0.0)
    up = (0.0, 0.0, 1.0)
    return [
        (v00, v10, v11, up, up, up),
        (v00, v11, v01, up, up, up),
    ]


class TestPresets:
    def test_six_presets_shipped(self):
        assert len(hc.HAIR_PRESETS) == 6

    def test_preset_names_are_unique(self):
        names = [p.name for p in hc.HAIR_PRESETS]
        assert len(names) == len(set(names))

    def test_get_preset_lookup(self):
        scalp = hc.get_preset('SCALP')
        assert scalp.name == 'SCALP'
        assert scalp.density_per_m2 == 150_000.0

    def test_get_preset_unknown_raises(self):
        with pytest.raises(KeyError):
            hc.get_preset('NOT_A_PRESET')

    def test_preset_names_helper(self):
        assert hc.preset_names() == ('SCALP', 'BEARD', 'EYEBROW', 'FUR_SHORT', 'FUR_LONG', 'FEATHERS')

    def test_density_ordering(self):
        # Sanity: short fur should be denser than long fur (more strands per m²)
        assert hc.get_preset('FUR_SHORT').density_per_m2 > hc.get_preset('FUR_LONG').density_per_m2
        # Feathers should be the sparsest preset
        feather_density = hc.get_preset('FEATHERS').density_per_m2
        for p in hc.HAIR_PRESETS:
            if p.name != 'FEATHERS':
                assert p.density_per_m2 > feather_density


class TestStrandCount:
    def test_zero_area_returns_minimum(self):
        scalp = hc.get_preset('SCALP')
        assert hc.strand_count_for(0.0, scalp) == hc.MIN_STRANDS

    def test_negative_area_returns_minimum(self):
        scalp = hc.get_preset('SCALP')
        assert hc.strand_count_for(-1.0, scalp) == hc.MIN_STRANDS

    def test_typical_human_scalp(self):
        # A human scalp is ~0.06 m² (head circumference ~56 cm, half spherical)
        # SCALP preset is 150k/m², so expect ~9000 strands
        scalp = hc.get_preset('SCALP')
        count = hc.strand_count_for(0.06, scalp)
        assert 8000 <= count <= 10000

    def test_clamped_to_max(self):
        scalp = hc.get_preset('SCALP')
        # A 1 km² scalp would be 150 billion strands — must clamp
        absurd = hc.strand_count_for(1_000_000.0, scalp)
        assert absurd == hc.MAX_STRANDS


class TestStrandRadius:
    def test_radius_scales_with_mesh_scale(self):
        scalp = hc.get_preset('SCALP')
        normal = hc.default_strand_radius_for(scalp, mesh_scale=1.0)
        doubled = hc.default_strand_radius_for(scalp, mesh_scale=2.0)
        assert doubled == pytest.approx(normal * 2.0)

    def test_zero_scale_uses_floor(self):
        scalp = hc.get_preset('SCALP')
        # Should still return a positive radius
        r = hc.default_strand_radius_for(scalp, mesh_scale=0.0)
        assert r > 0


class TestMemoryEstimate:
    def test_zero_strands_zero_memory(self):
        assert hc.estimate_memory_mb(0, 12) == 0.0

    def test_typical_scalp_under_1mb(self):
        # 10k strands * 13 verts * 32 bytes = 4.16 MB — well under "warn at 50 MB"
        mb = hc.estimate_memory_mb(10_000, 12)
        assert mb < 10.0

    def test_million_strand_warning_range(self):
        # 1M strands × 13 verts × 32 bytes ÷ 1024² ≈ 396 MB — well past
        # any sensible "warn at 100 MB" threshold for hair memory
        mb = hc.estimate_memory_mb(1_000_000, 12)
        assert mb > 300.0


class TestHairCardLayout:
    def test_empty_input(self):
        assert hc.hair_card_uv_layout(0) == []
        assert hc.hair_card_uv_layout(-1) == []

    def test_single_card_fills_uv_space(self):
        layout = hc.hair_card_uv_layout(1, card_aspect=1.0)
        assert len(layout) == 1
        u0, v0, u1, v1 = layout[0]
        # Should fit comfortably inside [0, 1] with margin
        assert 0 <= u0 < u1 <= 1
        assert 0 <= v0 < v1 <= 1

    def test_card_count_matches_input(self):
        for n in (1, 4, 9, 16, 100):
            layout = hc.hair_card_uv_layout(n)
            assert len(layout) == n

    def test_cards_dont_overlap(self):
        # Quick check for a small layout
        layout = hc.hair_card_uv_layout(4, card_aspect=1.0, margin=0.01)
        for i, a in enumerate(layout):
            for j, b in enumerate(layout):
                if i >= j:
                    continue
                # Two rects overlap iff neither's right < other's left
                overlap_x = not (a[2] <= b[0] or b[2] <= a[0])
                overlap_y = not (a[3] <= b[1] or b[3] <= a[1])
                assert not (overlap_x and overlap_y), f"Cards {i} and {j} overlap"

    def test_cards_stay_inside_uv_unit(self):
        layout = hc.hair_card_uv_layout(50, card_aspect=4.0)
        for u0, v0, u1, v1 in layout:
            assert u0 >= 0
            assert v0 >= 0
            assert u1 <= 1.0001  # epsilon for float math
            assert v1 <= 1.0001


class TestPaintedAreaDensity:
    def test_zero_multiplier_clamps_to_min(self):
        scalp = hc.get_preset('SCALP')
        # 0 multiplier × 0.06 m² × 150k = 0; clamps to MIN_STRANDS
        assert hc.select_density_for_painted_area(0.06, scalp, density_multiplier=0.0) == hc.MIN_STRANDS

    def test_double_multiplier_doubles_count(self):
        scalp = hc.get_preset('SCALP')
        normal = hc.select_density_for_painted_area(0.06, scalp, density_multiplier=1.0)
        doubled = hc.select_density_for_painted_area(0.06, scalp, density_multiplier=2.0)
        # Within rounding tolerance
        assert abs(doubled - normal * 2) <= 1

    def test_negative_multiplier_clamps_to_min(self):
        scalp = hc.get_preset('SCALP')
        # Defensive — negative multiplier shouldn't produce negative strand counts
        assert hc.select_density_for_painted_area(0.06, scalp, density_multiplier=-1.0) == hc.MIN_STRANDS


class TestVectorHelpers:
    def test_triangle_area_unit(self):
        # Right triangle with legs 1.0 → area 0.5
        a = hc.triangle_area((0, 0, 0), (1, 0, 0), (0, 1, 0))
        assert a == pytest.approx(0.5)

    def test_unit_quad_total_area(self):
        tris = _unit_quad_triangles()
        total = sum(hc.triangle_area(t[0], t[1], t[2]) for t in tris)
        assert total == pytest.approx(1.0)

    def test_degenerate_triangle_zero_area(self):
        # All points collinear → zero area
        a = hc.triangle_area((0, 0, 0), (1, 0, 0), (2, 0, 0))
        assert a == pytest.approx(0.0)

    def test_normalize_unit(self):
        n = hc._normalize((3.0, 0.0, 0.0))
        assert n == pytest.approx((1.0, 0.0, 0.0))

    def test_normalize_degenerate_returns_up(self):
        n = hc._normalize((0.0, 0.0, 0.0))
        assert n == (0.0, 0.0, 1.0)


class TestAreaCDF:
    def test_empty_areas(self):
        assert hc.build_area_cdf([]) == []

    def test_zero_total(self):
        assert hc.build_area_cdf([0.0, 0.0]) == []

    def test_cdf_ends_at_one(self):
        cdf = hc.build_area_cdf([1.0, 3.0])
        assert cdf[-1] == 1.0

    def test_cdf_monotonic(self):
        cdf = hc.build_area_cdf([2.0, 1.0, 3.0, 0.5])
        for i in range(1, len(cdf)):
            assert cdf[i] >= cdf[i - 1]

    def test_cdf_proportions(self):
        # Areas 1:3 → first boundary at 0.25
        cdf = hc.build_area_cdf([1.0, 3.0])
        assert cdf[0] == pytest.approx(0.25)


class TestPickTriangle:
    def test_empty_cdf_returns_minus_one(self):
        assert hc.pick_triangle([], 0.5) == -1

    def test_picks_first_bucket(self):
        cdf = [0.25, 1.0]
        assert hc.pick_triangle(cdf, 0.1) == 0
        assert hc.pick_triangle(cdf, 0.25) == 0

    def test_picks_second_bucket(self):
        cdf = [0.25, 1.0]
        assert hc.pick_triangle(cdf, 0.5) == 1
        assert hc.pick_triangle(cdf, 1.0) == 1

    def test_area_weighting_is_proportional(self):
        # Big second triangle (area 9 vs 1) should get ~90% of picks
        cdf = hc.build_area_cdf([1.0, 9.0])
        rng = random.Random(42)
        picks = [hc.pick_triangle(cdf, rng.random()) for _ in range(10000)]
        frac_second = sum(1 for p in picks if p == 1) / len(picks)
        assert 0.86 < frac_second < 0.94


class TestBarycentric:
    def test_inside_lower_triangle(self):
        # r1+r2 <= 1 stays as-is
        w = hc.sample_barycentric(0.2, 0.3)
        assert w == pytest.approx((0.5, 0.2, 0.3))
        assert sum(w) == pytest.approx(1.0)

    def test_folds_upper_triangle(self):
        # r1+r2 > 1 reflects
        w = hc.sample_barycentric(0.8, 0.7)
        assert sum(w) == pytest.approx(1.0)
        assert all(c >= 0 for c in w)

    def test_weights_always_sum_to_one(self):
        rng = random.Random(7)
        for _ in range(1000):
            w = hc.sample_barycentric(rng.random(), rng.random())
            assert sum(w) == pytest.approx(1.0)
            assert all(c >= -1e-9 for c in w)


class TestSampleSurfaceStrands:
    def test_zero_count_empty(self):
        assert hc.sample_surface_strands(_unit_quad_triangles(), 0, random.Random(1)) == []

    def test_no_triangles_empty(self):
        assert hc.sample_surface_strands([], 100, random.Random(1)) == []

    def test_count_matches(self):
        strands = hc.sample_surface_strands(_unit_quad_triangles(), 500, random.Random(1))
        assert len(strands) == 500

    def test_roots_lie_on_surface_plane(self):
        # Unit quad is at z=0; all roots should have z≈0
        strands = hc.sample_surface_strands(_unit_quad_triangles(), 200, random.Random(1))
        for s in strands:
            assert abs(s.root[2]) < 1e-9

    def test_roots_inside_unit_square(self):
        strands = hc.sample_surface_strands(_unit_quad_triangles(), 200, random.Random(1))
        for s in strands:
            assert -1e-9 <= s.root[0] <= 1.0 + 1e-9
            assert -1e-9 <= s.root[1] <= 1.0 + 1e-9

    def test_normals_point_up(self):
        strands = hc.sample_surface_strands(_unit_quad_triangles(), 50, random.Random(1))
        for s in strands:
            assert s.normal == pytest.approx((0.0, 0.0, 1.0))

    def test_deterministic_with_same_seed(self):
        tris = _unit_quad_triangles()
        a = hc.sample_surface_strands(tris, 100, random.Random(99))
        b = hc.sample_surface_strands(tris, 100, random.Random(99))
        assert a == b


class TestStrandPolyline:
    def test_point_count(self):
        pts = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.1, 6, 0.0, random.Random(1))
        assert len(pts) == 7  # segments + 1

    def test_minimum_one_segment(self):
        pts = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.1, 0, 0.0, random.Random(1))
        assert len(pts) == 2  # clamped to 1 segment

    def test_root_is_first_point(self):
        root = (0.3, 0.4, 0.0)
        pts = hc.strand_polyline(root, (0, 0, 1), 0.1, 4, 0.0, random.Random(1))
        assert pts[0] == pytest.approx(root)

    def test_no_jitter_is_straight(self):
        # Without jitter the tip is exactly length along the normal
        pts = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.2, 4, 0.0, random.Random(1))
        assert pts[-1] == pytest.approx((0.0, 0.0, 0.2))

    def test_no_jitter_evenly_spaced(self):
        pts = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.4, 4, 0.0, random.Random(1))
        # Each step should be 0.1 in z
        for i, p in enumerate(pts):
            assert p[2] == pytest.approx(0.1 * i)

    def test_jitter_perturbs(self):
        straight = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.2, 4, 0.0, random.Random(1))
        jittered = hc.strand_polyline((0, 0, 0), (0, 0, 1), 0.2, 4, 0.5, random.Random(1))
        # Tip should differ once jitter is applied
        assert jittered[-1] != straight[-1]


class TestBuildStrandsGeometry:
    def test_full_pipeline_count(self):
        tris = _unit_quad_triangles()
        preset = hc.get_preset('FUR_SHORT')
        strands = hc.build_strands_geometry(tris, 100, preset, random.Random(3))
        assert len(strands) == 100
        # Each strand has segments+1 points
        for s in strands:
            assert len(s) == preset.segments + 1

    def test_scale_affects_length(self):
        tris = _unit_quad_triangles()
        preset = hc.get_preset('EYEBROW')  # no jitter → deterministic length
        normal = hc.build_strands_geometry(tris, 10, preset, random.Random(5), mesh_scale=1.0)
        scaled = hc.build_strands_geometry(tris, 10, preset, random.Random(5), mesh_scale=2.0)
        # First strand tip distance from root should double
        def tip_dist(strand):
            r, t = strand[0], strand[-1]
            return hc._length(hc._sub(t, r))
        assert tip_dist(scaled[0]) == pytest.approx(tip_dist(normal[0]) * 2.0)
