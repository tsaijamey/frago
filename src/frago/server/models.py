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


class AgentContinueRequest(BaseModel):
    """Request body for POST /api/agent/{session_id}/continue"""

    prompt: str = Field(..., min_length=1, description="Continuation prompt")


class ConsoleStartRequest(BaseModel):
    """Request body for POST /api/console/start"""

    prompt: str = Field(..., min_length=1, description="Initial message to Claude")
    project_path: Optional[str] = Field(
        default=None, description="Project path context"
    )
    auto_approve: bool = Field(
        default=True, description="Auto-approve all tool calls (default: true)"
    )


class ConsoleSendMessageRequest(BaseModel):
    """Request body for POST /api/console/{session_id}/message"""

    message: str = Field(..., min_length=1, description="User message to send")


class ConfigUpdateRequest(BaseModel):
    """Request body for PUT /api/config"""

    theme: Optional[str] = Field(default=None, pattern="^(dark|light)$")
    language: Optional[str] = Field(default=None, pattern="^(en|zh)$")
    font_size: Optional[int] = Field(default=None, ge=8, le=32)
    show_system_status: Optional[bool] = None
    confirm_on_exit: Optional[bool] = None
    auto_scroll_output: Optional[bool] = None
    max_history_items: Optional[int] = Field(default=None, ge=10, le=1000)
    shortcuts: Optional[Dict[str, str]] = None
    ai_title_enabled: Optional[bool] = None


# ============================================================
# Response Models
# ============================================================


class RecipeItemResponse(BaseModel):
    """Response for recipe list endpoints"""

    name: str
    description: Optional[str] = None
    category: str = "atomic"
    icon: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    path: Optional[str] = None
    source: Optional[str] = None
    runtime: Optional[str] = None


class RecipeInputSchema(BaseModel):
    """Recipe input parameter schema"""

    type: str
    required: bool = False
    default: Optional[Any] = None
    description: Optional[str] = None


class RecipeOutputSchema(BaseModel):
    """Recipe output schema"""

    type: str
    description: Optional[str] = None


class RecipeDetailResponse(BaseModel):
    """Response for recipe detail endpoint with rich metadata"""

    name: str
    description: Optional[str] = None
    category: str = "atomic"
    icon: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    path: Optional[str] = None
    source: Optional[str] = None
    runtime: Optional[str] = None
    # Rich metadata fields
    version: Optional[str] = None
    base_dir: Optional[str] = None
    script_path: Optional[str] = None
    metadata_path: Optional[str] = None
    use_cases: List[str] = Field(default_factory=list)
    output_targets: List[str] = Field(default_factory=list)
    inputs: Dict[str, RecipeInputSchema] = Field(default_factory=dict)
    outputs: Dict[str, RecipeOutputSchema] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)
    env: Dict[str, Any] = Field(default_factory=dict)
    source_code: Optional[str] = None


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
    step_count: int = 0
    tool_call_count: int = 0
    source: str = "unknown"  # terminal, web, or unknown


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
    project_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    step_count: int = 0
    tool_call_count: int = 0
    steps: List[TaskStepResponse] = Field(default_factory=list)
    steps_total: int = 0
    steps_offset: int = 0
    has_more_steps: bool = False
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


class ConsoleMessageResponse(BaseModel):
    """Response for console message item"""

    type: str  # user, assistant, tool_call, tool_result
    content: str
    timestamp: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConsoleStartResponse(BaseModel):
    """Response for POST /api/console/start"""

    session_id: str
    status: str  # running
    project_path: str
    auto_approve: bool


class ConsoleHistoryResponse(BaseModel):
    """Response for GET /api/console/{session_id}/history"""

    messages: List[ConsoleMessageResponse]
    total: int
    has_more: bool


class ConsoleSessionInfoResponse(BaseModel):
    """Response for GET /api/console/{session_id}/info"""

    session_id: str
    project_path: str
    auto_approve: bool
    running: bool
    message_count: int


