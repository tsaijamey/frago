"""Pydantic models for API request/response validation.

These models define the JSON schema for HTTP API endpoints.
Most map directly to existing GUI models in frago.gui_deprecated.models.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# Request Models
# ============================================================


class RecipeRunRequest(BaseModel):
    """Request body for POST /api/recipes/{name}/run"""

    params: Optional[Dict[str, Any]] = Field(
        default=None, description="Recipe parameters as key-value pairs"
    )
    timeout: Optional[int] = Field(
        default=None, ge=1, le=3600, description="Timeout in seconds (1-3600)"
    )


class AgentStartRequest(BaseModel):
    """Request body for POST /api/agent"""

    prompt: str = Field(..., min_length=1, description="Agent task prompt")
    project_path: Optional[str] = Field(
        default=None, description="Project path context for the agent"
    )


class ConfigUpdateRequest(BaseModel):
    """Request body for PUT /api/config"""

    theme: Optional[str] = Field(default=None, pattern="^(dark|light)$")
    font_size: Optional[int] = Field(default=None, ge=10, le=24)
    show_system_status: Optional[bool] = None
    confirm_on_exit: Optional[bool] = None
    auto_scroll_output: Optional[bool] = None
    max_history_items: Optional[int] = Field(default=None, ge=10, le=1000)
    shortcuts: Optional[Dict[str, str]] = None


# ============================================================
# Response Models
# ============================================================


class RecipeItemResponse(BaseModel):
    """Response for recipe list/detail endpoints"""

    name: str
    description: Optional[str] = None
    category: str = "atomic"
    icon: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    path: Optional[str] = None
    source: Optional[str] = None
    runtime: Optional[str] = None


class TaskItemResponse(BaseModel):
    """Response for task list endpoint"""

    id: str
    title: str
    status: str  # running, completed, error, cancelled
    project_path: Optional[str] = None
    agent_type: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class TaskStepResponse(BaseModel):
    """Response for task step"""

    timestamp: datetime
    type: str  # user, assistant, tool
    content: str
    tool_name: Optional[str] = None
    tool_result: Optional[str] = None


class ToolUsageStatResponse(BaseModel):
    """Tool usage statistics"""

    name: str
    count: int


class TaskSummaryResponse(BaseModel):
    """Task summary after completion"""

    total_duration_ms: int
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_error_count: int = 0
    most_used_tools: List[ToolUsageStatResponse] = Field(default_factory=list)


class TaskDetailResponse(BaseModel):
    """Response for task detail endpoint"""

    id: str
    title: str
    status: str
    steps: List[TaskStepResponse] = Field(default_factory=list)
    summary: Optional[TaskSummaryResponse] = None


class TaskListResponse(BaseModel):
    """Response for GET /api/tasks"""

    tasks: List[TaskItemResponse]
    total: int


class TaskStepsResponse(BaseModel):
    """Response for GET /api/tasks/{id}/steps"""

    steps: List[TaskStepResponse]
    total: int
    has_more: bool


class UserConfigResponse(BaseModel):
    """Response for GET /api/config"""

    theme: str = "dark"
    font_size: int = 14
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100
    shortcuts: Dict[str, str] = Field(default_factory=dict)


class SystemStatusResponse(BaseModel):
    """Response for GET /api/status"""

    chrome_available: bool = False
    chrome_connected: bool = False
    projects_count: int = 0
    tasks_running: int = 0


class ServerInfoResponse(BaseModel):
    """Response for GET /api/info"""

    version: str
    host: str
    port: int
    started_at: datetime


class SkillItemResponse(BaseModel):
    """Response for skill list endpoint"""

    name: str
    description: Optional[str] = None
    file_path: Optional[str] = None


# ============================================================
# WebSocket Message Models
# ============================================================


class WebSocketMessage(BaseModel):
    """WebSocket message envelope"""

    type: str  # session_sync, task_started, task_updated, task_completed, connection
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SessionSyncPayload(BaseModel):
    """Payload for session_sync message"""

    tasks: List[TaskItemResponse]


class TaskStartedPayload(BaseModel):
    """Payload for task_started message"""

    task: TaskItemResponse


class TaskUpdatedPayload(BaseModel):
    """Payload for task_updated message"""

    task_id: str
    status: str
    step: Optional[TaskStepResponse] = None


class TaskCompletedPayload(BaseModel):
    """Payload for task_completed message"""

    task_id: str
    status: str
    summary: Optional[TaskSummaryResponse] = None


class ConnectionPayload(BaseModel):
    """Payload for connection status message"""

    status: str  # connected, disconnected, reconnecting
