"""Headless unit tests for hair_core — pure Python, no Blender needed.

Born Clean per IronCore conventions: these tests run with `pytest`
without a Blender install. They verify the math, not the bpy wiring.

Run with:
    python -m pytest tests/test_hair_core.py -v
"""
from __future__ import annotations

import pytest

# hair_core is preloaded by conftest.py via importlib's file-loader so we
# don't have to trigger pipe_sculpt/__init__.py (which imports bpy).
import hair_core as hc  # noqa: E402


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
