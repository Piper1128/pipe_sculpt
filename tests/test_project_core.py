"""Tests for project_core — validation + path planning."""
from __future__ import annotations

import os
import tempfile

import pytest

import project_core as pc  # noqa: E402


class TestValidateName:
    def test_simple_name_passes(self):
        assert pc.validate_project_name("MyCharacter") is None

    def test_with_underscore_passes(self):
        assert pc.validate_project_name("hero_001") is None

    def test_with_hyphen_passes(self):
        assert pc.validate_project_name("npc-guard-01") is None

    def test_with_space_passes(self):
        assert pc.validate_project_name("My Cool Character") is None

    def test_empty_fails(self):
        assert pc.validate_project_name("") is not None
        assert pc.validate_project_name("   ") is not None

    def test_starting_with_underscore_fails(self):
        # Convention: project names start with alphanumeric for tidy
        # filesystem listings — leading underscore tends to mean
        # "hidden / special"
        assert pc.validate_project_name("_secret") is not None

    def test_starting_with_hyphen_fails(self):
        assert pc.validate_project_name("-flag") is not None

    def test_with_slash_fails(self):
        assert pc.validate_project_name("path/to/thing") is not None

    def test_with_backslash_fails(self):
        assert pc.validate_project_name("path\\thing") is not None

    def test_with_colon_fails(self):
        assert pc.validate_project_name("C:thing") is not None

    def test_too_long_fails(self):
        assert pc.validate_project_name("a" * 65) is not None

    def test_max_length_passes(self):
        assert pc.validate_project_name("a" * 64) is None

    def test_windows_reserved_names_fail(self):
        for reserved in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9"):
            assert pc.validate_project_name(reserved) is not None, f"{reserved} should be rejected"
            assert pc.validate_project_name(reserved.lower()) is not None, f"{reserved.lower()} should be rejected"


class TestProjectPaths:
    def test_layout_structure(self):
        paths = pc.project_paths("/tmp", "MyChar")
        assert paths['root'].endswith(os.path.join("tmp", "MyChar")) or \
               paths['root'].endswith(os.path.join("tmp", "MyChar").replace("/", "\\"))

    def test_subfolders_all_listed(self):
        paths = pc.project_paths("/tmp", "MyChar")
        assert set(paths['subfolders'].keys()) == set(pc.PROJECT_SUBFOLDERS)

    def test_blend_file_in_root(self):
        paths = pc.project_paths("/tmp", "MyChar")
        assert paths['blend_file'].endswith("MyChar.blend")
        assert os.path.dirname(paths['blend_file']) == paths['root']


class TestDirectoryWriteable:
    def test_existing_writeable_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            assert pc.is_directory_writeable(tmp)

    def test_nonexistent_dir_false(self):
        assert not pc.is_directory_writeable("/this/does/not/exist/anywhere")

    def test_empty_string_false(self):
        assert not pc.is_directory_writeable("")


class TestSummary:
    def test_summary_includes_project_name(self):
        s = pc.project_summary("/tmp", "Hero")
        assert "Hero" in s

    def test_summary_lists_all_subfolders(self):
        s = pc.project_summary("/tmp", "Hero")
        for sub in pc.PROJECT_SUBFOLDERS:
            assert sub in s

    def test_summary_mentions_blend(self):
        s = pc.project_summary("/tmp", "Hero")
        assert ".blend" in s
