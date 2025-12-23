"""Data models for Frago GUI.

Defines core entities: WindowConfig, AppState, UserConfig, CommandRecord, etc.
Extended for 011-gui-tasks-redesign: TaskItem, TaskDetail, TaskStep, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from frago.session.models import MonitoredSession, SessionStep, SessionSummary


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is in UTC timezone

    If no timezone info, assume local time and convert to UTC.
    """
    if dt.tzinfo is None:
        # No timezone info, assume local time, attach local timezone then convert to UTC
        return dt.astimezone().astimezone(timezone.utc)
    return dt.astimezone(timezone.utc)


class TaskStatus(Enum):
    """Task execution status (for existing GUI task management)."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


# ============================================================
# 011-gui-tasks-redesign: New task status enum (for Tasks page display)
# ============================================================


class GUITaskStatus(str, Enum):
    """Task status (for GUI Tasks page display)

    Uses string enum for JSON serialization.
    Color mapping:
    - RUNNING: yellow (var(--accent-warning))
    - COMPLETED: green (var(--accent-success))
    - ERROR: red (var(--accent-error))
    - CANCELLED: red (var(--accent-error))
    """

    RUNNING = "running"  # In progress - yellow
    COMPLETED = "completed"  # Completed - green
    ERROR = "error"  # Error - red
    CANCELLED = "cancelled"  # Cancelled - red

    @property
    def color(self) -> str:
        """Return CSS color variable for status"""
        colors = {
            GUITaskStatus.RUNNING: "var(--accent-warning)",
            GUITaskStatus.COMPLETED: "var(--accent-success)",
            GUITaskStatus.ERROR: "var(--accent-error)",
            GUITaskStatus.CANCELLED: "var(--accent-error)",
        }
        return colors[self]

    @property
    def icon(self) -> str:
        """Return status icon"""
        icons = {
            GUITaskStatus.RUNNING: "●",
            GUITaskStatus.COMPLETED: "✓",
            GUITaskStatus.ERROR: "✗",
            GUITaskStatus.CANCELLED: "○",
        }
        return icons[self]

    @property
    def label(self) -> str:
        """Return status label"""
        labels = {
            GUITaskStatus.RUNNING: "Running",
            GUITaskStatus.COMPLETED: "Completed",
            GUITaskStatus.ERROR: "Error",
            GUITaskStatus.CANCELLED: "Cancelled",
        }
        return labels[self]


class ConnectionStatus(Enum):
    """Chrome connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CHECKING = "checking"


class PageType(Enum):
    """GUI page types.

    Updated for 011-gui-tasks-redesign:
    - Added TIPS page (default startup page)
    - Added TASKS page (renamed from HOME)
    - Added TASK_DETAIL page (task details)
    - Removed HISTORY (merged into TASKS)
    """

    TIPS = "tips"  # Added: Tips page (default)
    TASKS = "tasks"  # Added: Tasks page (formerly home)
    TASK_DETAIL = "task_detail"  # Added: Task detail page
    HOME = "home"  # Kept: Compatibility with old code
    RECIPES = "recipes"  # Kept
    RECIPE_DETAIL = "recipe_detail"  # Kept
    SKILLS = "skills"  # Kept
    HISTORY = "history"  # Kept: Compatibility with old code
    SETTINGS = "settings"  # Kept


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
    title: str = "frago"
    frameless: bool = False  # Use native window title bar to make close button work properly
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


# ============================================================
# 011-gui-tasks-redesign: Tasks page data models
# ============================================================


class ToolUsageStat(BaseModel):
    """Tool usage statistics"""

    name: str = Field(..., description="Tool name")
    count: int = Field(..., ge=0, description="Usage count")


