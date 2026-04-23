"""
Data Model Definitions

Contains all Pydantic models used by frago init command:
- Config: Persistent configuration
- APIEndpoint: Custom API endpoint configuration
- TemporaryState: Ctrl+C recovery state
- InstallationStep: Installation step state machine
- DependencyCheckResult: Dependency check result
- ResourceType: Resource type enumeration
- InstallResult: Resource installation result
- ResourceStatus: Resource installation status
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Literal
from datetime import datetime, timedelta
from enum import Enum


class APIEndpoint(BaseModel):
    """API endpoint configuration (nested in Config)"""

    type: Literal["deepseek", "aliyun", "kimi", "minimax", "custom"]
    url: Optional[str] = None
    api_key: str
    # Model configuration (optional, uses preset defaults if not specified)
    default_model: Optional[str] = None  # Maps to ANTHROPIC_MODEL
    sonnet_model: Optional[str] = None   # Maps to ANTHROPIC_DEFAULT_SONNET_MODEL
    haiku_model: Optional[str] = None    # Maps to ANTHROPIC_DEFAULT_HAIKU_MODEL

    @model_validator(mode="after")
    def validate_url_for_custom(self) -> "APIEndpoint":
        """Validate URL requirement (custom type must provide URL)"""
        if self.type == "custom" and not self.url:
            raise ValueError("Custom endpoint requires URL")
        return self


class TaskIngestionChannel(BaseModel):
    """One declared ingestion channel. Field names match ingestion/scheduler.py
    `ChannelConfig` so `ChannelConfig(**channel.model_dump())` works."""

    name: str
    poll_recipe: str
    notify_recipe: str
    poll_interval_seconds: int = 120
    poll_timeout_seconds: int = 20

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Channel name cannot be empty")
        return v.strip()

    @field_validator("poll_recipe", "notify_recipe")
    @classmethod
    def _recipe_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Recipe name cannot be empty")
        return v.strip()

    @field_validator("poll_interval_seconds", "poll_timeout_seconds")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Interval/timeout must be positive")
        return v


class TaskIngestionConfig(BaseModel):
    """Container for task ingestion configuration.

    Nested under `Config.task_ingestion`. Persists to config.json with the
    layout `{enabled: bool, channels: [TaskIngestionChannel, ...]}`, which
    matches what `server/app.py:_start_ingestion_scheduler` and
    `cli/reply_command.py` have always read by hand.
    """

    enabled: bool = False
    channels: List[TaskIngestionChannel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> "TaskIngestionConfig":
        names = [c.name for c in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("Channel names must be unique")
        return self


class Config(BaseModel):
    """Frago configuration entity (persisted to ~/.frago/config.json)"""

    schema_version: str = "1.0"

    # Dependency information
    node_version: Optional[str] = None
    node_path: Optional[str] = None
    npm_version: Optional[str] = None
    claude_code_version: Optional[str] = None
    claude_code_path: Optional[str] = None

    # Authentication configuration (mutually exclusive)
    auth_method: Literal["official", "custom"] = "official"
    api_endpoint: Optional[APIEndpoint] = None

    # Optional features
    ccr_enabled: bool = False
    ccr_config_path: Optional[str] = None

    # Multi-device sync configuration
    sync_repo_url: Optional[str] = None  # User's private repo URL (for sync)
    sync_max_file_size_mb: float = 5.0  # Max file size to sync (MB), default 5MB

    # Workspace resource management
    workspace_scan_roots: List[str] = Field(default_factory=list)  # e.g. ["~/repos/", "~/work/"]
    workspace_exclude_patterns: List[str] = Field(
        default_factory=lambda: ["node_modules", ".venv", "__pycache__", ".git"]
    )

    # Community recipe repository
    community_repo: str = "tsaijamey/frago"  # GitHub repo for community recipes

    # DEPRECATED (spec 20260422-init-flow-modernization): init no longer
    # bundles or installs official commands/skills/recipes. Fields kept so
    # older config.json files continue to deserialize; values are unread.
    official_resource_sync_enabled: bool = False
    official_resource_last_sync: Optional[datetime] = None
    official_resource_last_commit: Optional[str] = None
    resources_installed: bool = False
    resources_version: Optional[str] = None
    last_resource_update: Optional[datetime] = None

    # Task ingestion configuration (spec 20260422-channel-config-ui)
    task_ingestion: TaskIngestionConfig = Field(default_factory=TaskIngestionConfig)

    # Primary Agent configuration
    primary_agent: dict = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    init_completed: bool = False

    @model_validator(mode="after")
    def validate_auth_consistency(self) -> "Config":
        """Validate authentication configuration consistency

        Rules:
        - official mode cannot have api_endpoint in config.json
        - custom mode does not require api_endpoint (API config stored in ~/.claude/settings.json)
        """
        if self.auth_method == "official" and self.api_endpoint:
            raise ValueError("Official auth cannot have api_endpoint")
        # Note: custom mode no longer requires api_endpoint since it's stored in settings.json
        return self

    class ConfigDict:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class TemporaryState(BaseModel):
    """Temporary state (for Ctrl+C recovery, saved to ~/.frago/.init_state.json)"""

    completed_steps: List[str] = Field(default_factory=list)
    current_step: Optional[str] = None
    interrupted_at: datetime = Field(default_factory=datetime.now)
    recoverable: bool = True

    def is_expired(self, days: int = 7) -> bool:
        """Check if expired (default 7 days)"""
        return datetime.now() - self.interrupted_at > timedelta(days=days)

    def add_step(self, step: str) -> None:
        """Record completed step"""
        if step not in self.completed_steps:
            self.completed_steps.append(step)

    def set_current_step(self, step: str) -> None:
        """Set current step"""
        self.current_step = step

    def is_step_completed(self, step: str) -> bool:
        """Check if step is completed"""
        return step in self.completed_steps


class StepStatus(str, Enum):
    """Installation step status enumeration"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class InstallationStep(BaseModel):
    """Installation step state machine"""

    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    error_code: Optional[int] = None

    def start(self) -> None:
        """Mark step as started"""
        self.status = StepStatus.IN_PROGRESS
        self.started_at = datetime.now()

    def complete(self) -> None:
        """Mark step as completed successfully"""
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.now()

    def fail(self, error: str, code: int) -> None:
        """Mark step as failed"""
        self.status = StepStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error
        self.error_code = code

    def skip(self) -> None:
        """Mark step as skipped"""
        self.status = StepStatus.SKIPPED
        self.completed_at = datetime.now()


