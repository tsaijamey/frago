"""Unified cache service for data preloading and WebSocket broadcast.

Provides centralized cache management for all data types with:
- Startup preloading for instant frontend access
- WebSocket broadcast on data changes
- Version tracking for incremental updates
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CacheService:
    """Unified cache for all data types with WebSocket broadcast."""

    _instance: Optional["CacheService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the cache service."""
        self._tasks_cache: Optional[Dict[str, Any]] = None
        self._dashboard_cache: Optional[Dict[str, Any]] = None
        self._recipes_cache: Optional[List[Dict[str, Any]]] = None
        self._skills_cache: Optional[List[Dict[str, Any]]] = None
        self._community_recipes_cache: Optional[List[Dict[str, Any]]] = None

        self._version: int = 0
        self._initialized: bool = False
        self._async_lock: Optional[asyncio.Lock] = None

    @classmethod
    def get_instance(cls) -> "CacheService":
        """Get singleton instance.

        Returns:
            CacheService instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_async_lock(self) -> asyncio.Lock:
        """Get or create async lock for the current event loop."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def initialize(self) -> None:
        """Preload all data at startup.

        This should be called during application lifespan startup.
        """
        if self._initialized:
            logger.debug("Cache already initialized")
            return

        logger.info("Initializing cache service...")
        start_time = datetime.now()

        async with self._get_async_lock():
            # Load all data concurrently using thread pool
            loop = asyncio.get_event_loop()

            tasks_future = loop.run_in_executor(None, self._load_tasks)
            recipes_future = loop.run_in_executor(None, self._load_recipes)
            skills_future = loop.run_in_executor(None, self._load_skills)

            self._tasks_cache, self._recipes_cache, self._skills_cache = await asyncio.gather(
                tasks_future, recipes_future, skills_future
            )

            # Compute dashboard from loaded data
            self._dashboard_cache = await loop.run_in_executor(
                None, self._compute_dashboard
            )

            self._version += 1
            self._initialized = True

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"Cache initialized in {duration:.2f}s: "
            f"tasks={self._tasks_cache.get('total', 0) if self._tasks_cache else 0}, "
            f"recipes={len(self._recipes_cache) if self._recipes_cache else 0}, "
            f"skills={len(self._skills_cache) if self._skills_cache else 0}"
        )

    def is_initialized(self) -> bool:
        """Check if cache is ready.

        Returns:
            True if cache is initialized and ready to serve.
        """
        return self._initialized

    def _load_tasks(self) -> Dict[str, Any]:
        """Load tasks from session storage (runs in thread pool).

        Returns:
            Tasks dictionary with 'tasks' list and 'total' count.
        """
        try:
            from frago.server.services.task_service import TaskService
            return TaskService.get_tasks(limit=100, offset=0, generate_titles=False)
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            return {"tasks": [], "total": 0}

    def _load_recipes(self) -> List[Dict[str, Any]]:
        """Load recipes (runs in thread pool).

        Returns:
            List of recipe dictionaries.
        """
        try:
            from frago.server.services.recipe_service import RecipeService
            return RecipeService.get_recipes(force_reload=True)
        except Exception as e:
            logger.error(f"Failed to load recipes: {e}")
            return []

    def _load_skills(self) -> List[Dict[str, Any]]:
        """Load skills (runs in thread pool).

        Returns:
            List of skill dictionaries.
        """
        try:
            from frago.server.services.skill_service import SkillService
            return SkillService.get_skills(force_reload=True)
        except Exception as e:
            logger.error(f"Failed to load skills: {e}")
            return []

    def _compute_dashboard(self) -> Dict[str, Any]:
        """Compute dashboard data from cached data.

        Returns:
            Dashboard data dictionary.
        """
        try:
            from frago.server.utils import get_server_state
            from frago.session.models import SessionStatus
            from frago.session.storage import list_sessions

            # Get server state
            server_state = get_server_state()
            uptime_seconds = 0.0
            if server_state.get("started_at"):
                try:
                    started = datetime.fromisoformat(
                        server_state["started_at"].replace("Z", "+00:00")
                    )
                    uptime_seconds = (datetime.now(timezone.utc) - started).total_seconds()
                except (ValueError, AttributeError):
                    pass

            # Get activity data
            now = datetime.now(timezone.utc)
            time_range_ago = now - timedelta(hours=12)

            # Initialize hourly buckets
            hourly_data: Dict[str, Dict] = {}
            for i in range(12):
                hour_start = now - timedelta(hours=11 - i)
                hour_start = hour_start.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_start.isoformat()] = {
                    "session_count": 0,
                    "tool_call_count": 0,
                    "completed_count": 0,
                }

            # Get sessions
            try:
                all_sessions = list_sessions(limit=1000)
            except Exception:
                all_sessions = []

            def normalize_dt(dt: datetime) -> datetime:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)

            # Filter recent sessions
            recent_sessions = []
            for s in all_sessions:
                last_activity = normalize_dt(s.last_activity)
                is_running = s.status == SessionStatus.RUNNING
                if last_activity >= time_range_ago or is_running:
                    recent_sessions.append(s)

            # Aggregate statistics
            stats = {
                "total_sessions": len(recent_sessions),
                "completed_sessions": sum(
                    1 for s in recent_sessions if s.status == SessionStatus.COMPLETED
                ),
                "running_sessions": sum(
                    1 for s in recent_sessions if s.status == SessionStatus.RUNNING
                ),
                "error_sessions": sum(
                    1 for s in recent_sessions if s.status == SessionStatus.ERROR
                ),
                "total_tool_calls": sum(s.tool_call_count for s in recent_sessions),
                "total_steps": sum(s.step_count for s in recent_sessions),
            }

            # Fill hourly buckets
            for session in recent_sessions:
                last_activity = normalize_dt(session.last_activity)
                session_hour = last_activity.replace(minute=0, second=0, microsecond=0)
                hour_key = session_hour.isoformat()
                if hour_key in hourly_data:
                    hourly_data[hour_key]["session_count"] += 1
                    hourly_data[hour_key]["tool_call_count"] += session.tool_call_count
                    if session.status == SessionStatus.COMPLETED:
                        hourly_data[hour_key]["completed_count"] += 1

            hourly_distribution = [
                {"hour": hour, **data}
                for hour, data in sorted(hourly_data.items())
            ]

            return {
                "server": {
                    "running": True,
                    "uptime_seconds": uptime_seconds,
                    "started_at": server_state.get("started_at"),
                },
                "activity_overview": {
                    "hourly_distribution": hourly_distribution,
                    "stats": stats,
                },
                "resource_counts": {
                    "tasks": len(all_sessions),
                    "recipes": (
                        (len(self._recipes_cache) if self._recipes_cache else 0)
                        + len([r for r in (self._community_recipes_cache or []) if r.get("installed")])
                    ),
                    "skills": len(self._skills_cache) if self._skills_cache else 0,
                },
            }
        except Exception as e:
            logger.error(f"Failed to compute dashboard: {e}")
            return {
                "server": {"running": True, "uptime_seconds": 0, "started_at": None},
                "activity_overview": {"hourly_distribution": [], "stats": {}},
                "resource_counts": {"tasks": 0, "recipes": 0, "skills": 0},
            }

    async def get_tasks(self) -> Dict[str, Any]:
        """Get cached task list.

        Returns:
            Tasks dictionary with 'tasks' list and 'total' count.
        """
        if not self._initialized or self._tasks_cache is None:
            return {"tasks": [], "total": 0}
        return self._tasks_cache

    async def get_dashboard(self) -> Dict[str, Any]:
        """Get cached dashboard data.

        Returns:
            Dashboard data dictionary.
        """
        if not self._initialized or self._dashboard_cache is None:
            return {
                "server": {"running": True, "uptime_seconds": 0, "started_at": None},
                "activity_overview": {"hourly_distribution": [], "stats": {}},
                "resource_counts": {"tasks": 0, "recipes": 0, "skills": 0},
            }
        return self._dashboard_cache

    async def get_recipes(self) -> List[Dict[str, Any]]:
        """Get cached recipes.

        Returns:
            List of recipe dictionaries.
        """
        if not self._initialized or self._recipes_cache is None:
            return []
        return self._recipes_cache

    async def get_skills(self) -> List[Dict[str, Any]]:
        """Get cached skills.

        Returns:
            List of skill dictionaries.
        """
        if not self._initialized or self._skills_cache is None:
            return []
        return self._skills_cache

    async def get_community_recipes(self) -> List[Dict[str, Any]]:
        """Get cached community recipes.

        Returns:
            List of community recipe dictionaries.
        """
        if self._community_recipes_cache is None:
            return []
        return self._community_recipes_cache

    def set_community_recipes(self, recipes: List[Dict[str, Any]]) -> None:
        """Update community recipes cache.

        Called by CommunityRecipeService when new data is fetched.

        Args:
            recipes: List of community recipe dictionaries.
        """
        self._community_recipes_cache = recipes

    async def get_initial_data(self) -> Dict[str, Any]:
        """Get all cached data for initial WebSocket connection.

        Returns:
            Dictionary containing all cached data and version.
        """
        return {
            "version": self._version,
            "tasks": await self.get_tasks(),
            "dashboard": await self.get_dashboard(),
            "recipes": await self.get_recipes(),
            "skills": await self.get_skills(),
            "community_recipes": await self.get_community_recipes(),
        }

    async def refresh_tasks(self, broadcast: bool = True) -> None:
        """Refresh task cache and optionally broadcast update.

        Args:
            broadcast: If True, broadcast update via WebSocket.
        """
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._tasks_cache = await loop.run_in_executor(None, self._load_tasks)
            self._dashboard_cache = await loop.run_in_executor(
                None, self._compute_dashboard
            )
            self._version += 1

        if broadcast:
            await self._broadcast_update("data_tasks", self._tasks_cache)
            await self._broadcast_update("data_dashboard", self._dashboard_cache)

        logger.debug(f"Tasks cache refreshed, version={self._version}")

    async def refresh_recipes(self, broadcast: bool = True) -> None:
        """Refresh recipe cache and optionally broadcast update.

        Args:
            broadcast: If True, broadcast update via WebSocket.
        """
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._recipes_cache = await loop.run_in_executor(None, self._load_recipes)
            self._version += 1

        if broadcast:
            await self._broadcast_update("data_recipes", self._recipes_cache)

        logger.debug(f"Recipes cache refreshed, version={self._version}")

    async def refresh_skills(self, broadcast: bool = True) -> None:
        """Refresh skill cache and optionally broadcast update.

        Args:
            broadcast: If True, broadcast update via WebSocket.
        """
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._skills_cache = await loop.run_in_executor(None, self._load_skills)
            self._version += 1

        if broadcast:
            await self._broadcast_update("data_skills", self._skills_cache)

        logger.debug(f"Skills cache refreshed, version={self._version}")

    async def refresh_all(self, broadcast: bool = True) -> None:
        """Refresh all caches.

        Args:
            broadcast: If True, broadcast updates via WebSocket.
        """
        await self.refresh_tasks(broadcast=False)
        await self.refresh_recipes(broadcast=False)
        await self.refresh_skills(broadcast=False)

        if broadcast:
            await self._broadcast_update("data_initial", await self.get_initial_data())

    async def _broadcast_update(self, msg_type: str, data: Any) -> None:
        """Broadcast data update via WebSocket.

        Args:
            msg_type: Message type identifier.
            data: Data to broadcast.
        """
        try:
            from frago.server.websocket import manager, create_message

            message = create_message(msg_type, {"version": self._version, "data": data})
            await manager.broadcast(message)
            logger.debug(f"Broadcast {msg_type} to {manager.connection_count} clients")
        except Exception as e:
            logger.warning(f"Failed to broadcast {msg_type}: {e}")
