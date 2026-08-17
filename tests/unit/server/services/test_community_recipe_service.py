"""Tests for frago.server.services.community_recipe_service module.

Tests community recipe management with caching and periodic refresh.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from frago.server.services.community_recipe_service import CommunityRecipeService


@pytest.fixture
def reset_community_service():
    """Reset singleton state before each test."""
    CommunityRecipeService._instance = None
    yield
    CommunityRecipeService._instance = None


class TestCommunityRecipeServiceSingleton:
    """Test CommunityRecipeService singleton pattern."""

    def test_get_instance_returns_same_instance(self, reset_community_service):
        """Multiple calls should return same instance."""
        instance1 = CommunityRecipeService.get_instance()
        instance2 = CommunityRecipeService.get_instance()

        assert instance1 is instance2

    def test_fresh_instance_has_no_cache(self, reset_community_service):
        """Fresh instance should have no cached data."""
        instance = CommunityRecipeService.get_instance()

        assert instance._cache is None
        assert instance._last_fetch_error is None


class TestCommunityRecipeServiceGetLastError:
    """Test CommunityRecipeService.get_last_error() method."""

    def test_returns_none_initially(self, reset_community_service):
        """Should return None when no error occurred."""
        service = CommunityRecipeService.get_instance()

        assert service.get_last_error() is None

    def test_returns_stored_error(self, reset_community_service):
        """Should return last fetch error."""
        service = CommunityRecipeService.get_instance()
        service._last_fetch_error = "Test error"

        assert service.get_last_error() == "Test error"


class TestCommunityRecipeServiceInstallRecipe:
    """Test CommunityRecipeService.install_recipe() method."""

    def test_successful_installation(self, reset_community_service):
        """Should return success on successful installation."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.install.return_value = "test-recipe"

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.install_recipe("test-recipe")

        assert result["status"] == "ok"
        assert result["recipe_name"] == "test-recipe"
        assert service._cache is None  # Cache should be invalidated

    def test_installation_failure(self, reset_community_service):
        """Should return error on installation failure."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.install.side_effect = Exception("Install failed")

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.install_recipe("failing-recipe")

        assert result["status"] == "error"
        assert "Install failed" in result["error"]


class TestCommunityRecipeServiceUpdateRecipe:
    """Test CommunityRecipeService.update_recipe() method."""

    def test_successful_update(self, reset_community_service):
        """Should return success on successful update."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.update.return_value = "updated-recipe"

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.update_recipe("test-recipe")

        assert result["status"] == "ok"
        assert result["recipe_name"] == "updated-recipe"

    def test_update_failure(self, reset_community_service):
        """Should return error on update failure."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.update.side_effect = Exception("Update failed")

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.update_recipe("failing-recipe")

        assert result["status"] == "error"


class TestCommunityRecipeServiceUninstallRecipe:
    """Test CommunityRecipeService.uninstall_recipe() method."""

    def test_successful_uninstall(self, reset_community_service):
        """Should return success on successful uninstall."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.uninstall.return_value = True

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.uninstall_recipe("test-recipe")

        assert result["status"] == "ok"
        assert result["recipe_name"] == "test-recipe"

    def test_uninstall_not_found(self, reset_community_service):
        """Should return error when recipe not found."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.uninstall.return_value = False

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.uninstall_recipe("not-found")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_uninstall_failure(self, reset_community_service):
        """Should return error on uninstall failure."""
        service = CommunityRecipeService.get_instance()

        mock_installer = MagicMock()
        mock_installer.uninstall.side_effect = Exception("Uninstall failed")

        with patch(
            "frago.recipes.installer.RecipeInstaller",
            return_value=mock_installer,
        ):
            result = service.uninstall_recipe("failing-recipe")

        assert result["status"] == "error"


class TestCommunityRecipeServiceAsync:
    """Test CommunityRecipeService async methods."""

    @pytest.mark.asyncio
    async def test_start_does_not_await_the_first_fetch(
        self, reset_community_service
    ):
        """start() must return before GitHub answers.

        Server startup calls this; if it waited, an unreachable or rate-limited
        api.github.com would keep the server from serving anything at all.
        """
        service = CommunityRecipeService.get_instance()
        fetch_entered = asyncio.Event()
        release = asyncio.Event()

        async def hanging_refresh():
            fetch_entered.set()
            await release.wait()

        with patch.object(service, "_do_refresh", side_effect=hanging_refresh):
            await service.start()
            await asyncio.wait_for(fetch_entered.wait(), timeout=1)

            # start() is long back while the fetch is still out there hanging.
            assert service._cache is None
            assert not service._first_refresh_done.is_set()

            release.set()
            await service.stop()

    @pytest.mark.asyncio
    async def test_reader_waits_for_the_in_flight_first_fetch(
        self, reset_community_service
    ):
        """A reader arriving mid-bootstrap joins that fetch, never starts a second.

        A duplicate fetch costs a request out of an hourly budget that is 60
        when nobody is logged in.
        """
        service = CommunityRecipeService.get_instance()
        release = asyncio.Event()

        async def slow_refresh():
            await release.wait()
            service._cache = [{"name": "recipe1"}]

        with patch.object(
            service, "_do_refresh", side_effect=slow_refresh
        ) as mock_refresh:
            await service.start()
            reader = asyncio.create_task(service.get_recipes())
            await asyncio.sleep(0)  # let the loop and the reader both start

            release.set()
            recipes = await asyncio.wait_for(reader, timeout=2)

            assert recipes == [{"name": "recipe1"}]
            assert mock_refresh.call_count == 1  # the loop's, not a second one

            await service.stop()

    @pytest.mark.asyncio
    async def test_reader_fetches_when_no_loop_is_running(
        self, reset_community_service
    ):
        """With no background loop, a reader still fetches for itself."""
        service = CommunityRecipeService.get_instance()

        async def fill_cache():
            service._cache = [{"name": "recipe1"}]

        with patch.object(
            service, "_do_refresh", side_effect=fill_cache
        ) as mock_refresh:
            recipes = await service.get_recipes()

        assert recipes == [{"name": "recipe1"}]
        mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_creates_task(self, reset_community_service):
        """start() should create background refresh task."""
        service = CommunityRecipeService.get_instance()

        with patch.object(
            service, "_refresh_loop", new_callable=AsyncMock
        ):
            await service.start()

            assert service._task is not None

            # Cleanup
            await service.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, reset_community_service):
        """stop() should cancel running task."""
        service = CommunityRecipeService.get_instance()

        with patch.object(
            service, "_refresh_loop", new_callable=AsyncMock
        ):
            await service.start()
            await service.stop()

            assert service._task is None or service._task.done()

    @pytest.mark.asyncio
    async def test_get_recipes_returns_cache(self, reset_community_service):
        """get_recipes() should return cached recipes."""
        service = CommunityRecipeService.get_instance()
        service._cache = [{"name": "recipe1"}, {"name": "recipe2"}]

        recipes = await service.get_recipes()

        assert len(recipes) == 2
        assert recipes[0]["name"] == "recipe1"

    @pytest.mark.asyncio
    async def test_get_recipes_fetches_if_no_cache(self, reset_community_service):
        """get_recipes() should fetch if no cache."""
        service = CommunityRecipeService.get_instance()
        service._cache = None

        with patch.object(
            service, "_do_refresh", new_callable=AsyncMock
        ) as mock_refresh:
            async def set_cache():
                service._cache = [{"name": "fetched"}]

            mock_refresh.side_effect = set_cache
            recipes = await service.get_recipes()

        assert recipes == [{"name": "fetched"}]
