"""Tests for palette_core — serialization round-trip + defensive decoding."""
from __future__ import annotations

import pytest

import palette_core as pal  # noqa: E402


class TestEmpty:
    def test_empty_palette_size(self):
        assert len(pal.empty_palette()) == pal.MAX_SLOTS

    def test_empty_palette_all_neutral_grey(self):
        for c in pal.empty_palette():
            assert c == (0.5, 0.5, 0.5)


class TestRoundtrip:
    def test_empty_roundtrip(self):
        blob = pal.serialize_palette(pal.empty_palette())
        result = pal.deserialize_palette(blob)
        assert result == pal.empty_palette()

    def test_custom_colors_roundtrip(self):
        palette = pal.empty_palette()
        palette[0] = (1.0, 0.0, 0.0)  # red
        palette[3] = (0.0, 1.0, 0.0)  # green
        palette[15] = (0.0, 0.0, 1.0)  # blue
        result = pal.deserialize_palette(pal.serialize_palette(palette))
        assert result[0] == (1.0, 0.0, 0.0)
        assert result[3] == (0.0, 1.0, 0.0)
        assert result[15] == (0.0, 0.0, 1.0)


class TestDefensive:
    def test_empty_string_returns_empty(self):
        assert pal.deserialize_palette("") == pal.empty_palette()

    def test_malformed_json_returns_empty(self):
        assert pal.deserialize_palette("not json") == pal.empty_palette()

    def test_non_list_returns_empty(self):
        assert pal.deserialize_palette('{"a": 1}') == pal.empty_palette()

    def test_oversized_palette_truncates(self):
        palette = [(0.1, 0.2, 0.3)] * (pal.MAX_SLOTS * 2)
        blob = pal.serialize_palette(palette)
        result = pal.deserialize_palette(blob)
        assert len(result) == pal.MAX_SLOTS

    def test_undersized_palette_pads(self):
        small = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        blob = pal.serialize_palette(small)
        result = pal.deserialize_palette(blob)
        assert len(result) == pal.MAX_SLOTS
        assert result[0] == (1.0, 0.0, 0.0)
        # Remaining slots are neutral grey
        for c in result[2:]:
            assert c == (0.5, 0.5, 0.5)

    def test_out_of_range_clamped(self):
        # Sending HDR / negative values gets clamped on decode
        palette = [(2.0, -0.5, 1.5)] + [(0.5, 0.5, 0.5)] * (pal.MAX_SLOTS - 1)
        blob = pal.serialize_palette(palette)
        result = pal.deserialize_palette(blob)
        assert result[0] == (1.0, 0.0, 1.0)


class TestUpdateSlot:
    def test_in_range_replaces(self):
        palette = pal.empty_palette()
        updated = pal.update_slot(palette, 5, (0.8, 0.2, 0.1))
        assert updated[5] == (0.8, 0.2, 0.1)
        # Other slots unchanged
        for i, c in enumerate(updated):
            if i != 5:
                assert c == (0.5, 0.5, 0.5)

    def test_negative_index_is_noop(self):
        palette = pal.empty_palette()
        assert pal.update_slot(palette, -1, (1.0, 0.0, 0.0)) == palette

    def test_out_of_range_index_is_noop(self):
        palette = pal.empty_palette()
        assert pal.update_slot(palette, pal.MAX_SLOTS, (1.0, 0.0, 0.0)) == palette

    def test_update_doesnt_mutate_input(self):
        palette = pal.empty_palette()
        original = list(palette)
        pal.update_slot(palette, 0, (0.1, 0.2, 0.3))
        assert palette == original
