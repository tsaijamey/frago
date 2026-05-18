"""Tests for frago.recipes.registry module.

Tests recipe scanning, registration, and singleton management.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.recipes.registry import (
    RecipeRegistry,
    get_registry,
    invalidate_registry,
)


class TestGetSourceLabel:
    """Test _get_source_label() method."""

    @pytest.fixture
    def registry(self) -> RecipeRegistry:
        """Create empty registry."""
        with patch.object(RecipeRegistry, "_setup_search_paths"):
            reg = RecipeRegistry()
            reg.search_paths = []
            return reg

    def test_user_recipes_path(self, registry: RecipeRegistry):
        """User recipes path should return 'User'."""
        path = Path.home() / ".frago" / "recipes" / "atomic"
        assert registry._get_source_label(path) == "User"

    def test_community_recipes_path(self, registry: RecipeRegistry):
        """Community recipes path should return 'Community'."""
        path = Path.home() / ".frago" / "community-recipes" / "atomic"
        assert registry._get_source_label(path) == "Community"

    def test_official_recipes_path(self, registry: RecipeRegistry):
        """Other paths should return 'Official'."""
        path = Path("/usr/share/frago/recipes")
        assert registry._get_source_label(path) == "Official"

    def test_windows_user_path(self, registry: RecipeRegistry):
        """Windows-style user path should return 'User'."""
        # Simulate Windows path with backslashes
        path = Path("C:/Users/test/.frago\\recipes\\atomic")
        assert registry._get_source_label(path) == "User"


class TestNeedsRescan:
    """Test needs_rescan() method."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> RecipeRegistry:
        """Create registry with temp search path."""
        with patch.object(RecipeRegistry, "_setup_search_paths"):
            reg = RecipeRegistry()
            reg.search_paths = [tmp_path]
            reg._last_scan_mtimes = {}
            return reg

    def test_no_previous_scan(self, registry: RecipeRegistry, tmp_path: Path):
        """Should return True if path not in last_scan_mtimes."""
        assert registry.needs_rescan() is True

    def test_after_scan_no_changes(self, registry: RecipeRegistry, tmp_path: Path):
        """Should return False after scan with no changes."""
        # Record current mtime
        registry._last_scan_mtimes[tmp_path] = tmp_path.stat().st_mtime

        assert registry.needs_rescan() is False

    def test_directory_modified(self, registry: RecipeRegistry, tmp_path: Path):
        """Should return True if directory was modified."""
        import time

        # Record old mtime
        registry._last_scan_mtimes[tmp_path] = tmp_path.stat().st_mtime - 10

        # Modify directory
        (tmp_path / "new_file.txt").write_text("test")

        assert registry.needs_rescan() is True

    def test_nonexistent_path_skipped(self, tmp_path: Path):
        """Non-existent paths should be skipped."""
        with patch.object(RecipeRegistry, "_setup_search_paths"):
            reg = RecipeRegistry()
            reg.search_paths = [tmp_path / "nonexistent"]
            reg._last_scan_mtimes = {}

        # Should not raise, just return False
        assert reg.needs_rescan() is False


