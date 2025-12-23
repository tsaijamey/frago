"""Dashboard API route for Frago Web Service.

Provides system overview data including:
- Server status and uptime
- Recent task activity
- Resource counts (tasks, recipes, skills)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.utils import get_server_state

router = APIRouter()


class ServerInfo(BaseModel):
    """Server status information."""
    running: bool
    uptime_seconds: float
    started_at: Optional[str] = None


class RecentActivity(BaseModel):
    """Recent activity item."""
    id: str
    type: str  # 'task', 'recipe_run'
    title: str
    status: str
    timestamp: str


class ResourceCounts(BaseModel):
    """Resource statistics."""
    tasks: int
    recipes: int
    skills: int


class DashboardData(BaseModel):
    """Complete dashboard data response."""
    server: ServerInfo
    recent_activity: list[RecentActivity]
    resource_counts: ResourceCounts


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard():
    """Get dashboard overview data.

    Returns server status, recent activity, and resource counts.
    """
    # Get server state
    server_state = get_server_state()
    uptime_seconds = 0.0
    if server_state.get("started_at"):
        try:
            started = datetime.fromisoformat(server_state["started_at"].replace("Z", "+00:00"))
            uptime_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        except (ValueError, AttributeError):
            pass

    # Get recent tasks
    from frago.session.storage import list_sessions
    recent_activity: list[RecentActivity] = []

    try:
        tasks = list_sessions(limit=5)
        for task in tasks:
            recent_activity.append(RecentActivity(
                id=task.session_id,
                type="task",
                title=task.name or "Unknown Task",
                status=task.status.value if task.status else "unknown",
                timestamp=task.started_at.isoformat() if task.started_at else "",
            ))
    except Exception:
        pass  # Continue with empty activity

    # Get resource counts using the adapter
    from frago.server.adapter import FragoApiAdapter
    adapter = FragoApiAdapter.get_instance()

    try:
        recipes = adapter.get_recipes()
        recipe_count = len(recipes) if recipes else 0
    except Exception:
        recipe_count = 0

    try:
        skills = adapter.get_skills()
        skill_count = len(skills) if skills else 0
    except Exception:
        skill_count = 0

    try:
        all_tasks = list_sessions(limit=1000)
        task_count = len(all_tasks) if all_tasks else 0
    except Exception:
        task_count = 0

    return DashboardData(
        server=ServerInfo(
            running=True,
            uptime_seconds=uptime_seconds,
            started_at=server_state.get("started_at"),
        ),
        recent_activity=recent_activity,
        resource_counts=ResourceCounts(
            tasks=task_count,
            recipes=recipe_count,
            skills=skill_count,
        ),
    )
