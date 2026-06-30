"""Headless tests for clip_core — clip-manager naming logic."""
from __future__ import annotations

import clip_core as cc  # noqa: E402 (preloaded by conftest.py)


class TestStripDupSuffix:
    def test_strips_numeric(self):
        assert cc.strip_dup_suffix("Walk.001") == "Walk"
        assert cc.strip_dup_suffix("Run.042") == "Run"

    def test_no_suffix_unchanged(self):
        assert cc.strip_dup_suffix("Walk") == "Walk"

    def test_non_numeric_suffix_kept(self):
        assert cc.strip_dup_suffix("Run.beta") == "Run.beta"

    def test_short_name(self):
        assert cc.strip_dup_suffix("A") == "A"
        assert cc.strip_dup_suffix(".001") == ".001"  # nothing before the dot

    def test_only_strips_last_suffix(self):
        assert cc.strip_dup_suffix("Walk.001.002") == "Walk.001"


class TestUniqueName:
    def test_no_collision(self):
        assert cc.unique_name("Walk", []) == "Walk"
        assert cc.unique_name("Walk", ["Run", "Idle"]) == "Walk"

    def test_first_collision(self):
        assert cc.unique_name("Walk", ["Walk"]) == "Walk.001"

    def test_skips_taken_numbers(self):
        assert cc.unique_name("Walk", ["Walk", "Walk.001", "Walk.002"]) == "Walk.003"

    def test_fills_gap(self):
        # .001 is free even though .002 exists
        assert cc.unique_name("Walk", ["Walk", "Walk.002"]) == "Walk.001"

    def test_accepts_set(self):
        assert cc.unique_name("Walk", {"Walk"}) == "Walk.001"


class TestNextDuplicateName:
    def test_plain_name(self):
        assert cc.next_duplicate_name("Walk", ["Walk"]) == "Walk.001"

    def test_already_suffixed(self):
        # Duplicating 'Walk.001' should give 'Walk.002', not 'Walk.001.001'
        assert cc.next_duplicate_name("Walk.001", ["Walk", "Walk.001"]) == "Walk.002"

    def test_no_existing(self):
        assert cc.next_duplicate_name("Walk", []) == "Walk"


class TestSortClipNames:
    def test_case_insensitive(self):
        assert cc.sort_clip_names(["walk", "Idle", "Run"]) == ["Idle", "Run", "walk"]

    def test_stable_for_equal_lower(self):
        # 'Walk' and 'walk' compare equal case-insensitively; tie-break keeps order deterministic
        out = cc.sort_clip_names(["walk", "Walk"])
        assert set(out) == {"walk", "Walk"}
        assert len(out) == 2
