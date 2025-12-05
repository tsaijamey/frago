"""
终端输出格式化器

提供会话监控数据的终端显示格式化能力，包括：
- 人类可读的格式化输出（默认）
- JSON 格式输出（--json-status 模式）
- emoji 图标和颜色支持
"""

import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, TextIO

from frago.session.models import (
    MonitoredSession,
    SessionStatus,
    SessionStep,
    SessionSummary,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
)


# ============================================================
# 图标定义
# ============================================================


class Icons:
    """步骤类型图标"""

    SESSION_START = "🚀"
    SESSION_END = "✨"
    SESSION_ERROR = "❌"

    USER_MESSAGE = "📝"
    ASSISTANT_MESSAGE = "🤖"
    TOOL_CALL = "🔧"
    TOOL_RESULT = "✅"
    TOOL_ERROR = "⚠️"
    SYSTEM_EVENT = "ℹ️"

    PENDING = "⏳"
    SUCCESS = "✅"
    ERROR = "❌"


# ============================================================
# 格式化函数
# ============================================================


def format_timestamp(dt: datetime) -> str:
    """格式化时间戳为短格式

    Args:
        dt: datetime 对象

    Returns:
        格式化的时间字符串 (HH:MM:SS)
    """
    return dt.strftime("%H:%M:%S")


def format_duration(ms: int) -> str:
    """格式化持续时间

    Args:
        ms: 毫秒数

    Returns:
        格式化的持续时间字符串
    """
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f}s"
    else:
        minutes = ms // 60000
        seconds = (ms % 60000) / 1000
        return f"{minutes}m{seconds:.0f}s"


def get_step_icon(step_type: StepType) -> str:
    """获取步骤类型对应的图标

    Args:
        step_type: 步骤类型

    Returns:
        图标字符串
    """
    icon_map = {
        StepType.USER_MESSAGE: Icons.USER_MESSAGE,
        StepType.ASSISTANT_MESSAGE: Icons.ASSISTANT_MESSAGE,
        StepType.TOOL_CALL: Icons.TOOL_CALL,
        StepType.TOOL_RESULT: Icons.TOOL_RESULT,
        StepType.SYSTEM_EVENT: Icons.SYSTEM_EVENT,
    }
    return icon_map.get(step_type, "•")


def get_step_label(step_type: StepType) -> str:
    """获取步骤类型对应的标签

    Args:
        step_type: 步骤类型

    Returns:
        标签字符串
    """
    label_map = {
        StepType.USER_MESSAGE: "用户",
        StepType.ASSISTANT_MESSAGE: "助手",
        StepType.TOOL_CALL: "工具调用",
        StepType.TOOL_RESULT: "工具结果",
        StepType.SYSTEM_EVENT: "系统",
    }
    return label_map.get(step_type, "未知")


# ============================================================
# 终端格式化器
# ============================================================


