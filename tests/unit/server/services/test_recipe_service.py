"""Tests for frago.server.services.recipe_service module.

Tests recipe loading, caching, and execution.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.recipe_service import RecipeService


class TestRecipeServiceCache:
    """Test RecipeService caching behavior."""

    def test_get_recipes_force_reload(self):
        """get_recipes with force_reload should bypass cache."""
        with patch.object(RecipeService, "_load_recipes", return_value=[{"name": "fresh"}]):
            result = RecipeService.get_recipes(force_reload=True)

        assert result == [{"name": "fresh"}]


class TestRecipeServiceLoadRecipes:
    """Test RecipeService._load_recipes() method."""

    def test_loads_from_registry(self):
        """Should load recipes from RecipeRegistry."""
        mock_recipe = MagicMock()
        mock_recipe.metadata.name = "test-recipe"
        mock_recipe.metadata.description = "Test description"
        mock_recipe.metadata.type = "atomic"
        mock_recipe.metadata.tags = ["test"]
        mock_recipe.metadata.runtime = "python"
        mock_recipe.script_path = Path("/path/to/recipe.py")
        mock_recipe.source = "User"

        mock_registry = MagicMock()
        mock_registry.needs_rescan.return_value = False
        mock_registry.list_all.return_value = [mock_recipe]

        with patch("frago.recipes.registry.get_registry", return_value=mock_registry):
            result = RecipeService._load_recipes()

        assert len(result) == 1
        assert result[0]["name"] == "test-recipe"
        assert result[0]["description"] == "Test description"
        assert result[0]["category"] == "atomic"
        assert result[0]["source"] == "User"

    def test_invalidates_registry_on_rescan_needed(self):
        """Should invalidate and recreate registry if rescan needed."""
        mock_recipe = MagicMock()
        mock_recipe.metadata.name = "recipe"
        mock_recipe.metadata.description = "desc"
        mock_recipe.metadata.type = "atomic"
        mock_recipe.metadata.tags = []
        mock_recipe.metadata.runtime = "python"
        mock_recipe.script_path = None
        mock_recipe.source = "User"

        mock_registry_old = MagicMock()
        mock_registry_old.needs_rescan.return_value = True

        mock_registry_new = MagicMock()
        mock_registry_new.list_all.return_value = [mock_recipe]

        call_count = [0]

        def get_registry_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_registry_old
            return mock_registry_new

        with (
            patch("frago.recipes.registry.get_registry", side_effect=get_registry_side_effect),
            patch("frago.recipes.registry.invalidate_registry") as mock_invalidate,
        ):
            result = RecipeService._load_recipes()

        mock_invalidate.assert_called_once()
        assert len(result) == 1


class TestRecipeServiceLoadFromFilesystem:
    """Test RecipeService._load_recipes_from_filesystem() fallback."""

    def test_finds_js_recipes(self, tmp_path):
        """Should find .js recipe files."""
        recipes_dir = tmp_path / ".frago" / "recipes" / "atomic"
        recipes_dir.mkdir(parents=True)
        (recipes_dir / "test-recipe.js").write_text("// js recipe")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = RecipeService._load_recipes_from_filesystem()

        assert len(result) == 1
        assert result[0]["name"] == "test-recipe"
        assert result[0]["category"] == "atomic"

    def test_finds_py_recipes(self, tmp_path):
        """Should find .py recipe files."""
        recipes_dir = tmp_path / ".frago" / "recipes" / "workflows"
        recipes_dir.mkdir(parents=True)
        (recipes_dir / "workflow-recipe.py").write_text("# py recipe")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = RecipeService._load_recipes_from_filesystem()

        assert len(result) == 1
        assert result[0]["name"] == "workflow-recipe"
        assert result[0]["category"] == "workflow"

    def test_skips_init_files(self, tmp_path):
        """Should skip __init__.py files."""
        recipes_dir = tmp_path / ".frago" / "recipes"
        recipes_dir.mkdir(parents=True)
        (recipes_dir / "__init__.py").write_text("")
        (recipes_dir / "real-recipe.py").write_text("# recipe")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = RecipeService._load_recipes_from_filesystem()

        assert len(result) == 1
        assert result[0]["name"] == "real-recipe"

    def test_empty_when_no_recipes_dir(self, tmp_path):
        """Should return empty list when recipes directory doesn't exist."""
        # tmp_path doesn't have .frago/recipes

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = RecipeService._load_recipes_from_filesystem()

        assert result == []


