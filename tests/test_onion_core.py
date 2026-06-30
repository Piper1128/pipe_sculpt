"""Headless tests for onion_core — ghost-frame selection + tint math."""
from __future__ import annotations

import onion_core as oc  # noqa: E402 (preloaded by conftest.py)


class TestGhostFrames:
    def test_symmetric(self):
        assert oc.ghost_frames(10, 2, 2) == [8, 9, 11, 12]

    def test_excludes_current(self):
        assert 10 not in oc.ghost_frames(10, 3, 3)

    def test_before_only(self):
        assert oc.ghost_frames(10, 3, 0) == [7, 8, 9]

    def test_after_only(self):
        assert oc.ghost_frames(10, 0, 3) == [11, 12, 13]

    def test_step(self):
        assert oc.ghost_frames(10, 2, 2, step=2) == [6, 8, 12, 14]

    def test_step_min_one(self):
        # step 0 is clamped to 1
        assert oc.ghost_frames(10, 1, 1, step=0) == [9, 11]

    def test_clamp_min(self):
        # frame_min=8 drops frames below 8
        assert oc.ghost_frames(10, 5, 0, frame_min=8) == [8, 9]

    def test_clamp_max(self):
        assert oc.ghost_frames(10, 0, 5, frame_max=12) == [11, 12]

    def test_clamp_both(self):
        assert oc.ghost_frames(10, 5, 5, frame_min=9, frame_max=11) == [9, 11]

    def test_zero_ghosts(self):
        assert oc.ghost_frames(10, 0, 0) == []

    def test_float_current_rounded(self):
        assert oc.ghost_frames(10.4, 1, 1) == [9, 11]


class TestGhostTint:
    def test_past_is_blue(self):
        r, g, b, a = oc.ghost_tint(8, 10, max_dist=2)
        assert b > r  # blue-dominant

    def test_future_is_warm(self):
        r, g, b, a = oc.ghost_tint(12, 10, max_dist=2)
        assert r > b  # red-dominant

    def test_nearest_full_alpha(self):
        # distance 1 keeps base_alpha
        _, _, _, a = oc.ghost_tint(9, 10, max_dist=4, base_alpha=0.5)
        assert a == 0.5

    def test_far_fades(self):
        near = oc.ghost_tint(9, 10, max_dist=4, base_alpha=0.5)[3]
        far = oc.ghost_tint(14, 10, max_dist=4, base_alpha=0.5)[3]
        assert far < near

    def test_alpha_floor(self):
        # very far ghost never drops below the 15% floor of base_alpha
        _, _, _, a = oc.ghost_tint(1000, 10, max_dist=4, base_alpha=0.5)
        assert a >= 0.15 * 0.5

    def test_no_max_dist_full(self):
        _, _, _, a = oc.ghost_tint(15, 10, max_dist=0, base_alpha=0.6)
        assert a == 0.6


class TestGhostName:
    def test_basic(self):
        assert oc.ghost_name("Onion", 7) == "Onion_f7"

    def test_negative_frame(self):
        assert oc.ghost_name("Onion", -3) == "Onion_f-3"

    def test_float_rounded(self):
        assert oc.ghost_name("Onion", 7.6) == "Onion_f8"
