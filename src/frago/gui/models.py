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


class TaskStatus(Enum):
    """Task execution status (for existing GUI task management)."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


# ============================================================
# 011-gui-tasks-redesign: 新增任务状态枚举（用于 Tasks 页面显示）
# ============================================================


class GUITaskStatus(str, Enum):
    """任务状态（GUI Tasks 页面展示用）

    使用字符串枚举以便 JSON 序列化。
    颜色映射：
    - RUNNING: 黄色 (var(--accent-warning))
    - COMPLETED: 绿色 (var(--accent-success))
    - ERROR: 红色 (var(--accent-error))
    - CANCELLED: 红色 (var(--accent-error))
    """

    RUNNING = "running"  # 进行中 - 黄色
    COMPLETED = "completed"  # 已完成 - 绿色
    ERROR = "error"  # 出错 - 红色
    CANCELLED = "cancelled"  # 已取消 - 红色

    @property
    def color(self) -> str:
        """返回状态对应的 CSS 颜色变量"""
        colors = {
            GUITaskStatus.RUNNING: "var(--accent-warning)",
            GUITaskStatus.COMPLETED: "var(--accent-success)",
            GUITaskStatus.ERROR: "var(--accent-error)",
            GUITaskStatus.CANCELLED: "var(--accent-error)",
        }
        return colors[self]

    @property
    def icon(self) -> str:
        """返回状态图标"""
        icons = {
            GUITaskStatus.RUNNING: "●",
            GUITaskStatus.COMPLETED: "✓",
            GUITaskStatus.ERROR: "✗",
            GUITaskStatus.CANCELLED: "○",
        }
        return icons[self]

    @property
    def label(self) -> str:
        """返回状态标签（中文）"""
        labels = {
            GUITaskStatus.RUNNING: "进行中",
            GUITaskStatus.COMPLETED: "已完成",
            GUITaskStatus.ERROR: "出错",
            GUITaskStatus.CANCELLED: "已取消",
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
    - 新增 TIPS 页面（默认启动页）
    - 新增 TASKS 页面（原 HOME 重命名）
    - 新增 TASK_DETAIL 页面（任务详情）
    - 移除 HISTORY（合并到 TASKS）
    """

    TIPS = "tips"  # 新增：Tips 页面（默认）
    TASKS = "tasks"  # 新增：Tasks 页面（原 home）
    TASK_DETAIL = "task_detail"  # 新增：任务详情页
    HOME = "home"  # 保留：兼容旧代码
    RECIPES = "recipes"  # 保留
    RECIPE_DETAIL = "recipe_detail"  # 保留
    SKILLS = "skills"  # 保留
    HISTORY = "history"  # 保留：兼容旧代码
    SETTINGS = "settings"  # 保留


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


# ============================================================
# 011-gui-tasks-redesign: Tasks 页面数据模型
# ============================================================


class ToolUsageStat(BaseModel):
    """工具使用统计"""

    name: str = Field(..., description="工具名称")
    count: int = Field(..., ge=0, description="使用次数")


class TaskSummary(BaseModel):
    """任务摘要 - 会话完成后生成"""

    total_duration_ms: int = Field(..., ge=0, description="总耗时")
    user_message_count: int = Field(0, description="用户消息数")
    assistant_message_count: int = Field(0, description="助手消息数")
    tool_call_count: int = Field(0, description="工具调用总数")
    tool_success_count: int = Field(0, description="成功的工具调用")
    tool_error_count: int = Field(0, description="失败的工具调用")
    most_used_tools: List[ToolUsageStat] = Field(
        default_factory=list, description="最常用工具"
    )

    @classmethod
    def from_session_summary(cls, summary: "SessionSummary") -> "TaskSummary":
        """从 SessionSummary 转换"""
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
    """任务步骤 - GUI 展示用"""

    step_id: int = Field(..., ge=1, description="步骤序号")
    type: str = Field(..., description="步骤类型")
    timestamp: datetime = Field(..., description="时间戳")
    content: str = Field(..., description="内容摘要")
    tool_name: Optional[str] = Field(None, description="工具名称")
    tool_status: Optional[str] = Field(None, description="工具调用状态")

    @classmethod
    def from_session_step(cls, step: "SessionStep") -> "TaskStep":
        """从 SessionStep 转换"""
        return cls(
            step_id=step.step_id,
            type=step.type.value,
            timestamp=step.timestamp,
            content=step.content_summary,
            tool_name=None,
            tool_status=None,
        )


