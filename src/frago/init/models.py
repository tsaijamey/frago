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

    # Community recipe repository
    community_repo: str = "tsaijamey/frago"  # GitHub repo for community recipes

    # Resource installation status
    resources_installed: bool = False
    resources_version: Optional[str] = None
    last_resource_update: Optional[datetime] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    init_completed: bool = False

    @model_validator(mode="after")
    def validate_auth_consistency(self) -> "Config":
        """Validate authentication configuration consistency (mutual exclusivity constraint)"""
        if self.auth_method == "custom" and not self.api_endpoint:
            raise ValueError("Custom auth requires api_endpoint")
        if self.auth_method == "official" and self.api_endpoint:
            raise ValueError("Official auth cannot have api_endpoint")
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
    frago_version: str = ""
    install_time: Optional[datetime] = None

    @property
    def all_success(self) -> bool:
        """Whether all resources were installed successfully"""
        results = [self.commands, self.skills, self.recipes]
        return all(r is None or r.success for r in results)
