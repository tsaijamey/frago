"""Unified state manager for server data.

Provides centralized state management with:
- Single source of truth for all server data
- Type-safe data access
- Centralized refresh mechanism
- WebSocket broadcast on changes
"""

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from frago.server.state.broadcaster import StateBroadcaster
from frago.server.state.loader import StateLoader
from frago.server.state.models import (
    CommunityRecipe,
    Project,
    Recipe,
    ServerState,
    Skill,
    UserConfig,
)

logger = logging.getLogger(__name__)


class StateManager:
    """Unified state manager for all server data.

    This is the single point of access for all server state.
    All data modifications should go through this manager.
    """

    _instance: Optional["StateManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the state manager."""
        self._state = ServerState()
        self._async_lock: Optional[asyncio.Lock] = None
        self._initialized = False
        self._broadcaster = StateBroadcaster()

    @classmethod
    def get_instance(cls) -> "StateManager":
        """Get singleton instance.

        Returns:
            StateManager instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _get_async_lock(self) -> asyncio.Lock:
        """Get or create async lock for the current event loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    @property
    def state(self) -> ServerState:
        """Get current state (read-only access)."""
        return self._state

    @property
    def version(self) -> int:
        """Get current state version."""
        return self._state.version

    def is_initialized(self) -> bool:
        """Check if state is initialized."""
        return self._initialized

    # ============================================================
    # Initialization
    # ============================================================

    async def initialize(self) -> None:
        """Initialize state by loading all data.

        Should be called during application startup.
        """
        if self._initialized:
            logger.debug("State already initialized")
            return

        logger.info("Initializing state manager...")
        start_time = datetime.now()

        async with self._get_async_lock():
            loop = asyncio.get_event_loop()

            # Load all data concurrently
            recipes_future = loop.run_in_executor(None, self._load_recipes)
            skills_future = loop.run_in_executor(None, self._load_skills)
            projects_future = loop.run_in_executor(None, self._load_projects)

            recipes_data, skills_data, projects_data = await asyncio.gather(
                recipes_future, skills_future, projects_future
            )

            self._state.recipes = recipes_data
            self._state.skills = skills_data
            self._state.projects = projects_data

            self._state.version += 1
            self._state.last_updated = datetime.now()
            self._initialized = True

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"State initialized in {duration:.2f}s: "
            f"recipes={len(self._state.recipes)}, "
            f"skills={len(self._state.skills)}, "
            f"projects={len(self._state.projects)}"
        )

    # ============================================================
    # Data Loading (internal)
    # ============================================================

    # 加载逻辑已抽到 state/loader.StateLoader；以下保留为门面委托，行为不变。
    def _load_recipes(self) -> List[Recipe]:
        """Load recipes from storage (delegates to StateLoader)."""
        return StateLoader.load_recipes()

    def _load_skills(self) -> List[Skill]:
        """Load skills from storage (delegates to StateLoader)."""
        return StateLoader.load_skills()

    def _load_projects(self) -> List[Project]:
        """Load projects from storage (delegates to StateLoader)."""
        return StateLoader.load_projects()

    def _load_config(self) -> Dict[str, Any]:
        """Load main config from storage (delegates to StateLoader)."""
        return StateLoader.load_config()

    def _load_gh_status(self) -> Dict[str, Any]:
        """Load GitHub CLI status (delegates to StateLoader)."""
        return StateLoader.load_gh_status()

    # ============================================================
    # Data Access (public)
    # ============================================================

    def get_recipes(self) -> List[Recipe]:
        """Get recipe list."""
        return self._state.recipes

    def get_community_recipes(self) -> List[CommunityRecipe]:
        """Get community recipe list."""
        return self._state.community_recipes

    def get_skills(self) -> List[Skill]:
        """Get skill list."""
        return self._state.skills

    def get_projects(self) -> List[Project]:
        """Get project list."""
        return self._state.projects

    def get_config(self) -> Dict[str, Any]:
        """Get user config, loading on first access."""
        if not self._state.config or self._state.config == UserConfig():
            self._state.config = self._load_config()  # type: ignore
        # Return as dict for API compatibility
        if isinstance(self._state.config, dict):
            return self._state.config
        return {}

    def get_gh_status(self) -> Dict[str, Any]:
        """Get GitHub CLI status, loading on first access."""
        if not self._state.gh_status:
            self._state.gh_status = self._load_gh_status()
        return self._state.gh_status

    # ============================================================
    # Data Refresh (public)
    # ============================================================

    async def refresh_recipes(self, broadcast: bool = True) -> None:
        """Refresh recipe data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.recipes = await loop.run_in_executor(None, self._load_recipes)
            self._state.version += 1
            self._state.last_updated = datetime.now()

        if broadcast:
            await self._broadcast("recipes", self._state.recipes)

        logger.debug(f"Recipes refreshed, version={self._state.version}")

    async def refresh_skills(self, broadcast: bool = True) -> None:
        """Refresh skill data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.skills = await loop.run_in_executor(None, self._load_skills)
            self._state.version += 1
            self._state.last_updated = datetime.now()

        if broadcast:
            await self._broadcast("skills", self._state.skills)

        logger.debug(f"Skills refreshed, version={self._state.version}")

    async def refresh_projects(self, broadcast: bool = True) -> None:
        """Refresh project data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.projects = await loop.run_in_executor(None, self._load_projects)
            self._state.version += 1
            self._state.last_updated = datetime.now()

        if broadcast:
            await self._broadcast("projects", self._state.projects)

        logger.debug(f"Projects refreshed, version={self._state.version}")

    async def refresh_all(self, broadcast: bool = True) -> None:
        """Refresh all data."""
        await self.refresh_recipes(broadcast=False)
        await self.refresh_skills(broadcast=False)
        await self.refresh_projects(broadcast=False)

        if broadcast:
            await self._broadcast("all", self.get_initial_data())

    async def refresh_config(self, broadcast: bool = True) -> None:
        """Refresh config data."""
        loop = asyncio.get_event_loop()
        self._state.config = await loop.run_in_executor(None, self._load_config)  # type: ignore
        self._state.version += 1

        if broadcast:
            await self._broadcast_raw("data_config", self._state.config)

        logger.debug("Config refreshed")

    async def refresh_gh_status(self, broadcast: bool = True) -> None:
        """Refresh GitHub CLI status."""
        loop = asyncio.get_event_loop()
        self._state.gh_status = await loop.run_in_executor(None, self._load_gh_status)
        self._state.version += 1

        if broadcast:
            await self._broadcast_raw("data_gh_status", self._state.gh_status)

        logger.debug("GitHub CLI status refreshed")

    def set_community_recipes(self, recipes: List[Dict[str, Any]]) -> None:
        """Update community recipes from external service."""
        self._state.community_recipes = [
            CommunityRecipe(
                name=r.get("name", ""),
                url=r.get("url", ""),
                description=r.get("description"),
                version=r.get("version"),
                type=r.get("type", "atomic"),
                runtime=r.get("runtime"),
                tags=r.get("tags", []),
                installed=r.get("installed", False),
                installed_version=r.get("installed_version"),
                has_update=r.get("has_update", False),
            )
            for r in recipes
        ]

    # ============================================================
    # Data Export (for API responses)
    # ============================================================

    def get_initial_data(self) -> Dict[str, Any]:
        """Get all data for initial WebSocket connection."""
        return {
            "version": self._state.version,
            "recipes": self._recipes_to_dict(),
            "skills": self._skills_to_dict(),
            "community_recipes": self._community_recipes_to_dict(),
            "projects": self._projects_to_dict(),
        }

    def _recipes_to_dict(self) -> List[Dict[str, Any]]:
        """Convert recipes to dict for API response."""
        return [
            {
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "icon": r.icon,
                "tags": r.tags,
                "path": r.path,
                "source": r.source,
                "runtime": r.runtime,
            }
            for r in self._state.recipes
        ]

    def _skills_to_dict(self) -> List[Dict[str, Any]]:
        """Convert skills to dict for API response."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "file_path": s.file_path,
            }
            for s in self._state.skills
        ]

    def _community_recipes_to_dict(self) -> List[Dict[str, Any]]:
        """Convert community recipes to dict for API response."""
        return [
            {
                "name": r.name,
                "url": r.url,
                "description": r.description,
                "version": r.version,
                "type": r.type,
                "runtime": r.runtime,
                "tags": r.tags,
                "installed": r.installed,
                "installed_version": r.installed_version,
                "has_update": r.has_update,
            }
            for r in self._state.community_recipes
        ]

    def _projects_to_dict(self) -> List[Dict[str, Any]]:
        """Convert projects to dict for API response."""
        return [
            {
                "path": p.path,
                "name": p.name,
                "last_accessed": p.last_accessed.isoformat() if p.last_accessed else None,
            }
            for p in self._state.projects
        ]

    # ============================================================
    # Subscription & Broadcast
    # ============================================================

    # 订阅与 WS 传输已抽到 state/broadcaster.StateBroadcaster；以下为门面委托。
    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to state changes (delegates to StateBroadcaster).

        Args:
            callback: Function called with (data_type, data) on changes
        """
        self._broadcaster.subscribe(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Unsubscribe from state changes (delegates to StateBroadcaster)."""
        self._broadcaster.unsubscribe(callback)

    async def _broadcast(self, data_type: str, data: Any) -> None:
        """Broadcast state change to WebSocket clients.

        序列化在此（manager 持有 _*_to_dict），传输交给 broadcaster。
        """
        # Convert data to dict based on data_type
        # Note: data may be a list of dataclasses, not a dataclass itself
        if data_type == "recipes":
            payload = self._recipes_to_dict()
        elif data_type == "skills":
            payload = self._skills_to_dict()
        elif data_type == "projects":
            payload = self._projects_to_dict()
        else:
            payload = data

        await self._broadcaster.broadcast(data_type, self._state.version, payload)

    async def _broadcast_raw(self, msg_type: str, data: Any) -> None:
        """Broadcast raw data to WebSocket clients (delegates to StateBroadcaster)."""
        await self._broadcaster.broadcast_raw(msg_type, self._state.version, data)
