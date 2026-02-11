"""Unified data models for server state management.

These dataclasses represent the internal state of the server.
They can be converted to/from Pydantic API models as needed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ============================================================
# Task Models
# ============================================================


@dataclass
class TaskStep:
    """A single step in a task execution."""

    timestamp: datetime
    type: str  # user, assistant, tool_call, tool_result, system
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_result: Optional[str] = None


@dataclass
class ToolUsageStat:
    """Tool usage statistics."""

    name: str
    count: int


@dataclass
class TaskSummary:
    """Summary of a completed task."""

    total_duration_ms: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0
    most_used_tools: List[ToolUsageStat] = field(default_factory=list)


@dataclass
class TaskItem:
    """Task list item (lightweight)."""

    id: str
    title: str
    status: str  # running, completed, error, cancelled
    project_path: Optional[str] = None
    agent_type: str = "claude"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    step_count: int = 0
    tool_call_count: int = 0
    source: str = "unknown"  # terminal, web, unknown


@dataclass
class TaskDetail:
    """Full task details including steps."""

    id: str
    title: str
    status: str
    project_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    step_count: int = 0
    tool_call_count: int = 0
    steps: List[TaskStep] = field(default_factory=list)
    steps_total: int = 0
    steps_offset: int = 0
    has_more_steps: bool = False
    summary: Optional[TaskSummary] = None


# ============================================================
# Recipe Models
# ============================================================


@dataclass
class Recipe:
    """Recipe item."""

    name: str
    description: Optional[str] = None
    category: str = "atomic"  # atomic, workflow
    icon: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    path: Optional[str] = None
    source: Optional[str] = None
    runtime: Optional[str] = None


@dataclass
class CommunityRecipe:
    """Community recipe item."""

    name: str
    url: str
    description: Optional[str] = None
    version: Optional[str] = None
    type: str = "atomic"
    runtime: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    installed: bool = False
    installed_version: Optional[str] = None
    has_update: bool = False


# ============================================================
# Skill Models
# ============================================================


@dataclass
class Skill:
    """Skill item."""

    name: str
    description: Optional[str] = None
    file_path: Optional[str] = None


# ============================================================
# Project Models
# ============================================================


@dataclass
class Project:
    """Project item."""

    path: str
    name: str
    last_accessed: Optional[datetime] = None


# ============================================================
# Dashboard Models
# ============================================================


@dataclass
class ResourceCounts:
    """Resource counts for dashboard."""

    tasks: int = 0
    recipes: int = 0
    skills: int = 0


@dataclass
class DashboardStatus:
    """System status for dashboard footer."""

    chrome_connected: bool = False
    tab_count: int = 0
    error_count: int = 0
    last_synced_at: Optional[str] = None


@dataclass
class DashboardData:
    """Dashboard overview data (workbench model)."""

    running_tasks: List[Dict[str, Any]] = field(default_factory=list)
    recent_tasks: List[Dict[str, Any]] = field(default_factory=list)
    quick_recipes: List[Dict[str, Any]] = field(default_factory=list)
    resource_counts: ResourceCounts = field(default_factory=ResourceCounts)
    system_status: DashboardStatus = field(default_factory=DashboardStatus)


# ============================================================
# Config Models
# ============================================================


@dataclass
class UserConfig:
    """User configuration."""

    theme: str = "dark"
    language: str = "en"
    font_size: int = 14
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100
    shortcuts: Dict[str, str] = field(default_factory=dict)
    ai_title_enabled: bool = False


# ============================================================
# Unified Server State
# ============================================================


@dataclass
class ServerState:
    """Unified server state containing all data models.

    This is the single source of truth for all server data.
    WebUI reads from this state, and all modifications go through StateManager.
    """

    # Task data
    tasks: List[TaskItem] = field(default_factory=list)
    tasks_total: int = 0
    task_details: Dict[str, TaskDetail] = field(default_factory=dict)

    # Recipe data
    recipes: List[Recipe] = field(default_factory=list)
    community_recipes: List[CommunityRecipe] = field(default_factory=list)

    # Skill data
    skills: List[Skill] = field(default_factory=list)

    # Project data
    projects: List[Project] = field(default_factory=list)

    # Dashboard data
    dashboard: DashboardData = field(default_factory=DashboardData)

    # Config data
    config: UserConfig = field(default_factory=UserConfig)
    env_vars: Dict[str, Any] = field(default_factory=dict)
    recipe_env_requirements: List[Dict[str, Any]] = field(default_factory=list)

    # GitHub status
    gh_status: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    version: int = 0
    last_updated: Optional[datetime] = None
