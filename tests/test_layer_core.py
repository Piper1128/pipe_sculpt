"""Headless tests for layer_core — additive-layer helpers."""
from __future__ import annotations

import layer_core as lc  # noqa: E402 (preloaded by conftest.py)


class TestClampInfluence:
    def test_in_range(self):
        assert lc.clamp_influence(0.5) == 0.5

    def test_below(self):
        assert lc.clamp_influence(-0.3) == 0.0

    def test_above(self):
        assert lc.clamp_influence(1.7) == 1.0

    def test_edges(self):
        assert lc.clamp_influence(0.0) == 0.0
        assert lc.clamp_influence(1.0) == 1.0


class TestInfluencePercent:
    def test_half(self):
        assert lc.influence_percent(0.5) == 50

    def test_full(self):
        assert lc.influence_percent(1.0) == 100

    def test_rounds(self):
        assert lc.influence_percent(0.756) == 76

    def test_clamps(self):
        assert lc.influence_percent(2.0) == 100
        assert lc.influence_percent(-1.0) == 0


class TestIsAdditive:
    def test_combine_is_additive(self):
        assert lc.is_additive("COMBINE")

    def test_add_is_additive(self):
        assert lc.is_additive("ADD")

    def test_replace_not_additive(self):
        assert not lc.is_additive("REPLACE")

    def test_default_is_combine(self):
        assert lc.DEFAULT_BLEND_MODE == "COMBINE"
        assert lc.is_additive(lc.DEFAULT_BLEND_MODE)


class TestDescribeLayer:
    def test_basic(self):
        assert lc.describe_layer("Recoil", "COMBINE", 0.75, False) == "Recoil · Combine · 75%"

    def test_muted(self):
        s = lc.describe_layer("Breathing", "COMBINE", 1.0, True)
        assert "muted" in s
        assert s == "Breathing · Combine · muted · 100%"

    def test_full_influence(self):
        assert lc.describe_layer("Flinch", "ADD", 1.0, False) == "Flinch · Add · 100%"


class TestBlendModeConstants:
    def test_all_modes_present(self):
        for m in ("REPLACE", "COMBINE", "ADD", "SUBTRACT", "MULTIPLY"):
            assert m in lc.ALL_BLEND_MODES

    def test_replace_not_in_additive(self):
        assert "REPLACE" not in lc.ADDITIVE_BLEND_MODES