class TerminalFormatter:
    """终端输出格式化器

    将会话数据格式化为人类可读的终端输出。
    """

    def __init__(self, output: TextIO = sys.stderr, use_icons: bool = True):
        """初始化格式化器

        Args:
            output: 输出流（默认 stderr，避免干扰管道）
            use_icons: 是否使用 emoji 图标
        """
        self.output = output
        self.use_icons = use_icons

    def print(self, message: str) -> None:
        """输出消息

        Args:
            message: 消息内容
        """
        print(message, file=self.output, flush=True)

    def format_session_start(self, session: MonitoredSession) -> str:
        """格式化会话开始消息

        Args:
            session: 监控会话对象

        Returns:
            格式化的消息
        """
        icon = Icons.SESSION_START if self.use_icons else ">"
        ts = format_timestamp(session.started_at)
        short_id = session.session_id[:8]
        return f"[{ts}] {icon} 会话已启动 (session: {short_id}...)"

    def format_session_end(
        self, session: MonitoredSession, summary: Optional[SessionSummary] = None
    ) -> str:
        """格式化会话结束消息

        Args:
            session: 监控会话对象
            summary: 会话摘要（可选）

        Returns:
            格式化的消息
        """
        if session.status == SessionStatus.ERROR:
            icon = Icons.SESSION_ERROR if self.use_icons else "X"
            status = "异常终止"
        else:
            icon = Icons.SESSION_END if self.use_icons else "*"
            status = "会话完成"

        ts = format_timestamp(session.ended_at or session.last_activity)

        if summary:
            duration = format_duration(summary.total_duration_ms)
            tools = summary.tool_call_count
            return f"[{ts}] {icon} {status} (耗时: {duration}, 工具调用: {tools}次)"
        else:
            return f"[{ts}] {icon} {status}"

    def format_step(self, step: SessionStep) -> str:
        """格式化步骤消息

        Args:
            step: 会话步骤对象

        Returns:
            格式化的消息
        """
        icon = get_step_icon(step.type) if self.use_icons else "-"
        ts = format_timestamp(step.timestamp)
        label = get_step_label(step.type)
        content = step.content_summary

        return f"[{ts}] {icon} {label}: {content}"

    def format_tool_complete(self, tool_call: ToolCallRecord) -> str:
        """格式化工具调用完成消息

        Args:
            tool_call: 工具调用记录

        Returns:
            格式化的消息
        """
        if tool_call.status == ToolCallStatus.SUCCESS:
            icon = Icons.SUCCESS if self.use_icons else "+"
        else:
            icon = Icons.ERROR if self.use_icons else "!"

        ts = format_timestamp(tool_call.completed_at or tool_call.called_at)
        name = tool_call.tool_name
        duration = format_duration(tool_call.duration_ms or 0)

        return f"[{ts}] {icon} {name} 完成 ({duration})"

    def print_session_start(self, session: MonitoredSession) -> None:
        """输出会话开始消息"""
        self.print(self.format_session_start(session))

    def print_session_end(
        self, session: MonitoredSession, summary: Optional[SessionSummary] = None
    ) -> None:
        """输出会话结束消息"""
        self.print(self.format_session_end(session, summary))

    def print_step(self, step: SessionStep) -> None:
        """输出步骤消息"""
        self.print(self.format_step(step))

    def print_tool_complete(self, tool_call: ToolCallRecord) -> None:
        """输出工具调用完成消息"""
        self.print(self.format_tool_complete(tool_call))


# ============================================================
# JSON 格式化器
# ============================================================


class JsonFormatter:
    """JSON 输出格式化器

    将会话数据格式化为 JSON 输出，便于机器处理。
    """

    def __init__(self, output: TextIO = sys.stdout):
        """初始化格式化器

        Args:
            output: 输出流
        """
        self.output = output

    def _output(self, event_type: str, data: Dict[str, Any]) -> None:
        """输出 JSON 事件

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        event = {"type": event_type, "timestamp": datetime.now().isoformat(), **data}
        print(json.dumps(event, ensure_ascii=False), file=self.output, flush=True)

    def emit_session_start(self, session: MonitoredSession) -> None:
        """输出会话开始事件"""
        self._output(
            "session_start",
            {
                "session_id": session.session_id,
                "agent_type": session.agent_type.value,
                "project_path": session.project_path,
                "started_at": session.started_at.isoformat(),
            },
        )

    def emit_session_end(
        self, session: MonitoredSession, summary: Optional[SessionSummary] = None
    ) -> None:
        """输出会话结束事件"""
        data = {
            "session_id": session.session_id,
            "status": session.status.value,
            "ended_at": (session.ended_at or session.last_activity).isoformat(),
        }
        if summary:
            data["summary"] = summary.model_dump(mode="json")
        self._output("session_end", data)

    def emit_step(self, step: SessionStep) -> None:
        """输出步骤事件"""
        self._output(
            "step",
            {
                "session_id": step.session_id,
                "step_id": step.step_id,
                "type": step.type.value,
                "content_summary": step.content_summary,
                "step_timestamp": step.timestamp.isoformat(),
            },
        )

    def emit_tool_complete(self, tool_call: ToolCallRecord) -> None:
        """输出工具调用完成事件"""
        self._output(
            "tool_complete",
            {
                "session_id": tool_call.session_id,
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.tool_name,
                "status": tool_call.status.value,
                "duration_ms": tool_call.duration_ms,
                "result_summary": tool_call.result_summary,
            },
        )


# ============================================================
# 格式化器工厂
# ============================================================


def create_formatter(
    json_mode: bool = False,
    output: Optional[TextIO] = None,
    use_icons: bool = True,
):
    """创建格式化器

    Args:
        json_mode: 是否使用 JSON 格式
        output: 自定义输出流
        use_icons: 是否使用 emoji 图标

    Returns:
        TerminalFormatter 或 JsonFormatter 实例
    """
    if json_mode:
        return JsonFormatter(output or sys.stdout)
    else:
        return TerminalFormatter(output or sys.stderr, use_icons=use_icons)
