"""Dashboard API route for Frago Web Service.

Provides the redesigned dashboard data:
- Running tasks (real-time via WebSocket)
- Recent completed/failed tasks
- Quick recipes (sorted by recent usage)
- Resource counts
- System status (Chrome, tabs, errors, sync)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.state import StateManager

router = APIRouter()


# ============================================================
# New Dashboard Models
# ============================================================


class RunningTaskSummary(BaseModel):
    """Summary of a currently running task."""

    id: str
    name: Optional[str] = None
    project_path: str = ""
    started_at: str = ""
    elapsed_seconds: float = 0.0
    current_step: Optional[str] = None
    step_count: int = 0


class RecentTaskSummary(BaseModel):
    """Summary of a recently completed/failed task."""

    id: str
    name: Optional[str] = None
    status: str = "completed"
    duration_ms: Optional[int] = None
    ended_at: Optional[str] = None
    error_summary: Optional[str] = None


class QuickRecipeItem(BaseModel):
    """Recipe item for quick access on dashboard."""

    name: str
    description: Optional[str] = None
    runtime: Optional[str] = None
    run_count: int = 0
    last_used: Optional[str] = None


class ResourceCounts(BaseModel):
    """Resource statistics."""

    tasks: int = 0
    recipes: int = 0
    skills: int = 0


class DashboardStatus(BaseModel):
    """System status for dashboard footer."""

    chrome_connected: bool = False
    tab_count: int = 0
    error_count: int = 0
    last_synced_at: Optional[str] = None


class DashboardData(BaseModel):
    """Complete dashboard data response."""

    running_tasks: list[RunningTaskSummary] = []
    recent_tasks: list[RecentTaskSummary] = []
    quick_recipes: list[QuickRecipeItem] = []
    resource_counts: ResourceCounts = ResourceCounts()
    system_status: DashboardStatus = DashboardStatus()


# ============================================================
# Dashboard Computation
# ============================================================


def compute_dashboard_data() -> DashboardData:
    """Compute full dashboard data from services.

    This is the single source of truth for dashboard data,
    used by both the HTTP endpoint and the WebSocket push.
    """
    import logging

    from frago.session.models import AgentType, SessionStatus
    from frago.session.storage import list_sessions

    logger = logging.getLogger(__name__)
    now = datetime.now(timezone.utc)

    # ------- Running Tasks -------
    running_tasks: list[RunningTaskSummary] = []
    try:
        from frago.server.services.task_service import TaskService
        from frago.session.title_manager import get_title_manager

        title_manager = get_title_manager()
        running_sessions = list_sessions(
            agent_type=AgentType.CLAUDE,
            status=SessionStatus.RUNNING,
            limit=20,
        )

        for session in running_sessions:
            name = title_manager.get_title(session.session_id)
            if not name:
                name = getattr(session, "name", None) or f"Task {session.session_id[:8]}"

            started_at = getattr(session, "started_at", None)
            elapsed = 0.0
            started_at_str = ""
            if started_at:
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                elapsed = (now - started_at).total_seconds()
                started_at_str = started_at.isoformat()

            # Get current step (latest step)
            current_step = None
            try:
                from frago.session.storage import read_steps_paginated
                steps_result = read_steps_paginated(
                    session.session_id, AgentType.CLAUDE, limit=1, offset=0, from_end=True
                )
                steps = steps_result.get("steps", [])
                if steps:
                    step = steps[0]
                    tool_name = getattr(step, "tool_name", None)
                    if tool_name:
                        current_step = tool_name
                    else:
                        content = getattr(step, "content_summary", "") or ""
                        if content:
                            current_step = content[:50]
            except Exception:
                pass

            running_tasks.append(RunningTaskSummary(
                id=session.session_id,
                name=name,
                project_path=getattr(session, "project_path", "") or "",
                started_at=started_at_str,
                elapsed_seconds=elapsed,
                current_step=current_step,
                step_count=getattr(session, "step_count", 0),
            ))
    except Exception as e:
        logger.error("Failed to compute running tasks: %s", e)

    # ------- Recent Tasks -------
    recent_tasks: list[RecentTaskSummary] = []
    try:
        from frago.server.services.task_service import TaskService
        from frago.session.title_manager import get_title_manager

        title_manager = get_title_manager()
        all_sessions = list_sessions(
            agent_type=AgentType.CLAUDE,
            limit=50,
        )

        for session in all_sessions:
            if session.status == SessionStatus.RUNNING:
                continue

            # Skip excluded sessions
            if title_manager.is_excluded_session(session.session_id):
                continue

            name = title_manager.get_title(session.session_id)
            if not name:
                name = getattr(session, "name", None)
            if not name:
                name = None  # Frontend will show "Untitled task"

            ended_at = getattr(session, "ended_at", None)
            ended_at_str = ended_at.isoformat() if ended_at else None

            started_at = getattr(session, "started_at", None)
            duration_ms = None
            if started_at and ended_at:
                duration_ms = int((ended_at - started_at).total_seconds() * 1000)

            error_summary = None
            status_val = session.status.value if session.status else "completed"
            if status_val == "error":
                error_summary = TaskService.extract_error_summary(session.session_id)

            recent_tasks.append(RecentTaskSummary(
                id=session.session_id,
                name=name,
                status=status_val,
                duration_ms=duration_ms,
                ended_at=ended_at_str,
                error_summary=error_summary,
            ))

            if len(recent_tasks) >= 5:
                break
    except Exception as e:
        logger.error("Failed to compute recent tasks: %s", e)

    # ------- Quick Recipes -------
    quick_recipes: list[QuickRecipeItem] = []
    try:
        from frago.recipes.usage_tracker import get_top_recipes, get_usage
        from frago.server.services.recipe_service import RecipeService

        top_names = get_top_recipes(limit=5)

        if top_names:
            all_recipes = RecipeService.get_recipes()
            recipe_map = {r.get("name", ""): r for r in all_recipes}

            for name in top_names:
                recipe = recipe_map.get(name)
                if recipe:
                    usage = get_usage(name)
                    quick_recipes.append(QuickRecipeItem(
                        name=name,
                        description=recipe.get("description"),
                        runtime=recipe.get("runtime"),
                        run_count=usage.get("run_count", 0),
                        last_used=usage.get("last_used"),
                    ))
        else:
            # Fallback: first 5 recipes
            all_recipes = RecipeService.get_recipes()
            for r in all_recipes[:5]:
                quick_recipes.append(QuickRecipeItem(
                    name=r.get("name", ""),
                    description=r.get("description"),
                    runtime=r.get("runtime"),
                    run_count=0,
                    last_used=None,
                ))
    except Exception as e:
        logger.error("Failed to compute quick recipes: %s", e)

    # ------- Resource Counts -------
    resource_counts = ResourceCounts()
    try:
        from frago.recipes.installer import RecipeInstaller
        from frago.server.services.recipe_service import RecipeService
        from frago.server.services.skill_service import SkillService

        recipes = RecipeService.get_recipes()
        recipe_count = len(recipes) if recipes else 0
        try:
            installer = RecipeInstaller()
            community_installed = installer.list_installed()
            recipe_count += len(community_installed)
        except Exception:
            pass

        skills = SkillService.get_skills()
        skill_count = len(skills) if skills else 0

        all_tasks = list_sessions(limit=1000)
        task_count = len(all_tasks) if all_tasks else 0

        resource_counts = ResourceCounts(
            tasks=task_count,
            recipes=recipe_count,
            skills=skill_count,
        )
    except Exception as e:
        logger.error("Failed to compute resource counts: %s", e)

    # ------- System Status -------
    system_status = DashboardStatus()
    try:
        from frago.server.services.system_service import SystemService

        status = SystemService.get_status()
        chrome_connected = status.get("chrome_connected", False)
        tab_count = status.get("tab_count", 0)

        # Error count: sessions with error status in last 12h
        error_count = 0
        try:
            time_range_ago = now - timedelta(hours=12)
            for session in list_sessions(limit=1000):
                if session.status == SessionStatus.ERROR:
                    last_activity = session.last_activity
                    if last_activity:
                        if last_activity.tzinfo is None:
                            last_activity = last_activity.replace(tzinfo=timezone.utc)
                        if last_activity >= time_range_ago:
                            error_count += 1
        except Exception:
            pass

        # Last synced time
        last_synced_at = None
        try:
            from frago.tools.sync_repo import get_last_synced_at
            last_synced_at = get_last_synced_at()
        except Exception:
            pass

        system_status = DashboardStatus(
            chrome_connected=chrome_connected,
            tab_count=tab_count,
            error_count=error_count,
            last_synced_at=last_synced_at,
        )
    except Exception as e:
        logger.error("Failed to compute system status: %s", e)

    return DashboardData(
        running_tasks=running_tasks,
        recent_tasks=recent_tasks,
        quick_recipes=quick_recipes,
        resource_counts=resource_counts,
        system_status=system_status,
    )


# ============================================================
# API Endpoint
# ============================================================


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard():
    """Get dashboard overview data.

    Returns running tasks, recent tasks, quick recipes,
    resource counts, and system status.
    """
    state_manager = StateManager.get_instance()

    if state_manager.is_initialized():
        dashboard = state_manager.get_dashboard()
        # Dashboard is stored as the new DashboardData dict structure
        return DashboardData(
            running_tasks=[
                RunningTaskSummary(**t) for t in dashboard.running_tasks
            ],
            recent_tasks=[
                RecentTaskSummary(**t) for t in dashboard.recent_tasks
            ],
            quick_recipes=[
                QuickRecipeItem(**r) for r in dashboard.quick_recipes
            ],
            resource_counts=ResourceCounts(
                tasks=dashboard.resource_counts.tasks,
                recipes=dashboard.resource_counts.recipes,
                skills=dashboard.resource_counts.skills,
            ),
            system_status=DashboardStatus(
                chrome_connected=dashboard.system_status.chrome_connected,
                tab_count=dashboard.system_status.tab_count,
                error_count=dashboard.system_status.error_count,
                last_synced_at=dashboard.system_status.last_synced_at,
            ),
        )

    # Fallback: compute directly
    return compute_dashboard_data()
