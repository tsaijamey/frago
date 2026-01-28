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
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from frago.server.state.models import (
    CommunityRecipe,
    DashboardData,
    Project,
    Recipe,
    ResourceCounts,
    ServerState,
    ServerStatus,
    Skill,
    TaskDetail,
    TaskItem,
    TaskStep,
    TaskSummary,
    ToolUsageStat,
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
        self._subscribers: List[Callable[[str, Any], None]] = []

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
            tasks_future = loop.run_in_executor(None, self._load_tasks)
            recipes_future = loop.run_in_executor(None, self._load_recipes)
            skills_future = loop.run_in_executor(None, self._load_skills)
            projects_future = loop.run_in_executor(None, self._load_projects)

            tasks_data, recipes_data, skills_data, projects_data = await asyncio.gather(
                tasks_future, recipes_future, skills_future, projects_future
            )

            self._state.tasks = tasks_data.get("tasks", [])
            self._state.tasks_total = tasks_data.get("total", 0)
            self._state.recipes = recipes_data
            self._state.skills = skills_data
            self._state.projects = projects_data

            # Compute dashboard
            self._state.dashboard = await loop.run_in_executor(
                None, self._compute_dashboard
            )

            self._state.version += 1
            self._state.last_updated = datetime.now(timezone.utc)
            self._initialized = True

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(
            f"State initialized in {duration:.2f}s: "
            f"tasks={len(self._state.tasks)}, "
            f"recipes={len(self._state.recipes)}, "
            f"skills={len(self._state.skills)}, "
            f"projects={len(self._state.projects)}"
        )

    # ============================================================
    # Data Loading (internal)
    # ============================================================

    def _load_tasks(self) -> Dict[str, Any]:
        """Load tasks from session storage."""
        try:
            from frago.server.services.task_service import TaskService

            result = TaskService.get_tasks(limit=100, offset=0)
            tasks = []
            for t in result.get("tasks", []):
                tasks.append(
                    TaskItem(
                        id=t.get("id", ""),
                        title=t.get("title", ""),
                        status=t.get("status", "running"),
                        project_path=t.get("project_path"),
                        agent_type=t.get("agent_type", "claude"),
                        started_at=self._parse_datetime(t.get("started_at")),
                        completed_at=self._parse_datetime(t.get("completed_at")),
                        duration_ms=t.get("duration_ms"),
                        step_count=t.get("step_count", 0),
                        tool_call_count=t.get("tool_call_count", 0),
                        source=t.get("source", "unknown"),
                    )
                )
            return {"tasks": tasks, "total": result.get("total", len(tasks))}
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            return {"tasks": [], "total": 0}

    def _load_task_detail(self, task_id: str) -> Optional[TaskDetail]:
        """Load task detail from session storage."""
        try:
            from frago.server.services.task_service import TaskService

            task = TaskService.get_task(task_id)
            if task is None:
                return None

            steps = []
            for s in task.get("steps", []):
                steps.append(
                    TaskStep(
                        timestamp=self._parse_datetime(s.get("timestamp"))
                        or datetime.now(timezone.utc),
                        type=s.get("type", "assistant"),
                        content=s.get("content", ""),
                        tool_name=s.get("tool_name"),
                        tool_call_id=s.get("tool_call_id"),
                        tool_result=s.get("tool_result"),
                    )
                )

            summary = None
            if task.get("summary"):
                s = task["summary"]
                most_used_tools = []
                for t in s.get("most_used_tools", []):
                    if hasattr(t, "tool_name"):
                        most_used_tools.append(ToolUsageStat(name=t.tool_name, count=t.count))
                    else:
                        most_used_tools.append(
                            ToolUsageStat(name=t.get("name", ""), count=t.get("count", 0))
                        )
                summary = TaskSummary(
                    total_duration_ms=s.get("total_duration_ms", 0),
                    user_message_count=s.get("user_message_count", 0),
                    assistant_message_count=s.get("assistant_message_count", 0),
                    tool_call_count=s.get("tool_call_count", 0),
                    tool_success_count=s.get("tool_success_count", 0),
                    tool_error_count=s.get("tool_error_count", 0),
                    most_used_tools=most_used_tools,
                )

            return TaskDetail(
                id=task.get("id", task_id),
                title=task.get("title", ""),
                status=task.get("status", "running"),
                project_path=task.get("project_path"),
                started_at=self._parse_datetime(task.get("started_at")),
                completed_at=self._parse_datetime(task.get("completed_at")),
                duration_ms=task.get("duration_ms"),
                step_count=task.get("step_count", len(steps)),
                tool_call_count=task.get("tool_call_count", 0),
                steps=steps,
                steps_total=task.get("steps_total", len(steps)),
                steps_offset=task.get("steps_offset", 0),
                has_more_steps=task.get("has_more_steps", False),
                summary=summary,
            )
        except Exception as e:
            logger.error(f"Failed to load task detail {task_id}: {e}")
            return None

    def _load_recipes(self) -> List[Recipe]:
        """Load recipes from storage."""
        try:
            from frago.server.services.recipe_service import RecipeService

            raw_recipes = RecipeService.get_recipes(force_reload=True)
            recipes = []
            for r in raw_recipes:
                recipes.append(
                    Recipe(
                        name=r.get("name", ""),
                        description=r.get("description"),
                        category=r.get("category", "atomic"),
                        icon=r.get("icon"),
                        tags=r.get("tags", []),
                        path=r.get("path"),
                        source=r.get("source"),
                        runtime=r.get("runtime"),
                    )
                )
            return recipes
        except Exception as e:
            logger.error(f"Failed to load recipes: {e}")
            return []

    def _load_skills(self) -> List[Skill]:
        """Load skills from storage."""
        try:
            from frago.server.services.skill_service import SkillService

            raw_skills = SkillService.get_skills(force_reload=True)
            skills = []
            for s in raw_skills:
                skills.append(
                    Skill(
                        name=s.get("name", ""),
                        description=s.get("description"),
                        file_path=s.get("file_path"),
                    )
                )
            return skills
        except Exception as e:
            logger.error(f"Failed to load skills: {e}")
            return []

    def _load_projects(self) -> List[Project]:
        """Load projects from storage."""
        try:
            from datetime import datetime
            from pathlib import Path

            from frago.server.services.file_service import FileService

            projects_dir = Path.home() / ".frago" / "projects"
            raw_projects = FileService.list_projects()
            projects = []
            for p in raw_projects:
                # Parse last_accessed from ISO format string to datetime
                last_accessed = None
                if p.last_accessed:
                    try:
                        last_accessed = datetime.fromisoformat(p.last_accessed)
                    except (ValueError, TypeError):
                        pass

                projects.append(
                    Project(
                        path=str(projects_dir / p.run_id),
                        name=p.theme_description or p.run_id,
                        last_accessed=last_accessed,
                    )
                )
            return projects
        except Exception as e:
            logger.error(f"Failed to load projects: {e}")
            return []

    def _load_config(self) -> Dict[str, Any]:
        """Load main config from storage."""
        try:
            from frago.server.services.main_config_service import MainConfigService

            return MainConfigService.get_config()
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return {}

    def _load_env_vars(self) -> Dict[str, Any]:
        """Load environment variables from storage."""
        try:
            from frago.server.services.env_service import EnvService

            return EnvService.get_env_vars()
        except Exception as e:
            logger.error(f"Failed to load env vars: {e}")
            return {"vars": {}, "file_exists": False}

    def _load_recipe_env_requirements(self) -> List[Dict[str, Any]]:
        """Load recipe environment requirements from storage."""
        try:
            from frago.server.services.env_service import EnvService

            return EnvService.get_recipe_env_requirements()
        except Exception as e:
            logger.error(f"Failed to load recipe env requirements: {e}")
            return []

    def _load_gh_status(self) -> Dict[str, Any]:
        """Load GitHub CLI status."""
        try:
            from frago.server.services.github_service import GitHubService

            return GitHubService.check_gh_cli()
        except Exception as e:
            logger.error(f"Failed to load gh status: {e}")
            return {"installed": False, "authenticated": False, "username": None}

    def _compute_dashboard(self) -> DashboardData:
        """Compute dashboard data from current state."""
        try:
            from frago.server.utils import get_server_state
            from frago.session.models import SessionStatus
            from frago.session.storage import list_sessions

            # Server status
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

            server_status = ServerStatus(
                running=True,
                uptime_seconds=uptime_seconds,
                started_at=server_state.get("started_at"),
            )

            # Activity data
            now = datetime.now(timezone.utc)
            time_range_ago = now - timedelta(hours=12)

            hourly_data: Dict[str, Dict] = {}
            for i in range(12):
                hour_start = now - timedelta(hours=11 - i)
                hour_start = hour_start.replace(minute=0, second=0, microsecond=0)
                hourly_data[hour_start.isoformat()] = {
                    "session_count": 0,
                    "tool_call_count": 0,
                    "completed_count": 0,
                }

            try:
                all_sessions = list_sessions(limit=1000)
            except Exception:
                all_sessions = []

            def normalize_dt(dt: datetime) -> datetime:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)

            recent_sessions = []
            for s in all_sessions:
                last_activity = normalize_dt(s.last_activity)
                is_running = s.status == SessionStatus.RUNNING
                if last_activity >= time_range_ago or is_running:
                    recent_sessions.append(s)

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
                {"hour": hour, **data} for hour, data in sorted(hourly_data.items())
            ]

            # Resource counts
            installed_community = len(
                [r for r in self._state.community_recipes if r.installed]
            )
            resource_counts = ResourceCounts(
                tasks=len(all_sessions),
                recipes=len(self._state.recipes) + installed_community,
                skills=len(self._state.skills),
            )

            return DashboardData(
                server=server_status,
                activity_overview={
                    "hourly_distribution": hourly_distribution,
                    "stats": stats,
                },
                resource_counts=resource_counts,
            )
        except Exception as e:
            logger.error(f"Failed to compute dashboard: {e}")
            return DashboardData()

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        """Parse datetime from string or return as-is if already datetime."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    # ============================================================
    # Data Access (public)
    # ============================================================

    def get_tasks(self) -> List[TaskItem]:
        """Get task list."""
        return self._state.tasks

    def get_tasks_total(self) -> int:
        """Get total task count."""
        return self._state.tasks_total

    def get_task_detail(self, task_id: str) -> Optional[TaskDetail]:
        """Get task detail, loading from storage if not cached."""
        if task_id in self._state.task_details:
            return self._state.task_details[task_id]

        # Load and cache
        detail = self._load_task_detail(task_id)
        if detail:
            self._state.task_details[task_id] = detail
        return detail

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

    def get_dashboard(self) -> DashboardData:
        """Get dashboard data."""
        return self._state.dashboard

    def get_config(self) -> Dict[str, Any]:
        """Get user config, loading on first access."""
        if not self._state.config or self._state.config == UserConfig():
            self._state.config = self._load_config()  # type: ignore
        # Return as dict for API compatibility
        if isinstance(self._state.config, dict):
            return self._state.config
        return {}

    def get_env_vars(self) -> Dict[str, Any]:
        """Get environment variables, loading on first access."""
        if not self._state.env_vars:
            self._state.env_vars = self._load_env_vars()
        return self._state.env_vars

    def get_recipe_env_requirements(self) -> List[Dict[str, Any]]:
        """Get recipe environment requirements, loading on first access."""
        if not self._state.recipe_env_requirements:
            self._state.recipe_env_requirements = self._load_recipe_env_requirements()
        return self._state.recipe_env_requirements

    def get_gh_status(self) -> Dict[str, Any]:
        """Get GitHub CLI status, loading on first access."""
        if not self._state.gh_status:
            self._state.gh_status = self._load_gh_status()
        return self._state.gh_status

    # ============================================================
    # Data Refresh (public)
    # ============================================================

    async def refresh_tasks(self, broadcast: bool = True) -> None:
        """Refresh task data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            tasks_data = await loop.run_in_executor(None, self._load_tasks)
            self._state.tasks = tasks_data.get("tasks", [])
            self._state.tasks_total = tasks_data.get("total", 0)
            # Clear cached task details
            self._state.task_details.clear()
            # Update dashboard
            self._state.dashboard = await loop.run_in_executor(
                None, self._compute_dashboard
            )
            self._state.version += 1
            self._state.last_updated = datetime.now(timezone.utc)

        if broadcast:
            await self._broadcast("tasks", self._state.tasks)
            await self._broadcast("dashboard", self._state.dashboard)

        logger.debug(f"Tasks refreshed, version={self._state.version}")

    async def refresh_task_detail(self, task_id: str, broadcast: bool = True) -> Optional[TaskDetail]:
        """Refresh specific task detail."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            detail = await loop.run_in_executor(None, self._load_task_detail, task_id)
            if detail:
                self._state.task_details[task_id] = detail
                self._state.version += 1
            elif task_id in self._state.task_details:
                del self._state.task_details[task_id]

        if broadcast and detail:
            await self._broadcast("task_detail", {"task_id": task_id, "detail": detail})

        return detail

    async def refresh_recipes(self, broadcast: bool = True) -> None:
        """Refresh recipe data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.recipes = await loop.run_in_executor(None, self._load_recipes)
            self._state.version += 1
            self._state.last_updated = datetime.now(timezone.utc)

        if broadcast:
            await self._broadcast("recipes", self._state.recipes)

        logger.debug(f"Recipes refreshed, version={self._state.version}")

    async def refresh_skills(self, broadcast: bool = True) -> None:
        """Refresh skill data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.skills = await loop.run_in_executor(None, self._load_skills)
            self._state.version += 1
            self._state.last_updated = datetime.now(timezone.utc)

        if broadcast:
            await self._broadcast("skills", self._state.skills)

        logger.debug(f"Skills refreshed, version={self._state.version}")

    async def refresh_projects(self, broadcast: bool = True) -> None:
        """Refresh project data."""
        async with self._get_async_lock():
            loop = asyncio.get_event_loop()
            self._state.projects = await loop.run_in_executor(None, self._load_projects)
            self._state.version += 1
            self._state.last_updated = datetime.now(timezone.utc)

        if broadcast:
            await self._broadcast("projects", self._state.projects)

        logger.debug(f"Projects refreshed, version={self._state.version}")

    async def refresh_all(self, broadcast: bool = True) -> None:
        """Refresh all data."""
        await self.refresh_tasks(broadcast=False)
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

    async def refresh_env_vars(self, broadcast: bool = True) -> None:
        """Refresh environment variables."""
        loop = asyncio.get_event_loop()
        self._state.env_vars = await loop.run_in_executor(None, self._load_env_vars)
        self._state.version += 1

        if broadcast:
            await self._broadcast_raw("data_env_vars", self._state.env_vars)

        logger.debug("Env vars refreshed")

    async def refresh_recipe_env_requirements(self, broadcast: bool = True) -> None:
        """Refresh recipe environment requirements."""
        loop = asyncio.get_event_loop()
        self._state.recipe_env_requirements = await loop.run_in_executor(
            None, self._load_recipe_env_requirements
        )
        self._state.version += 1

        if broadcast:
            await self._broadcast_raw("data_recipe_env", self._state.recipe_env_requirements)

        logger.debug("Recipe env requirements refreshed")

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
            "tasks": {"tasks": self._tasks_to_dict(), "total": self._state.tasks_total},
            "dashboard": self._dashboard_to_dict(),
            "recipes": self._recipes_to_dict(),
            "skills": self._skills_to_dict(),
            "community_recipes": self._community_recipes_to_dict(),
            "projects": self._projects_to_dict(),
        }

    def _tasks_to_dict(self) -> List[Dict[str, Any]]:
        """Convert tasks to dict for API response."""
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "project_path": t.project_path,
                "agent_type": t.agent_type,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "duration_ms": t.duration_ms,
                "step_count": t.step_count,
                "tool_call_count": t.tool_call_count,
                "source": t.source,
            }
            for t in self._state.tasks
        ]

    def _dashboard_to_dict(self) -> Dict[str, Any]:
        """Convert dashboard to dict for API response."""
        d = self._state.dashboard
        return {
            "server": {
                "running": d.server.running,
                "uptime_seconds": d.server.uptime_seconds,
                "started_at": d.server.started_at,
            },
            "activity_overview": d.activity_overview,
            "resource_counts": {
                "tasks": d.resource_counts.tasks,
                "recipes": d.resource_counts.recipes,
                "skills": d.resource_counts.skills,
            },
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

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to state changes.

        Args:
            callback: Function called with (data_type, data) on changes
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Unsubscribe from state changes."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def _broadcast(self, data_type: str, data: Any) -> None:
        """Broadcast state change to WebSocket clients."""
        try:
            from frago.server.websocket import create_message, manager

            # Convert data to dict based on data_type
            # Note: data may be a list of dataclasses, not a dataclass itself
            if data_type == "tasks":
                payload = {"tasks": self._tasks_to_dict(), "total": self._state.tasks_total}
            elif data_type == "dashboard":
                payload = self._dashboard_to_dict()
            elif data_type == "recipes":
                payload = self._recipes_to_dict()
            elif data_type == "skills":
                payload = self._skills_to_dict()
            elif data_type == "projects":
                payload = self._projects_to_dict()
            else:
                payload = data

            message = create_message(
                f"data_{data_type}", {"version": self._state.version, "data": payload}
            )
            await manager.broadcast(message)
            logger.debug(f"Broadcast {data_type} to {manager.connection_count} clients")
        except Exception as e:
            logger.warning(f"Failed to broadcast {data_type}: {e}")

    async def _broadcast_raw(self, msg_type: str, data: Any) -> None:
        """Broadcast raw data to WebSocket clients (for dict data)."""
        try:
            from frago.server.websocket import create_message, manager

            message = create_message(msg_type, {"version": self._state.version, "data": data})
            await manager.broadcast(message)
            logger.debug(f"Broadcast {msg_type} to {manager.connection_count} clients")
        except Exception as e:
            logger.warning(f"Failed to broadcast {msg_type}: {e}")

        # Notify local subscribers
        for callback in self._subscribers:
            try:
                callback(msg_type, data)
            except Exception as e:
                logger.warning(f"Subscriber callback failed: {e}")
