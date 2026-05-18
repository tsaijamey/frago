"""Tests for frago.server.state.manager module.

Tests unified state management with singleton pattern,
initialization, data loading, and refresh mechanisms.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from frago.server.state import StateManager


@pytest.fixture(autouse=True)
def reset_state_manager():
    """Reset StateManager singleton before and after each test."""
    StateManager.reset_instance()
    yield
    StateManager.reset_instance()


class TestStateManagerSingleton:
    """Test StateManager singleton pattern."""

    def test_get_instance_returns_same_instance(self):
        """Multiple calls should return same instance."""
        instance1 = StateManager.get_instance()
        instance2 = StateManager.get_instance()

        assert instance1 is instance2

    def test_reset_instance_clears_singleton(self):
        """reset_instance() should clear the singleton."""
        instance1 = StateManager.get_instance()
        StateManager.reset_instance()
        instance2 = StateManager.get_instance()

        assert instance1 is not instance2

    def test_fresh_instance_not_initialized(self):
        """Fresh instance should not be initialized."""
        instance = StateManager.get_instance()

        assert not instance.is_initialized()

    def test_fresh_instance_has_zero_version(self):
        """Fresh instance should have version 0."""
        instance = StateManager.get_instance()

        assert instance.version == 0


class TestStateManagerLoadMethods:
    """Test StateManager data loading methods."""

    def test_load_tasks(self):
        """_load_tasks should call TaskService.get_tasks."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.task_service.TaskService.get_tasks"
        ) as mock_get:
            mock_get.return_value = {
                "tasks": [{"id": "1", "title": "Test", "status": "running"}],
                "total": 1,
            }
            result = manager._load_tasks()

        assert result["total"] == 1
        assert len(result["tasks"]) == 1

    def test_load_tasks_handles_error(self):
        """_load_tasks should return empty dict on error."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.task_service.TaskService.get_tasks",
            side_effect=Exception("Error"),
        ):
            result = manager._load_tasks()

        assert result == {"tasks": [], "total": 0}

    def test_load_recipes(self):
        """_load_recipes should call RecipeService.get_recipes."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.recipe_service.RecipeService.get_recipes"
        ) as mock_get:
            mock_get.return_value = [{"name": "recipe1"}]
            result = manager._load_recipes()

        assert len(result) == 1
        assert result[0].name == "recipe1"

    def test_load_recipes_handles_error(self):
        """_load_recipes should return empty list on error."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.recipe_service.RecipeService.get_recipes",
            side_effect=Exception("Error"),
        ):
            result = manager._load_recipes()

        assert result == []

    def test_load_skills(self):
        """_load_skills should call SkillService.get_skills."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.skill_service.SkillService.get_skills"
        ) as mock_get:
            mock_get.return_value = [{"name": "skill1"}]
            result = manager._load_skills()

        assert len(result) == 1

    def test_load_skills_handles_error(self):
        """_load_skills should return empty list on error."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.skill_service.SkillService.get_skills",
            side_effect=Exception("Error"),
        ):
            result = manager._load_skills()

        assert result == []

    def test_load_projects_handles_error(self):
        """_load_projects should return empty list on error."""
        manager = StateManager.get_instance()

        with patch(
            "frago.server.services.file_service.FileService.list_projects",
            side_effect=Exception("Error"),
        ):
            result = manager._load_projects()

        assert result == []


class TestStateManagerInitialize:
    """Test StateManager.initialize() async method."""

    @pytest.mark.asyncio
    async def test_initialize_sets_initialized_flag(self):
        """initialize() should set _initialized to True."""
        manager = StateManager.get_instance()

        with (
            patch.object(manager, "_load_tasks", return_value={"tasks": [], "total": 0}),
            patch.object(manager, "_load_recipes", return_value=[]),
            patch.object(manager, "_load_skills", return_value=[]),
            patch.object(manager, "_load_projects", return_value=[]),
            patch.object(manager, "_compute_dashboard", return_value=MagicMock()),
        ):
            await manager.initialize()

        assert manager.is_initialized()

    @pytest.mark.asyncio
    async def test_initialize_skips_if_already_initialized(self):
        """initialize() should skip if already initialized."""
        manager = StateManager.get_instance()
        manager._initialized = True

        with patch.object(manager, "_load_tasks") as mock_load:
            await manager.initialize()

        mock_load.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_increments_version(self):
        """initialize() should increment version number."""
        manager = StateManager.get_instance()
        initial_version = manager.version

        with (
            patch.object(manager, "_load_tasks", return_value={"tasks": [], "total": 0}),
            patch.object(manager, "_load_recipes", return_value=[]),
            patch.object(manager, "_load_skills", return_value=[]),
            patch.object(manager, "_load_projects", return_value=[]),
            patch.object(manager, "_compute_dashboard", return_value=MagicMock()),
        ):
            await manager.initialize()

        assert manager.version == initial_version + 1


class TestStateManagerIsInitialized:
    """Test StateManager.is_initialized() method."""

    def test_returns_false_when_not_initialized(self):
        """Should return False when _initialized is False."""
        manager = StateManager.get_instance()
        manager._initialized = False

        assert manager.is_initialized() is False

    def test_returns_true_when_initialized(self):
        """Should return True when _initialized is True."""
        manager = StateManager.get_instance()
        manager._initialized = True

        assert manager.is_initialized() is True


class TestStateManagerDataAccess:
    """Test StateManager data access methods."""

    def test_get_tasks_returns_state_tasks(self):
        """get_tasks() should return state tasks."""
        manager = StateManager.get_instance()

        tasks = manager.get_tasks()

        assert tasks == manager.state.tasks

    def test_get_recipes_returns_state_recipes(self):
        """get_recipes() should return state recipes."""
        manager = StateManager.get_instance()

        recipes = manager.get_recipes()

        assert recipes == manager.state.recipes

    def test_get_skills_returns_state_skills(self):
        """get_skills() should return state skills."""
        manager = StateManager.get_instance()

        skills = manager.get_skills()

        assert skills == manager.state.skills

    def test_get_projects_returns_state_projects(self):
        """get_projects() should return state projects."""
        manager = StateManager.get_instance()

        projects = manager.get_projects()

        assert projects == manager.state.projects


class TestStateManagerCommunityRecipes:
    """Test StateManager community recipe methods."""

    def test_set_community_recipes(self):
        """set_community_recipes() should update state."""
        manager = StateManager.get_instance()

        manager.set_community_recipes([
            {"name": "recipe1", "url": "http://example.com"},
            {"name": "recipe2", "url": "http://example.com"},
        ])

        assert len(manager.get_community_recipes()) == 2
        assert manager.get_community_recipes()[0].name == "recipe1"

    def test_get_community_recipes_returns_state(self):
        """get_community_recipes() should return state community recipes."""
        manager = StateManager.get_instance()

        recipes = manager.get_community_recipes()

        assert recipes == manager.state.community_recipes