class TestRecipeServiceGetRecipe:
    """Test RecipeService.get_recipe() method."""

    def test_fallback_to_list_on_registry_failure(self):
        """Should fallback to list lookup when registry raises."""
        with patch(
            "frago.recipes.registry.get_registry",
            side_effect=Exception("registry error")
        ):
            with patch.object(
                RecipeService, "get_recipes",
                return_value=[{"name": "target-recipe", "description": "Found via list"}]
            ):
                result = RecipeService.get_recipe("target-recipe")

        assert result is not None
        assert result["name"] == "target-recipe"

    def test_returns_none_when_not_found(self):
        """Should return None when recipe not found."""
        with patch(
            "frago.recipes.registry.get_registry",
            side_effect=Exception("not found")
        ):
            with patch.object(
                RecipeService, "get_recipes",
                return_value=[]
            ):
                result = RecipeService.get_recipe("nonexistent")

        assert result is None


class TestRecipeServiceRunRecipe:
    """Test RecipeService.run_recipe() method.

    RecipeService now directly calls RecipeRunner instead of subprocess.
    """

    def test_sync_execution_success(self):
        """Should return success result on successful execution."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "success": True,
            "data": {"response": "hello"},
            "stderr": "",
            "error": None,
            "execution_time": 1.0,
            "recipe_name": "test-recipe",
            "runtime": "python",
        }

        with patch(
            "frago.recipes.runner.RecipeRunner",
            return_value=mock_runner,
        ):
            result = RecipeService.run_recipe("test-recipe")

        assert result["status"] == "ok"
        assert result["data"] == {"response": "hello"}
        assert result["error"] is None
        assert "duration_ms" in result

    def test_sync_execution_failure(self):
        """Should return error result on failed execution."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "success": False,
            "data": None,
            "stderr": "",
            "error": {"message": "Recipe failed"},
            "execution_time": 0.5,
            "recipe_name": "failing-recipe",
            "runtime": "python",
        }

        with patch(
            "frago.recipes.runner.RecipeRunner",
            return_value=mock_runner,
        ):
            result = RecipeService.run_recipe("failing-recipe")

        assert result["status"] == "error"
        assert result["data"] is None
        assert result["error"] == {"message": "Recipe failed"}

    def test_async_execution(self):
        """Should delegate to RecipeRunner.run_async() and return execution_id."""
        mock_runner = MagicMock()
        mock_runner.run_async.return_value = "exec_abc123"

        with patch(
            "frago.recipes.runner.RecipeRunner",
            return_value=mock_runner,
        ):
            result = RecipeService.run_recipe_async("async-recipe", params={"k": "v"}, timeout=60)

        mock_runner.run_async.assert_called_once_with("async-recipe", {"k": "v"}, timeout=60)
        assert result == "exec_abc123"

    def test_with_params(self):
        """Should pass params to RecipeRunner.run()."""
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "success": True,
            "data": {"result": "ok"},
            "stderr": "",
            "error": None,
            "execution_time": 0.1,
            "recipe_name": "param-recipe",
            "runtime": "python",
        }

        with patch(
            "frago.recipes.runner.RecipeRunner",
            return_value=mock_runner,
        ):
            RecipeService.run_recipe("param-recipe", params={"key": "value"})

        mock_runner.run.assert_called_once_with("param-recipe", {"key": "value"})