class TaskSummary(BaseModel):
    """Task summary - generated after session completion"""

    total_duration_ms: int = Field(..., ge=0, description="Total duration")
    user_message_count: int = Field(0, description="User message count")
    assistant_message_count: int = Field(0, description="Assistant message count")
    tool_call_count: int = Field(0, description="Total tool call count")
    tool_success_count: int = Field(0, description="Successful tool calls")
    tool_error_count: int = Field(0, description="Failed tool calls")
    most_used_tools: List[ToolUsageStat] = Field(
        default_factory=list, description="Most used tools"
    )

    @classmethod
    def from_session_summary(cls, summary: "SessionSummary") -> "TaskSummary":
        """Convert from SessionSummary"""
        from frago.session.models import SessionSummary as SS

        return cls(
            total_duration_ms=summary.total_duration_ms,
            user_message_count=summary.user_message_count,
            assistant_message_count=summary.assistant_message_count,
            tool_call_count=summary.tool_call_count,
            tool_success_count=summary.tool_success_count,
            tool_error_count=summary.tool_error_count,
            most_used_tools=[
                ToolUsageStat(name=t.tool_name, count=t.count)
                for t in summary.most_used_tools
            ],
        )


class TaskStep(BaseModel):
    """Task step - for GUI display"""

    step_id: int = Field(..., ge=1, description="Step number")
    type: str = Field(..., description="Step type")
    timestamp: datetime = Field(..., description="Timestamp")
    content: str = Field(..., description="Content summary")
    tool_name: Optional[str] = Field(None, description="Tool name")
    tool_status: Optional[str] = Field(None, description="Tool call status")

    @classmethod
    def from_session_step(cls, step: "SessionStep") -> "TaskStep":
        """Convert from SessionStep"""
        return cls(
            step_id=step.step_id,
            type=step.type.value,
            timestamp=step.timestamp,
            content=step.content_summary,
            tool_name=None,
            tool_status=None,
        )