class TestScan:
    """Test scan() method."""

    @pytest.fixture
    def recipes_dir(self, tmp_path: Path) -> Path:
        """Create temp recipes directory structure."""
        recipes = tmp_path / ".frago" / "recipes"
        (recipes / "atomic" / "chrome").mkdir(parents=True)
        (recipes / "atomic" / "system").mkdir(parents=True)
        (recipes / "workflows").mkdir(parents=True)
        return recipes

    @pytest.fixture
    def registry(self, recipes_dir: Path) -> RecipeRegistry:
        """Create registry with temp directory."""
        with patch.object(RecipeRegistry, "_setup_search_paths"):
            reg = RecipeRegistry()
            reg.search_paths = [recipes_dir]
            reg._last_scan_mtimes = {}
            return reg

    def test_scan_clears_previous(self, registry: RecipeRegistry, recipes_dir: Path):
        """Scan should clear previous recipes."""
        # Add fake entry
        registry.recipes["fake"] = {"User": "fake_recipe"}

        registry.scan()

        assert "fake" not in registry.recipes

    def test_scan_records_mtime(self, registry: RecipeRegistry, recipes_dir: Path):
        """Scan should record directory mtime."""
        registry.scan()

        assert recipes_dir in registry._last_scan_mtimes

    def test_scan_finds_recipe(self, registry: RecipeRegistry, recipes_dir: Path):
        """Scan should find valid recipe directories."""
        # Create a valid recipe
        recipe_dir = recipes_dir / "atomic" / "chrome" / "test-recipe"
        recipe_dir.mkdir()

        # Create recipe.md with valid frontmatter (all required fields)
        (recipe_dir / "recipe.md").write_text(
            """---
name: test-recipe
description: A test recipe for unit testing
type: atomic
runtime: python
version: "1.0.0"
use_cases:
  - Testing recipe registry
output_targets:
  - stdout
---

# Test Recipe
"""
        )

        # Create recipe.py
        (recipe_dir / "recipe.py").write_text("# Python recipe script")

        registry.scan()

        assert "test-recipe" in registry.recipes
        assert "User" in registry.recipes["test-recipe"]

    def test_scan_skips_missing_script(self, registry: RecipeRegistry, recipes_dir: Path):
        """Recipe without script file should be skipped."""
        recipe_dir = recipes_dir / "atomic" / "chrome" / "no-script"
        recipe_dir.mkdir()

        (recipe_dir / "recipe.md").write_text(
            """---
name: no-script
description: Recipe without script
type: atomic
runtime: python
version: "1.0.0"
use_cases:
  - Testing
output_targets:
  - stdout
---
"""
        )
        # No recipe.py created

        registry.scan()

        assert "no-script" not in registry.recipes


class TestFindScriptFile:
    """Test _find_script_file() method."""

    @pytest.fixture
    def registry(self) -> RecipeRegistry:
        """Create empty registry."""
        with patch.object(RecipeRegistry, "_setup_search_paths"):
            reg = RecipeRegistry()
            reg.search_paths = []
            return reg

    def test_find_python_script(self, registry: RecipeRegistry, tmp_path: Path):
        """Should find recipe.py for python runtime."""
        (tmp_path / "recipe.py").write_text("# python")

        result = registry._find_script_file(tmp_path, "python")

        assert result == tmp_path / "recipe.py"

    def test_find_js_script(self, registry: RecipeRegistry, tmp_path: Path):
        """Should find recipe.js for chrome-js runtime."""
        (tmp_path / "recipe.js").write_text("// javascript")

        result = registry._find_script_file(tmp_path, "chrome-js")

        assert result == tmp_path / "recipe.js"

    def test_find_shell_script(self, registry: RecipeRegistry, tmp_path: Path):
        """Should find recipe.sh for shell runtime."""
        (tmp_path / "recipe.sh").write_text("#!/bin/bash")

        result = registry._find_script_file(tmp_path, "shell")

        assert result == tmp_path / "recipe.sh"

    def test_script_not_found(self, registry: RecipeRegistry, tmp_path: Path):
        """Should return None if script not found."""
        result = registry._find_script_file(tmp_path, "python")

        assert result is None

    def test_unknown_runtime(self, registry: RecipeRegistry, tmp_path: Path):
        """Unknown runtime should return None."""
        result = registry._find_script_file(tmp_path, "unknown-runtime")

        assert result is None


class TestSingletonFunctions:
    """Test module-level singleton functions."""

    def test_get_registry_returns_instance(self):
        """get_registry should return RecipeRegistry instance."""
        # Note: reset_singletons fixture will clean up
        result = get_registry()

        assert isinstance(result, RecipeRegistry)

    def test_get_registry_returns_same_instance(self):
        """Multiple calls should return same instance."""
        instance1 = get_registry()
        instance2 = get_registry()

        assert instance1 is instance2

    def test_invalidate_registry_clears_singleton(self):
        """invalidate_registry should clear the singleton."""
        instance1 = get_registry()
        invalidate_registry()
        instance2 = get_registry()

        # Should be different instances after invalidation
        assert instance1 is not instance2
