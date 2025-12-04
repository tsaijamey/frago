"""Data models for Frago GUI.

Defines core entities: WindowConfig, AppState, UserConfig, CommandRecord, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    """Task execution status."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class ConnectionStatus(Enum):
    """Chrome connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CHECKING = "checking"


class PageType(Enum):
    """GUI page types."""

    HOME = "home"
    RECIPES = "recipes"
    SKILLS = "skills"
    HISTORY = "history"
    SETTINGS = "settings"


class CommandType(Enum):
    """Command types for history records."""

    AGENT = "agent"
    RECIPE = "recipe"
    CHROME = "chrome"


class MessageType(Enum):
    """Stream message types."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    PROGRESS = "progress"
    ERROR = "error"


@dataclass
class WindowConfig:
    """GUI window display configuration."""

    width: int = 600
    height: int = 1434
    title: str = "Frago GUI"
    frameless: bool = False  # 使用原生窗口标题栏，让关闭按钮正常工作
    resizable: bool = False
    min_width: int = 400
    min_height: int = 600
    easy_drag: bool = True
    x: Optional[int] = None
    y: Optional[int] = None


@dataclass
class AppState:
    """GUI application runtime state."""

    current_page: PageType = PageType.HOME
    task_status: TaskStatus = TaskStatus.IDLE
    connection_status: ConnectionStatus = ConnectionStatus.CHECKING
    current_task_id: Optional[str] = None
    current_task_progress: float = 0.0
    last_error: Optional[str] = None


@dataclass
class UserConfig:
    """User preferences, persisted to ~/.frago/gui_config.json."""

    theme: str = "dark"
    font_size: int = 14
    show_system_status: bool = True
    confirm_on_exit: bool = True
    auto_scroll_output: bool = True
    max_history_items: int = 100
    shortcuts: Dict[str, str] = field(
        default_factory=lambda: {
            "send": "Ctrl+Enter",
            "clear": "Ctrl+L",
            "settings": "Ctrl+,",
        }
    )

    def validate(self) -> List[str]:
        """Validate configuration values.

        Returns:
            List of validation error messages, empty if valid.
        """
        errors = []
        if self.theme not in ("dark", "light"):
            errors.append(f"theme must be 'dark' or 'light', got '{self.theme}'")
        if not 10 <= self.font_size <= 24:
            errors.append(f"font_size must be between 10 and 24, got {self.font_size}")
        if not 10 <= self.max_history_items <= 1000:
            errors.append(
                f"max_history_items must be between 10 and 1000, got {self.max_history_items}"
            )
        return errors


@dataclass
class CommandRecord:
    """Command execution history record."""

    id: str
    timestamp: datetime
    command_type: CommandType
    input_text: str
    status: TaskStatus
    duration_ms: Optional[int] = None
    output: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "command_type": self.command_type.value,
            "input_text": self.input_text,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandRecord":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            command_type=CommandType(data["command_type"]),
            input_text=data["input_text"],
            status=TaskStatus(data["status"]),
            duration_ms=data.get("duration_ms"),
            output=data.get("output"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RecipeItem:
    """Recipe list item (from frago recipe list)."""

    name: str
    description: Optional[str] = None
    category: str = "atomic"
    icon: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    path: Optional[str] = None
    source: Optional[str] = None
    runtime: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "tags": self.tags,
            "path": self.path,
            "source": self.source,
            "runtime": self.runtime,
        }


@dataclass
class SkillItem:
    """Skill list item (from ~/.claude/skills/)."""

    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    file_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "file_path": self.file_path,
        }


@dataclass
class StreamMessage:
    """Stream-json parsed message."""

    type: MessageType
    content: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    progress: Optional[float] = None
    step: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JavaScript."""
        return {
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "progress": self.progress,
            "step": self.step,
        }
