"""Pydantic models for API request/response validation.

These models define the JSON schema for HTTP API endpoints.
Most map directly to existing GUI models in frago.gui_deprecated.models.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

# ============================================================
# Request Models
# ============================================================


class RecipeRunRequest(BaseModel):
    """Request body for POST /api/recipes/{name}/run"""

    params: dict[str, Any] | None = Field(
        default=None, description="Recipe parameters as key-value pairs"
    )
    timeout: int | None = Field(
        default=None, ge=1, le=3600, description="Timeout in seconds (1-3600)"
    )


class AgentStartRequest(BaseModel):
    """Request body for POST /api/agent"""

    prompt: str = Field(..., min_length=1, description="Agent task prompt")
    project_path: str | None = Field(
        default=None, description="Project path context for the agent"
    )
    agent_type: str | None = Field(
        default=None,
        description=(
            "Which cli-agent core to drive (claude / opencode / codex). "
            "Omit to use the configured core preference."
        ),
    )


class AgentContinueRequest(BaseModel):
    """Request body for POST /api/agent/attached/{internal_id}/message"""

    prompt: str = Field(..., min_length=1, description="Continuation prompt")


class AgentAttachedStartRequest(BaseModel):
    """Request body for POST /api/agent/attached"""

    prompt: str = Field(..., min_length=1, description="Agent task prompt")
    project_path: str | None = Field(
        default=None, description="Project path context for the agent"
    )
    agent_type: str | None = Field(
        default=None,
        description=(
            "Which cli-agent core to drive (claude / opencode / codex). "
            "Omit to use the configured core preference."
        ),
    )


class AgentAttachedStartResponse(BaseModel):
    """Response for POST /api/agent/attached"""

    session_id: str | None = None  # Real Claude session ID, comes later via WebSocket
    internal_id: str  # Internal ID for API calls
    status: str  # starting, running
    project_path: str


class AgentAttachResponse(BaseModel):
    """Response for POST /api/agent/{session_id}/attach"""

    status: str  # attached, not_found, already_attached
    session_id: str
    running: bool



class ConfigUpdateRequest(BaseModel):
    """Request body for PUT /api/config"""

    theme: str | None = Field(default=None, pattern="^(dark|light)$")
    language: str | None = Field(default=None, pattern="^(en|zh)$")
    font_size: int | None = Field(default=None, ge=8, le=32)
    max_history_items: int | None = Field(default=None, ge=10, le=1000)
    shortcuts: dict[str, str] | None = None
    ai_title_enabled: bool | None = None


# ============================================================
# Response Models
# ============================================================


class RecipeItemResponse(BaseModel):
    """Response for recipe list endpoints"""

    name: str
    description: str | None = None
    category: str = "atomic"
    icon: str | None = None
    tags: list[str] = Field(default_factory=list)
    path: str | None = None
    source: str | None = None
    runtime: str | None = None


class RecipeInputSchema(BaseModel):
    """Recipe input parameter schema

    The constraint fields are all optional and are enforced only for a caller
    who is not the owner. They are listed here as well as parsed, because
    pydantic drops whatever this model does not name: a recipe could declare
    `max_length` and the page building its form would never learn of it, which
    is how a limit ends up enforced by the server and invisible in the UI.
    """

    type: str
    required: bool = False
    default: Any | None = None
    description: str | None = None
    enum: list | None = None
    max_length: int | None = None
    pattern: str | None = None
    min: float | None = None
    max: float | None = None


class RecipeOutputSchema(BaseModel):
    """Recipe output schema"""

    type: str
    description: str | None = None


class RecipeFlowStep(BaseModel):
    """Recipe workflow step definition"""

    step: int
    action: str
    description: str
    recipe: str | None = None
    inputs: list[dict[str, str]] = Field(default_factory=list)
    outputs: list[dict[str, str]] = Field(default_factory=list)


class RecipeDetailResponse(BaseModel):
    """Response for recipe detail endpoint with rich metadata"""

    name: str
    description: str | None = None
    category: str = "atomic"
    icon: str | None = None
    tags: list[str] = Field(default_factory=list)
    path: str | None = None
    source: str | None = None
    runtime: str | None = None
    # Rich metadata fields
    version: str | None = None
    base_dir: str | None = None
    script_path: str | None = None
    metadata_path: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    output_targets: list[str] = Field(default_factory=list)
    inputs: dict[str, RecipeInputSchema] = Field(default_factory=dict)
    outputs: dict[str, RecipeOutputSchema] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    env: dict[str, Any] = Field(default_factory=dict)
    source_code: str | None = None
    flow: list[RecipeFlowStep] = Field(default_factory=list)
    # 这个配方有没有页面（/app/<名字>/ 能开出东西）。界面据此决定给不给「打开页面」。
    has_page: bool = False


class TaskItemResponse(BaseModel):
    """Response for task list endpoint"""

    id: str
    title: str
    status: str  # running, completed, error, cancelled
    project_path: str | None = None
    agent_type: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    step_count: int = 0
    tool_call_count: int = 0
    source: str = "unknown"  # terminal, web, or unknown


class TaskStepResponse(BaseModel):
    """Response for task step

    Message types match ConsoleMessage for consistency:
    - user: User input message
    - assistant: Assistant response message
    - tool_call: Tool call request
    - tool_result: Tool execution result
    - system: System event
    """

    timestamp: datetime
    type: str  # user, assistant, tool_call, tool_result, system
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_result: str | None = None


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
    most_used_tools: list[ToolUsageStatResponse] = Field(default_factory=list)


class TaskDetailResponse(BaseModel):
    """Response for task detail endpoint"""

    id: str
    title: str
    status: str
    project_path: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    step_count: int = 0
    tool_call_count: int = 0
    steps: list[TaskStepResponse] = Field(default_factory=list)
    steps_total: int = 0
    steps_offset: int = 0
    has_more_steps: bool = False
    summary: TaskSummaryResponse | None = None


class TaskListResponse(BaseModel):
    """Response for GET /api/tasks"""

    tasks: list[TaskItemResponse]
    total: int


class TaskStepsResponse(BaseModel):
    """Response for GET /api/tasks/{id}/steps"""

    steps: list[TaskStepResponse]
    total: int
    has_more: bool


class WebuiSessionsResponse(BaseModel):
    """Read-only view of ~/.frago/config.json -> webui_sessions, exposed via GET /config.

    spec 20260625-webui-session-lifecycle-mediator: front-end reads max_resident
    (and idle_timeout_secs) instead of hard-coding them.
    """

    max_resident: int = 10
    idle_timeout_secs: int = 1800
    # 手动清理浮窗的筛选门槛（小时）。不是自动回收那条线，见 WebuiSessionsConfig。
    cleanup_idle_hours: float = 1.0


class UserConfigResponse(BaseModel):
    """Response for GET /api/config"""

    theme: str = "dark"
    language: str = "en"
    font_size: int = 14
    max_history_items: int = 100
    shortcuts: dict[str, str] = Field(default_factory=dict)
    ai_title_enabled: bool = False
    webui_sessions: WebuiSessionsResponse = Field(default_factory=WebuiSessionsResponse)


class SystemStatusResponse(BaseModel):
    """Response for GET /api/status"""

    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    browser_available: bool = False
    browser_connected: bool = False
    projects_count: int = 0
    tasks_running: int = 0
    tab_count: int = 0


class ServerInfoResponse(BaseModel):
    """Response for GET /api/info"""

    version: str
    host: str
    port: int
    started_at: datetime


class SystemDirectoriesResponse(BaseModel):
    """Response for GET /api/system/directories"""

    home: str  # User home directory
    cwd: str | None = None  # Current working directory (optional)


class DirectoryEntry(BaseModel):
    """一个子目录。名字给人看，整条路径给选中之后用。"""

    name: str
    path: str


class DirectoryListingResponse(BaseModel):
    """Response for GET /api/system/directories/browse

    只报子目录，不报文件——这份清单唯一的用途是挑一个工作目录。
    """

    path: str  # 当前停在哪一层（已展开、已解析的绝对路径）
    parent: str | None = None  # 上一层；到了根就没有
    entries: list[DirectoryEntry] = []


class ClaudeUsageBucket(BaseModel):
    """一档额度。`resets_at` 照 Claude Code 的原话留着，带着人自己的时区名。"""

    percent: int = 0
    resets_at: str | None = None
    label: str | None = None  # 型号那一档才有：Fable / Opus / …


class ClaudeUsageResponse(BaseModel):
    """Response for GET /api/system/claude-usage

    `available` 为假表示这台机器答不出订阅额度——没装 Claude Code，或者用的是 API key
    而不是订阅。界面据此整块不画，而不是画三根空条子。
    """

    available: bool = False
    session: ClaudeUsageBucket | None = None  # 五小时会话窗口
    week_all: ClaudeUsageBucket | None = None  # 本周全模型
    week_model: ClaudeUsageBucket | None = None  # 本周某个型号
    checked_at: str | None = None
    error: str | None = None


class SkillItemResponse(BaseModel):
    """Response for skill list endpoint"""

    name: str
    description: str | None = None
    file_path: str | None = None


# ============================================================
# WebSocket Message Models
# ============================================================


class WebSocketMessage(BaseModel):
    """WebSocket message envelope"""

    type: str  # session_sync, task_started, task_updated, task_completed, connection
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class SessionSyncPayload(BaseModel):
    """Payload for session_sync message"""

    tasks: list[TaskItemResponse]


class TaskStartedPayload(BaseModel):
    """Payload for task_started message"""

    task: TaskItemResponse


class TaskUpdatedPayload(BaseModel):
    """Payload for task_updated message"""

    task_id: str
    status: str
    step: TaskStepResponse | None = None


class TaskCompletedPayload(BaseModel):
    """Payload for task_completed message"""

    task_id: str
    status: str
    summary: TaskSummaryResponse | None = None


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
    version: str | None = None
    path: str | None = None
    version_sufficient: bool = False
    required_version: str
    error: str | None = None
    install_guide: str = ""
    optional: bool = False
    """Absent means nothing frago does is blocked by this dependency missing.

    Node.js is the case. Without this field the response model silently dropped
    it, so the interface kept treating an absent Node as a problem to fix even
    after the checker had stopped calling it one.
    """


class InitStatusResponse(BaseModel):
    """Response for GET /api/init/status"""

    init_completed: bool = False
    node: DependencyStatusResponse
    claude_code: DependencyStatusResponse
    resources_installed: bool = False
    resources_version: str | None = None
    resources_update_available: bool = False
    current_frago_version: str
    auth_configured: bool = False
    auth_method: str | None = None
    resources_info: dict[str, Any] = Field(default_factory=dict)


class DependencyCheckResponse(BaseModel):
    """Response for POST /api/init/check-deps"""

    node: DependencyStatusResponse
    claude_code: DependencyStatusResponse
    all_satisfied: bool = False


class InstallResultSummary(BaseModel):
    """Summary for resource installation result"""

    installed: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class ResourceInstallResponse(BaseModel):
    """Response for POST /api/init/install-resources"""

    status: str  # ok, partial, error
    commands: InstallResultSummary
    skills: InstallResultSummary
    recipes: InstallResultSummary
    total_installed: int = 0
    total_skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    frago_version: str | None = None
    message: str | None = None


class DependencyInstallRequest(BaseModel):
    """Request for POST /api/init/install-dep/{name}"""

    pass  # No body needed, name is in path


class DependencyInstallResponse(BaseModel):
    """Response for POST /api/init/install-dep/{name}"""

    status: str  # ok, error
    message: str
    requires_restart: bool = False
    warning: str | None = None
    install_guide: str | None = None
    error_code: str | None = None
    details: str | None = None


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
    progress: int | None = None  # 0-100
    message: str | None = None


class InitStepCompletePayload(BaseModel):
    """Payload for init_step_complete message"""

    step: str
    status: str  # ok, error, skipped
    message: str | None = None


class InitErrorPayload(BaseModel):
    """Payload for init_error message"""

    step: str
    error: str
    details: str | None = None


# ============================================================
# Community Recipe Models
# ============================================================


class CommunityRecipeItemResponse(BaseModel):
    """Response for community recipe list endpoints"""

    name: str
    url: str
    description: str | None = None
    version: str | None = None
    type: str = "atomic"  # atomic | workflow
    runtime: str | None = None
    tags: list[str] = Field(default_factory=list)
    installed: bool = False
    installed_version: str | None = None
    has_update: bool = False


class CommunityRecipeInstallRequest(BaseModel):
    """Request body for POST /api/community-recipes/{name}/install"""

    force: bool = Field(default=False, description="Force overwrite if exists")


class CommunityRecipeInstallResponse(BaseModel):
    """Response for community recipe install/update operations"""

    status: str  # ok | error
    recipe_name: str | None = None
    message: str | None = None
    error: str | None = None


class TmuxSessionItem(BaseModel):
    """清点浮窗里的一行：一场本机 tmux agent 会话。

    ``last_stop_at`` / ``idle_secs`` 的口径是「最后一条终结记录的时刻」，NEVER 是
    tmux 自己的活动时间——后者被界面重绘推着走，同一批会话两个口径实测差过四小时。
    """

    name: str
    label: str
    session_id: str | None = None
    stop_reason: str | None = None
    last_stop_at: str | None = None
    idle_secs: float | None = None
    excerpt: str = ""
    memory_mb: int = 0
    busy: bool = False
    managed: bool = False


class TmuxSessionsResponse(BaseModel):
    """Response for GET /api/system/tmux-sessions"""

    sessions: list[TmuxSessionItem] = Field(default_factory=list)
    total: int = 0
    total_memory_mb: int = 0
    cleanup_idle_hours: float = 1.0


class CloseTmuxSessionsRequest(BaseModel):
    """Request body for POST /api/system/tmux-sessions/close"""

    names: list[str] = Field(..., description="tmux session names to close, one by one")


class CloseTmuxSessionsResult(BaseModel):
    name: str
    ok: bool
    via: str = "tmux"
    error: str | None = None


class CloseTmuxSessionsResponse(BaseModel):
    """Response for POST /api/system/tmux-sessions/close"""

    results: list[CloseTmuxSessionsResult] = Field(default_factory=list)
    closed: int = 0
    failed: int = 0


class CleanupThresholdRequest(BaseModel):
    """Request body for PUT /api/system/tmux-sessions/threshold"""

    cleanup_idle_hours: float = Field(..., ge=0.0, le=720.0)


class TmuxSessionsCountResponse(BaseModel):
    """Response for GET /api/system/tmux-sessions/count —— 左下角那个数字。

    刻意不带任何一场会话的内容：这条每分钟被问一次，读记录留给人点开浮窗那一刻。
    """

    total: int = 0
    total_memory_mb: int = 0


class EnvironmentItem(BaseModel):
    """环境仪表盘上的一格。

    `current` 是本机装的那一版，`latest` 是外面出到的那一版，两个都可能为空：没装的
    东西没有当前版本，没有公开版本源的东西（WorkBuddy）没有最新版本。`outdated` 只在
    两个都拿得到、且外面那个确实更大时才为真。
    """

    id: str
    name: str
    group: str
    required: bool = False
    installed: bool = False
    current: str | None = None
    latest: str | None = None
    outdated: bool = False


class EnvironmentResponse(BaseModel):
    """Response for GET /api/system/environment"""

    items: list[EnvironmentItem] = Field(default_factory=list)
    os: str = ""
    # frago 自己是从哪儿装的：local 本地构建的 wheel、index 索引、unknown。
    # 界面据此说明为什么这台机器上的 frago 不报可更新。
    frago_source: str = "unknown"
    # 外面那批版本号上次问到的时间（unix 秒）。没问到过就是空。
    checked_at: float | None = None


class EnvironmentUpgradeRequest(BaseModel):
    """Request body for POST /api/system/environment/upgrade"""

    ids: list[str] = Field(..., description="要升级的那几样，按这个顺序一样一样跑")


class EnvironmentUpgradeItemState(BaseModel):
    """一样东西这一轮升级到哪一步了。

    `state` 六档：pending 排着队、running 正在跑、ok 升成了、skipped 不用升、
    manual 得用户自己动手、failed 没升成。

    `message` 随档位换意思：manual 那档它是一条要用户在终端里跑的命令，界面原样摆出来
    给人复制；其余档位是给人看的那句结论。
    """

    state: str = "pending"
    message: str = ""
    before: str | None = None
    after: str | None = None


class EnvironmentUpgradeResponse(BaseModel):
    """Response for the upgrade endpoints"""

    # 提交时才有意义：已经有一批在跑时为假，此时返回的是那一批的进度。
    accepted: bool = True
    running: bool = False
    order: list[str] = Field(default_factory=list)
    items: dict[str, EnvironmentUpgradeItemState] = Field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