class TaskItem(BaseModel):
    """Task list item - for Tasks page"""

    session_id: str = Field(..., description="Session ID (unique identifier)")
    name: str = Field(..., description="Task name (extracted from first message)")
    status: GUITaskStatus = Field(..., description="Task status")
    started_at: datetime = Field(..., description="Start time")
    ended_at: Optional[datetime] = Field(None, description="End time")
    duration_ms: int = Field(0, ge=0, description="Duration (milliseconds)")
    step_count: int = Field(0, ge=0, description="Total step count")
    tool_call_count: int = Field(0, ge=0, description="Tool call count")
    last_activity: datetime = Field(..., description="Last activity time")
    project_path: str = Field(..., description="Associated project path")

    @classmethod
    def from_session(cls, session: "MonitoredSession") -> "TaskItem":
        """Convert from MonitoredSession"""
        from frago.session.models import SessionStatus
        from frago.session.storage import get_session_dir

        # Calculate duration (ensure all timestamps use UTC timezone)
        started = _ensure_utc(session.started_at)

        if session.ended_at:
            ended = _ensure_utc(session.ended_at)
            duration = ended - started
        else:
            now = datetime.now(timezone.utc)
            duration = now - started

        # Extract first user_message from steps.jsonl as task name
        name = cls._extract_task_name(session.session_id)

        # Map status
        status_map = {
            SessionStatus.RUNNING: GUITaskStatus.RUNNING,
            SessionStatus.COMPLETED: GUITaskStatus.COMPLETED,
            SessionStatus.ERROR: GUITaskStatus.ERROR,
            SessionStatus.CANCELLED: GUITaskStatus.CANCELLED,
        }
        gui_status = status_map.get(session.status, GUITaskStatus.RUNNING)

        return cls(
            session_id=session.session_id,
            name=name,
            status=gui_status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_ms=int(duration.total_seconds() * 1000),
            step_count=session.step_count,
            tool_call_count=session.tool_call_count,
            last_activity=session.last_activity,
            project_path=session.project_path,
        )

    @staticmethod
    def _extract_task_name(session_id: str, max_length: int = 100) -> str:
        """Extract task name from steps.jsonl

        Core strategy: Find the first valid assistant_message, then find the user_message
        with the closest timestamp that's earlier than it, and extract title from that message.

        This skips warmup messages (like "Warmup") and finds the user message that actually
        triggered the assistant response.

        Extraction priority:
        1. frago_task: Extract actual task from "## Current Task"
        2. command-args: Extract user input from <command-args>
        3. command-message: Extract command name as title
        4. Direct user input: First line of non-system content

        Args:
            session_id: Session ID
            max_length: Maximum name length

        Returns:
            Task name, or default name if extraction fails
        """
        import json
        import re
        from datetime import datetime
        from frago.session.storage import get_session_dir
        from frago.session.models import AgentType

        default_name = f"Task {session_id[:8]}..."

        def parse_timestamp(ts: str) -> datetime:
            """Parse timestamp, handling multiple formats"""
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        def extract_title_from_content(content: str) -> str | None:
            """Extract title from message content"""
            # 1. frago_task: Check if it's a /frago.* system prompt
            if content.startswith("# /frago"):
                task_match = re.search(r"## Current Task\s*\n+(.+?)(?:\n\n|$)", content, re.DOTALL)
                if task_match:
                    task = task_match.group(1).strip()
                    if task:
                        return task[:max_length] + "..." if len(task) > max_length else task
                return None  # frago prompt but no current task found, return None to continue search

            # 2. Try to extract user actual input from <command-args>
            args_match = re.search(r"<command-args>(.*?)(?:</command-args>|$)", content, re.DOTALL)
            if args_match:
                user_input = args_match.group(1).strip()
                user_input = re.sub(r"\.\.\.$", "", user_input).strip()
                if user_input:
                    return user_input[:max_length] + "..." if len(user_input) > max_length else user_input
                return None

            # 3. Extract command name from command-message
            cmd_match = re.search(r"<command-message>(\S+)\s+is running", content)
            if cmd_match:
                cmd_name = cmd_match.group(1)
                return f"/{cmd_name}"

            # 4. Remove system message tags, extract real content
            cleaned = re.sub(r"<command-message>.*?</command-message>", "", content, flags=re.DOTALL)
            cleaned = re.sub(r"<command-name>.*?</command-name>", "", cleaned, flags=re.DOTALL)
            cleaned = cleaned.strip()

            if cleaned:
                first_line = cleaned.split("\n")[0].strip()
                # Skip lines starting with # (usually system prompts)
                if first_line.startswith("#"):
                    return None
                if first_line:
                    return first_line[:max_length] + "..." if len(first_line) > max_length else first_line

            return None

        try:
            session_dir = get_session_dir(session_id, AgentType.CLAUDE)
            steps_path = session_dir / "steps.jsonl"

            if not steps_path.exists():
                return default_name

            # Read all steps
            steps = []
            with open(steps_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        steps.append(json.loads(line))

            if not steps:
                return default_name

            # Various forms of empty replies
            empty_replies = {"(empty reply)", "(empty)", "(Empty reply)", ""}

            # 1. Find first non-empty assistant_message
            first_valid_assistant = None
            for step in steps:
                if step.get("type") == "assistant_message":
                    content = step.get("content_summary", "") or step.get("content", "")
                    if content and content.strip() not in empty_replies:
                        first_valid_assistant = step
                        break

            if first_valid_assistant is None:
                return default_name

            assistant_ts = parse_timestamp(first_valid_assistant["timestamp"])

            # 2. Find user_message with timestamp earlier than assistant and closest to it
            candidates = []
            for step in steps:
                if step.get("type") == "user_message":
                    content = step.get("content_summary", "") or step.get("content", "")
                    # Skip system messages
                    if not content:
                        continue
                    if content.startswith("Caveat:") or content.startswith("<local-command"):
                        continue
                    if "<command-args></command-args>" in content:
                        continue

                    try:
                        step_ts = parse_timestamp(step["timestamp"])
                        if step_ts < assistant_ts:
                            candidates.append((step_ts, content))
                    except (KeyError, ValueError):
                        continue

            if not candidates:
                return default_name

            # Sort by timestamp, take the closest to assistant (i.e., the latest)
            candidates.sort(key=lambda x: x[0], reverse=True)

            # Try to extract title from each candidate
            for _, content in candidates:
                title = extract_title_from_content(content)
                if title:
                    return title

            return default_name
        except Exception:
            return default_name

    @staticmethod
    def should_display(session: "MonitoredSession") -> bool:
        """Determine if session should be displayed in task list

        Display criteria (any of):
        1. Running task
        2. Step count >= 10
        3. Has summary and step count >= 5

        Exclusion criteria:
        1. Step count < 5 and completed
        2. No assistant messages and step count < 10 (system session characteristics)

        Args:
            session: Session metadata

        Returns:
            Whether should be displayed
        """
        import json
        from frago.session.models import SessionStatus
        from frago.session.storage import get_session_dir

        # Always display running tasks
        if session.status == SessionStatus.RUNNING:
            return True

        # Display if step count >= 10
        if session.step_count >= 10:
            return True

        # Don't display if step count < 5 and completed
        if session.step_count < 5 and session.status == SessionStatus.COMPLETED:
            return False

        # Check if it's a system session (no assistant messages)
        if session.step_count < 10:
            session_dir = get_session_dir(session.session_id, session.agent_type)
            steps_file = session_dir / "steps.jsonl"
            if steps_file.exists():
                has_assistant = False
                try:
                    with open(steps_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            step = json.loads(line)
                            if step.get("type") == "assistant_message":
                                has_assistant = True
                                break
                except Exception:
                    pass

                # No assistant messages → system session, don't display
                if not has_assistant:
                    return False

        # Display if has summary and step count >= 5
        if session.step_count >= 5:
            session_dir = get_session_dir(session.session_id, session.agent_type)
            if (session_dir / "summary.json").exists():
                return True

        return False


class TaskDetail(BaseModel):
    """Task detail - for task detail page"""

    # Basic information (from TaskItem)
    session_id: str
    name: str
    status: GUITaskStatus
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: int
    project_path: str

    # Statistics
    step_count: int = Field(0, description="Total step count")
    tool_call_count: int = Field(0, description="Tool call count")
    user_message_count: int = Field(0, description="User message count")
    assistant_message_count: int = Field(0, description="Assistant message count")

    # Session content (paginated)
    steps: List[TaskStep] = Field(default_factory=list, description="Step list")
    steps_total: int = Field(0, description="Total steps")
    steps_offset: int = Field(0, description="Current offset")
    has_more_steps: bool = Field(False, description="Whether there are more steps")

    # Summary (after session completion)
    summary: Optional[TaskSummary] = Field(None, description="Session summary")

    @classmethod
    def from_session_data(
        cls,
        session: "MonitoredSession",
        steps: List["SessionStep"],
        summary: Optional["SessionSummary"] = None,
        offset: int = 0,
        limit: int = 50,
        total_steps: Optional[int] = None,
    ) -> "TaskDetail":
        """Build task detail from session data"""
        from frago.session.models import SessionStatus, StepType

        # Calculate message statistics
        user_count = sum(1 for s in steps if s.type == StepType.USER_MESSAGE)
        assistant_count = sum(1 for s in steps if s.type == StepType.ASSISTANT_MESSAGE)

        # Use passed total_steps or fall back to session.step_count
        actual_total = total_steps if total_steps is not None else session.step_count

        # Calculate duration (ensure all timestamps use UTC timezone)
        started = _ensure_utc(session.started_at)

        if session.ended_at:
            ended = _ensure_utc(session.ended_at)
            duration = ended - started
        else:
            now = datetime.now(timezone.utc)
            duration = now - started

        # Map status
        status_map = {
            SessionStatus.RUNNING: GUITaskStatus.RUNNING,
            SessionStatus.COMPLETED: GUITaskStatus.COMPLETED,
            SessionStatus.ERROR: GUITaskStatus.ERROR,
            SessionStatus.CANCELLED: GUITaskStatus.CANCELLED,
        }
        gui_status = status_map.get(session.status, GUITaskStatus.RUNNING)

        # Extract task name (reuse TaskItem's logic)
        name = TaskItem._extract_task_name(session.session_id)

        return cls(
            session_id=session.session_id,
            name=name,
            status=gui_status,
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_ms=int(duration.total_seconds() * 1000),
            project_path=session.project_path,
            step_count=actual_total,
            tool_call_count=session.tool_call_count,
            user_message_count=user_count,
            assistant_message_count=assistant_count,
            steps=[TaskStep.from_session_step(s) for s in steps],
            steps_total=actual_total,
            steps_offset=offset,
            has_more_steps=offset + len(steps) < actual_total,
            summary=TaskSummary.from_session_summary(summary) if summary else None,
        )
