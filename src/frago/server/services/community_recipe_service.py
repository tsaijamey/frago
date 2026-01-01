"""Community recipe management service.

Provides functionality for listing, installing, and updating
recipes from the community repository with periodic refresh.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Refresh interval in seconds
COMMUNITY_REFRESH_INTERVAL_SECONDS = 60


class CommunityRecipeService:
    """Service for community recipe operations with caching and periodic refresh."""

    _instance: Optional["CommunityRecipeService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the service."""
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._last_fetch_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._cache_service: Optional[Any] = None

    @classmethod
    def get_instance(cls) -> "CommunityRecipeService":
        """Get singleton instance.

        Returns:
            CommunityRecipeService instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_cache_service(self, cache_service: Any) -> None:
        """Link to CacheService for broadcasting updates.

        Args:
            cache_service: CacheService instance
        """
        self._cache_service = cache_service

    async def start(self) -> None:
        """Start background refresh task."""
        if self._task is not None and not self._task.done():
            logger.warning("Community recipe service already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info(
            f"Community recipe refresh started "
            f"(interval: {COMMUNITY_REFRESH_INTERVAL_SECONDS}s)"
        )

    async def stop(self) -> None:
        """Stop background refresh task."""
        if self._task is None or self._task.done():
            return

        self._stop_event.set()
        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        logger.info("Community recipe refresh stopped")

    async def _refresh_loop(self) -> None:
        """Background refresh loop."""
        while not self._stop_event.is_set():
            try:
                await self._do_refresh()
            except Exception as e:
                logger.warning(f"Community recipe refresh failed: {e}")
                self._last_fetch_error = str(e)

            # Wait for next refresh interval or stop event
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=COMMUNITY_REFRESH_INTERVAL_SECONDS,
                )
                # If wait completes without timeout, stop was requested
                break
            except asyncio.TimeoutError:
                # Timeout means continue to next refresh
                continue

    async def _do_refresh(self) -> None:
        """Perform refresh and broadcast if changed."""
        loop = asyncio.get_event_loop()
        new_data = await loop.run_in_executor(None, self._fetch_community_recipes)

        # Compare with cache - if different, update and broadcast
        if new_data != self._cache:
            self._cache = new_data
            self._last_fetch_error = None
            await self._broadcast_update()
            logger.debug(f"Community recipes updated, count={len(new_data)}")

    def _fetch_community_recipes(self) -> List[Dict[str, Any]]:
        """Fetch from GitHub and enrich with install status.

        Returns:
            List of community recipe dictionaries with installation status
        """
        from frago.recipes.installer import RecipeInstaller

        installer = RecipeInstaller()

        # Get community recipes from GitHub
        try:
            raw_recipes = installer.search_community()
        except Exception as e:
            logger.warning(f"Failed to fetch community recipes: {e}")
            self._last_fetch_error = str(e)
            return self._cache or []

        # Get installed recipes to check status
        installed = {r.name: r for r in installer.list_installed()}

        # Enrich with installation status
        result = []
        for recipe in raw_recipes:
            name = recipe.get("name", "")
            installed_info = installed.get(name)

            result.append({
                "name": name,
                "url": recipe.get("url", ""),
                "description": recipe.get("description"),
                "version": recipe.get("version"),
                "type": recipe.get("type", "atomic"),
                "runtime": recipe.get("runtime"),
                "tags": recipe.get("tags", []),
                "installed": installed_info is not None,
                "installed_version": installed_info.version if installed_info else None,
                "has_update": (
                    installed_info is not None
                    and recipe.get("version")
                    and installed_info.version != recipe.get("version")
                ),
            })

        return result

    async def _broadcast_update(self) -> None:
        """Broadcast community recipes update via WebSocket and update cache."""
        # Update CacheService for dashboard stats
        if self._cache_service is not None:
            self._cache_service.set_community_recipes(self._cache or [])

        try:
            from frago.server.websocket import manager, create_message

            message = create_message("data_community_recipes", {
                "data": self._cache,
                "error": self._last_fetch_error,
            })
            await manager.broadcast(message)
            logger.debug(
                f"Broadcast community recipes to {manager.connection_count} clients"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast community recipes: {e}")

    async def get_recipes(self) -> List[Dict[str, Any]]:
        """Get cached community recipes.

        Returns:
            List of community recipe dictionaries
        """
        if self._cache is None:
            # Initial fetch if not cached
            await self._do_refresh()
        return self._cache or []

    def install_recipe(self, name: str, force: bool = False) -> Dict[str, Any]:
        """Install a community recipe.

        Args:
            name: Recipe name to install
            force: Force overwrite if already exists

        Returns:
            Result dictionary with status, recipe_name, message, error
        """
        from frago.recipes.installer import RecipeInstaller

        try:
            installer = RecipeInstaller()
            installed_name = installer.install(f"community:{name}", force=force)
            # Invalidate cache to pick up new installation status
            self._cache = None
            return {
                "status": "ok",
                "recipe_name": installed_name,
                "message": f"Successfully installed {installed_name}",
            }
        except Exception as e:
            logger.error(f"Failed to install community recipe {name}: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def update_recipe(self, name: str) -> Dict[str, Any]:
        """Update an installed community recipe.

        Args:
            name: Recipe name to update

        Returns:
            Result dictionary with status, recipe_name, message, error
        """
        from frago.recipes.installer import RecipeInstaller

        try:
            installer = RecipeInstaller()
            updated_name = installer.update(name)
            # Invalidate cache
            self._cache = None
            return {
                "status": "ok",
                "recipe_name": updated_name,
                "message": f"Successfully updated {updated_name}",
            }
        except Exception as e:
            logger.error(f"Failed to update community recipe {name}: {e}")
            return {
                "status": "error",
                "error": str(e),
            }

    def get_last_error(self) -> Optional[str]:
        """Get the last fetch error if any.

        Returns:
            Error message or None
        """
        return self._last_fetch_error