class DependencyCheckResult(BaseModel):
    """Dependency check result (for parallel checking)"""

    name: str
    installed: bool = False
    version: Optional[str] = None
    path: Optional[str] = None
    version_sufficient: bool = False
    required_version: str
    error: Optional[str] = None

    def needs_install(self) -> bool:
        """Whether installation is needed"""
        return not self.installed or not self.version_sufficient

    def display_status(self) -> str:
        """Generate display status"""
        if not self.installed:
            return f"[X] {self.name}: Not installed"
        elif not self.version_sufficient:
            return f"[!]  {self.name}: Insufficient version (current {self.version}, requires {self.required_version})"
        else:
            return f"[OK] {self.name}: {self.version}"


class ResourceType(str, Enum):
    """Resource type enumeration"""

    COMMAND = "command"  # Claude Code slash command
    SKILL = "skill"      # Claude Code skill
    RECIPE = "recipe"    # Example recipe


class InstallResult(BaseModel):
    """Resource installation operation result"""

    resource_type: ResourceType
    installed: List[str] = Field(default_factory=list)  # List of installed file paths
    skipped: List[str] = Field(default_factory=list)    # List of skipped file paths (already exists)
    backed_up: List[str] = Field(default_factory=list)  # List of backed up file paths
    errors: List[str] = Field(default_factory=list)     # List of error messages

    @property
    def success(self) -> bool:
        """Whether all operations succeeded (no errors)"""
        return len(self.errors) == 0

    @property
    def total_count(self) -> int:
        """Total number of processed files"""
        return len(self.installed) + len(self.skipped)


class ResourceStatus(BaseModel):
    """Resource installation status (for --status display)"""

    commands: Optional[InstallResult] = None
    skills: Optional[InstallResult] = None
    recipes: Optional[InstallResult] = None
    hooks_installed: List[str] = Field(default_factory=list)
    frago_version: str = ""
    install_time: Optional[datetime] = None

    @property
    def all_success(self) -> bool:
        """Whether all resources were installed successfully"""
        results = [self.commands, self.skills, self.recipes]
        return all(r is None or r.success for r in results)
