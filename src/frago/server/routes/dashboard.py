"""Dashboard API route for Frago Web Service.

Provides system overview data including:
- Server status and uptime
- Activity overview (6-hour statistics and hourly distribution)
- Resource counts (tasks, recipes, skills)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from frago.server.services.cache_service import CacheService
from frago.server.utils import get_server_state
from frago.session.models import SessionStatus

router = APIRouter()


class ServerInfo(BaseModel):
    """Server status information."""
    running: bool
    uptime_seconds: float
    started_at: Optional[str] = None


class HourlyActivity(BaseModel):
    """Activity data for a single hour bucket."""
    hour: str  # ISO format hour start, e.g., "2025-12-24T14:00:00"
    session_count: int
    tool_call_count: int
    completed_count: int


class ActivityStats(BaseModel):
    """Aggregated activity statistics for past 12 hours."""
    total_sessions: int
    completed_sessions: int
    running_sessions: int
    error_sessions: int
    total_tool_calls: int
    total_steps: int


class ActivityOverview(BaseModel):
    """Complete activity overview for dashboard."""
    hourly_distribution: list[HourlyActivity]
    stats: ActivityStats


class ResourceCounts(BaseModel):
    """Resource statistics."""
    tasks: int
    recipes: int
    skills: int


class DashboardData(BaseModel):
    """Complete dashboard data response."""
    server: ServerInfo
    activity_overview: ActivityOverview
    resource_counts: ResourceCounts


def calculate_activity_overview() -> ActivityOverview:
    """Calculate activity statistics for the past 12 hours.

    Returns hourly distribution and aggregated stats.
    """
    from frago.session.storage import list_sessions

    now = datetime.now(timezone.utc)
    time_range_ago = now - timedelta(hours=12)

    # Initialize hourly buckets (12 hours, oldest first)
    hourly_data: dict[str, dict] = {}
    for i in range(12):
        hour_start = now - timedelta(hours=11 - i)
        hour_start = hour_start.replace(minute=0, second=0, microsecond=0)
        hourly_data[hour_start.isoformat()] = {
            "session_count": 0,
            "tool_call_count": 0,
            "completed_count": 0,
        }

    # Get all sessions and filter by time
    try:
        all_sessions = list_sessions(limit=1000)
    except Exception:
        all_sessions = []

    # Normalize timezone for comparison
    def normalize_dt(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # Filter sessions active in past 12 hours
    recent_sessions = []
    for s in all_sessions:
        last_activity = normalize_dt(s.last_activity)
        is_running = s.status == SessionStatus.RUNNING
        if last_activity >= time_range_ago or is_running:
            recent_sessions.append(s)

    # Aggregate statistics
    stats = ActivityStats(
        total_sessions=len(recent_sessions),
        completed_sessions=sum(
            1 for s in recent_sessions if s.status == SessionStatus.COMPLETED
        ),
        running_sessions=sum(
            1 for s in recent_sessions if s.status == SessionStatus.RUNNING
        ),
        error_sessions=sum(
            1 for s in recent_sessions if s.status == SessionStatus.ERROR
        ),
        total_tool_calls=sum(s.tool_call_count for s in recent_sessions),
        total_steps=sum(s.step_count for s in recent_sessions),
    )

    # Fill hourly buckets based on last_activity
    for session in recent_sessions:
        last_activity = normalize_dt(session.last_activity)
        session_hour = last_activity.replace(minute=0, second=0, microsecond=0)
        hour_key = session_hour.isoformat()
        if hour_key in hourly_data:
            hourly_data[hour_key]["session_count"] += 1
            hourly_data[hour_key]["tool_call_count"] += session.tool_call_count
            if session.status == SessionStatus.COMPLETED:
                hourly_data[hour_key]["completed_count"] += 1

    # Convert to list sorted by hour
    hourly_distribution = [
        HourlyActivity(hour=hour, **data)
        for hour, data in sorted(hourly_data.items())
    ]

    return ActivityOverview(
        hourly_distribution=hourly_distribution,
        stats=stats,
    )


@router.get("/dashboard", response_model=DashboardData)
async def get_dashboard():
    """Get dashboard overview data.

    Returns server status, activity overview, and resource counts.
    Uses cache for fast response when available.
    """
    # Use cache if available
    cache = CacheService.get_instance()
    if cache.is_initialized():
        cached = await cache.get_dashboard()
        if cached:
            # Convert cached dict to response models
            server = cached.get("server", {})
            activity = cached.get("activity_overview", {})
            resources = cached.get("resource_counts", {})

            hourly_dist = [
                HourlyActivity(**h)
                for h in activity.get("hourly_distribution", [])
            ]

            return DashboardData(
                server=ServerInfo(
                    running=server.get("running", True),
                    uptime_seconds=server.get("uptime_seconds", 0),
                    started_at=server.get("started_at"),
                ),
                activity_overview=ActivityOverview(
                    hourly_distribution=hourly_dist,
                    stats=ActivityStats(**activity.get("stats", {})),
                ),
                resource_counts=ResourceCounts(
                    tasks=resources.get("tasks", 0),
                    recipes=resources.get("recipes", 0),
                    skills=resources.get("skills", 0),
                ),
            )

    # Fallback to direct calculation if cache not ready
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

    # Calculate activity overview
    activity_overview = calculate_activity_overview()

    # Get resource counts using services
    from frago.server.services.recipe_service import RecipeService
    from frago.server.services.skill_service import SkillService
    from frago.session.storage import list_sessions
    from frago.recipes.installer import RecipeInstaller

    try:
        recipes = RecipeService.get_recipes()
        recipe_count = len(recipes) if recipes else 0
        # Add installed community recipes
        installer = RecipeInstaller()
        community_installed = installer.list_installed()
        recipe_count += len(community_installed)
    except Exception:
        recipe_count = 0

    try:
        skills = SkillService.get_skills()
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
        activity_overview=activity_overview,
        resource_counts=ResourceCounts(
            tasks=task_count,
            recipes=recipe_count,
            skills=skill_count,
        ),
    )