class TaskItem(BaseModel):
    """任务列表项 - 用于 Tasks 页面"""

    session_id: str = Field(..., description="会话 ID（唯一标识）")
    name: str = Field(..., description="任务名称（从首条消息提取）")
    status: GUITaskStatus = Field(..., description="任务状态")
    started_at: datetime = Field(..., description="开始时间")
    ended_at: Optional[datetime] = Field(None, description="结束时间")
    duration_ms: int = Field(0, ge=0, description="持续时间（毫秒）")
    step_count: int = Field(0, ge=0, description="步骤总数")
    tool_call_count: int = Field(0, ge=0, description="工具调用次数")
    last_activity: datetime = Field(..., description="最后活动时间")
    project_path: str = Field(..., description="关联项目路径")

    @classmethod
    def from_session(cls, session: "MonitoredSession") -> "TaskItem":
        """从 MonitoredSession 转换"""
        from frago.session.models import SessionStatus
        from frago.session.storage import get_session_dir

        # 计算持续时间
        # 确保时区一致性
        started = session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

        if session.ended_at:
            ended = session.ended_at
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            duration = ended - started
        else:
            now = datetime.now(timezone.utc)
            duration = now - started

        # 从 steps.jsonl 提取第一条 user_message 作为任务名称
        name = cls._extract_task_name(session.session_id)

        # 映射状态
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
        """从 steps.jsonl 提取任务名称

        核心策略：找到第一条有效的 assistant_message，然后找时间戳最接近
        且早于它的 user_message，从该消息提取标题。

        这样可以跳过预热消息（如 "Warmup"），找到真正触发 assistant 回复的用户消息。

        提取优先级：
        1. frago_task: 从 "## 当前任务" 提取实际任务
        2. command-args: 从 <command-args> 提取用户输入
        3. command-message: 提取命令名作为标题
        4. 直接用户输入: 第一行非系统内容

        Args:
            session_id: 会话 ID
            max_length: 名称最大长度

        Returns:
            任务名称，如果无法提取则返回默认名称
        """
        import json
        import re
        from datetime import datetime
        from frago.session.storage import get_session_dir
        from frago.session.models import AgentType

        default_name = f"Task {session_id[:8]}..."

        def parse_timestamp(ts: str) -> datetime:
            """解析时间戳，处理多种格式"""
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        def extract_title_from_content(content: str) -> str | None:
            """从消息内容提取标题"""
            # 1. frago_task: 检查是否为 /frago.* 系统 prompt
            if content.startswith("# /frago"):
                task_match = re.search(r"## 当前任务\s*\n+(.+?)(?:\n\n|$)", content, re.DOTALL)
                if task_match:
                    task = task_match.group(1).strip()
                    if task:
                        return task[:max_length] + "..." if len(task) > max_length else task
                return None  # frago prompt 但没找到当前任务，返回 None 继续查找

            # 2. 尝试从 <command-args> 提取用户实际输入
            args_match = re.search(r"<command-args>(.*?)(?:</command-args>|$)", content, re.DOTALL)
            if args_match:
                user_input = args_match.group(1).strip()
                user_input = re.sub(r"\.\.\.$", "", user_input).strip()
                if user_input:
                    return user_input[:max_length] + "..." if len(user_input) > max_length else user_input
                return None

            # 3. 提取 command-message 中的命令名
            cmd_match = re.search(r"<command-message>(\S+)\s+is running", content)
            if cmd_match:
                cmd_name = cmd_match.group(1)
                return f"/{cmd_name}"

            # 4. 移除系统消息标签，提取真实内容
            cleaned = re.sub(r"<command-message>.*?</command-message>", "", content, flags=re.DOTALL)
            cleaned = re.sub(r"<command-name>.*?</command-name>", "", cleaned, flags=re.DOTALL)
            cleaned = cleaned.strip()

            if cleaned:
                first_line = cleaned.split("\n")[0].strip()
                # 跳过以 # 开头的标题行（通常是系统 prompt）
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

            # 读取所有步骤
            steps = []
            with open(steps_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        steps.append(json.loads(line))

            if not steps:
                return default_name

            # 空回复的各种表达形式
            empty_replies = {"(空回复)", "(empty)", "(Empty reply)", ""}

            # 1. 找第一条非空的 assistant_message
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

            # 2. 找时间戳早于 assistant 且最接近的 user_message
            candidates = []
            for step in steps:
                if step.get("type") == "user_message":
                    content = step.get("content_summary", "") or step.get("content", "")
                    # 跳过系统消息
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

            # 按时间戳排序，取最接近 assistant 的（即最晚的）
            candidates.sort(key=lambda x: x[0], reverse=True)

            # 依次尝试提取标题
            for _, content in candidates:
                title = extract_title_from_content(content)
                if title:
                    return title

            return default_name
        except Exception:
            return default_name

    @staticmethod
    def should_display(session: "MonitoredSession") -> bool:
        """判断会话是否应该在任务列表中展示

        展示条件（满足任一）：
        1. 正在运行的任务
        2. 步骤数 >= 10
        3. 有 summary 且步骤数 >= 5

        排除条件：
        1. 步骤数 < 5 且已完成
        2. 无 assistant 消息 且 步骤数 < 10（系统会话特征）

        Args:
            session: 会话元数据

        Returns:
            是否应该展示
        """
        import json
        from frago.session.models import SessionStatus
        from frago.session.storage import get_session_dir

        # 正在运行的任务始终展示
        if session.status == SessionStatus.RUNNING:
            return True

        # 步骤数 >= 10 展示
        if session.step_count >= 10:
            return True

        # 步骤数 < 5 且已完成，不展示
        if session.step_count < 5 and session.status == SessionStatus.COMPLETED:
            return False

        # 检查是否为系统会话（无 assistant 消息）
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

                # 无 assistant 消息 → 系统会话，不展示
                if not has_assistant:
                    return False

        # 有 summary 且步骤数 >= 5 展示
        if session.step_count >= 5:
            session_dir = get_session_dir(session.session_id, session.agent_type)
            if (session_dir / "summary.json").exists():
                return True

        return False


class TaskDetail(BaseModel):
    """任务详情 - 用于任务详情页"""

    # 基本信息（来自 TaskItem）
    session_id: str
    name: str
    status: GUITaskStatus
    started_at: datetime
    ended_at: Optional[datetime]
    duration_ms: int
    project_path: str

    # 统计信息
    step_count: int = Field(0, description="步骤总数")
    tool_call_count: int = Field(0, description="工具调用次数")
    user_message_count: int = Field(0, description="用户消息数")
    assistant_message_count: int = Field(0, description="助手消息数")

    # 会话内容（分页）
    steps: List[TaskStep] = Field(default_factory=list, description="步骤列表")
    steps_total: int = Field(0, description="步骤总数")
    steps_offset: int = Field(0, description="当前偏移量")
    has_more_steps: bool = Field(False, description="是否有更多步骤")

    # 摘要（会话完成后）
    summary: Optional[TaskSummary] = Field(None, description="会话摘要")

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
        """从会话数据构建任务详情"""
        from frago.session.models import SessionStatus, StepType

        # 计算消息统计
        user_count = sum(1 for s in steps if s.type == StepType.USER_MESSAGE)
        assistant_count = sum(1 for s in steps if s.type == StepType.ASSISTANT_MESSAGE)

        # 使用传入的 total_steps 或回退到 session.step_count
        actual_total = total_steps if total_steps is not None else session.step_count

        # 计算持续时间
        # 确保时区一致性
        started = session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

        if session.ended_at:
            ended = session.ended_at
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            duration = ended - started
        else:
            now = datetime.now(timezone.utc)
            duration = now - started

        # 映射状态
        status_map = {
            SessionStatus.RUNNING: GUITaskStatus.RUNNING,
            SessionStatus.COMPLETED: GUITaskStatus.COMPLETED,
            SessionStatus.ERROR: GUITaskStatus.ERROR,
            SessionStatus.CANCELLED: GUITaskStatus.CANCELLED,
        }
        gui_status = status_map.get(session.status, GUITaskStatus.RUNNING)

        # 提取任务名称（复用 TaskItem 的逻辑）
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