class UserConfigResponse(BaseModel):
    """Response for GET /api/config"""

    theme: str = "dark"
    language: str = "en"
    font_size: int = 14
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100
    shortcuts: Dict[str, str] = Field(default_factory=dict)
    ai_title_enabled: bool = False


class SystemStatusResponse(BaseModel):
    """Response for GET /api/status"""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
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


# ============================================================
# Initialization Models
# ============================================================


class DependencyStatusResponse(BaseModel):
    """Dependency status for init endpoint"""

    name: str
    installed: bool = False
    version: Optional[str] = None
    path: Optional[str] = None
    version_sufficient: bool = False
    required_version: str
    error: Optional[str] = None
    install_guide: str = ""


class InitStatusResponse(BaseModel):
    """Response for GET /api/init/status"""

    init_completed: bool = False
    node: DependencyStatusResponse
    claude_code: DependencyStatusResponse
    resources_installed: bool = False
    resources_version: Optional[str] = None
    resources_update_available: bool = False
    current_frago_version: str
    auth_configured: bool = False
    auth_method: Optional[str] = None
    resources_info: Dict[str, Any] = Field(default_factory=dict)


class DependencyCheckResponse(BaseModel):
    """Response for POST /api/init/check-deps"""

    node: DependencyStatusResponse
    claude_code: DependencyStatusResponse
    all_satisfied: bool = False


class InstallResultSummary(BaseModel):
    """Summary for resource installation result"""

    installed: int = 0
    skipped: int = 0
    errors: List[str] = Field(default_factory=list)


class ResourceInstallResponse(BaseModel):
    """Response for POST /api/init/install-resources"""

    status: str  # ok, partial, error
    commands: InstallResultSummary
    skills: InstallResultSummary
    recipes: InstallResultSummary
    total_installed: int = 0
    total_skipped: int = 0
    errors: List[str] = Field(default_factory=list)
    frago_version: Optional[str] = None
    message: Optional[str] = None


class DependencyInstallRequest(BaseModel):
    """Request for POST /api/init/install-dep/{name}"""

    pass  # No body needed, name is in path


class DependencyInstallResponse(BaseModel):
    """Response for POST /api/init/install-dep/{name}"""

    status: str  # ok, error
    message: str
    requires_restart: bool = False
    warning: Optional[str] = None
    install_guide: Optional[str] = None
    error_code: Optional[str] = None
    details: Optional[str] = None


class ResourceInstallRequest(BaseModel):
    """Request for POST /api/init/install-resources"""

    force_update: bool = False


class InitCompleteResponse(BaseModel):
    """Response for POST /api/init/complete"""

    status: str  # ok, error
    message: str
    init_completed: bool = False


# ============================================================
# Init WebSocket Message Types
# ============================================================


class InitProgressPayload(BaseModel):
    """Payload for init_progress message"""

    step: str  # dependencies, resources, auth
    status: str  # checking, installing, complete, error
    progress: Optional[int] = None  # 0-100
    message: Optional[str] = None


class InitStepCompletePayload(BaseModel):
    """Payload for init_step_complete message"""

    step: str
    status: str  # ok, error, skipped
    message: Optional[str] = None


class InitErrorPayload(BaseModel):
    """Payload for init_error message"""

    step: str
    error: str
    details: Optional[str] = None


# ============================================================
# Community Recipe Models
# ============================================================


class CommunityRecipeItemResponse(BaseModel):
    """Response for community recipe list endpoints"""

    name: str
    url: str
    description: Optional[str] = None
    version: Optional[str] = None
    type: str = "atomic"  # atomic | workflow
    runtime: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    installed: bool = False
    installed_version: Optional[str] = None
    has_update: bool = False


class CommunityRecipeInstallRequest(BaseModel):
    """Request body for POST /api/community-recipes/{name}/install"""

    force: bool = Field(default=False, description="Force overwrite if exists")


class CommunityRecipeInstallResponse(BaseModel):
    """Response for community recipe install/update operations"""

    status: str  # ok | error
    recipe_name: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
