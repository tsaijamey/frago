"""
Terminal Output Formatter

Provides terminal display formatting capabilities for session monitoring data, including:
- Human-readable formatted output (default)
- JSON formatted output (--json-status mode)
- Emoji icon and color support
"""

import json
import sys
from datetime import datetime, timezone
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
# Icon Definitions
# ============================================================


class Icons:
    """Step type icons"""

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
# Formatting Functions
# ============================================================


def format_timestamp(dt: datetime) -> str:
    """Format timestamp to short format

    Args:
        dt: datetime object

    Returns:
        Formatted time string (HH:MM:SS)
    """
    return dt.strftime("%H:%M:%S")


def format_duration(ms: int) -> str:
    """Format duration

    Args:
        ms: Milliseconds

    Returns:
        Formatted duration string
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
    """Get icon corresponding to step type

    Args:
        step_type: Step type

    Returns:
        Icon string
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
    """Get label corresponding to step type

    Args:
        step_type: Step type

    Returns:
        Label string
    """
    label_map = {
        StepType.USER_MESSAGE: "User",
        StepType.ASSISTANT_MESSAGE: "Assistant",
        StepType.TOOL_CALL: "Tool Call",
        StepType.TOOL_RESULT: "Tool Result",
        StepType.SYSTEM_EVENT: "System",
    }
    return label_map.get(step_type, "Unknown")


# ============================================================
# Terminal Formatter
# ============================================================


class TerminalFormatter:
    """Terminal output formatter

    Formats session data into human-readable terminal output.
    """

    def __init__(self, output: TextIO = sys.stderr, use_icons: bool = True):
        """Initialize formatter

        Args:
            output: Output stream (default stderr, avoids interfering with pipes)
            use_icons: Whether to use emoji icons
        """
        self.output = output
        self.use_icons = use_icons

    def print(self, message: str) -> None:
        """Output message

        Args:
            message: Message content
        """
        print(message, file=self.output, flush=True)

    def format_session_start(self, session: MonitoredSession) -> str:
        """Format session start message

        Args:
            session: Monitored session object

        Returns:
            Formatted message
        """
        icon = Icons.SESSION_START if self.use_icons else ">"
        ts = format_timestamp(session.started_at)
        short_id = session.session_id[:8]
        return f"[{ts}] {icon} Session started (session: {short_id}...)"

    def format_session_end(
        self, session: MonitoredSession, summary: Optional[SessionSummary] = None
    ) -> str:
        """Format session end message

        Args:
            session: Monitored session object
            summary: Session summary (optional)

        Returns:
            Formatted message
        """
        if session.status == SessionStatus.ERROR:
            icon = Icons.SESSION_ERROR if self.use_icons else "X"
            status = "Terminated with error"
        else:
            icon = Icons.SESSION_END if self.use_icons else "*"
            status = "Session completed"

        ts = format_timestamp(session.ended_at or session.last_activity)

        if summary:
            duration = format_duration(summary.total_duration_ms)
            tools = summary.tool_call_count
            return f"[{ts}] {icon} {status} (duration: {duration}, tool calls: {tools})"
        else:
            return f"[{ts}] {icon} {status}"

    def format_step(self, step: SessionStep) -> str:
        """Format step message

        Args:
            step: Session step object

        Returns:
            Formatted message
        """
        icon = get_step_icon(step.type) if self.use_icons else "-"
        ts = format_timestamp(step.timestamp)
        label = get_step_label(step.type)
        content = step.content_summary

        return f"[{ts}] {icon} {label}: {content}"

    def format_tool_complete(self, tool_call: ToolCallRecord) -> str:
        """Format tool call complete message

        Args:
            tool_call: Tool call record

        Returns:
            Formatted message
        """
        if tool_call.status == ToolCallStatus.SUCCESS:
            icon = Icons.SUCCESS if self.use_icons else "+"
        else:
            icon = Icons.ERROR if self.use_icons else "!"

        ts = format_timestamp(tool_call.completed_at or tool_call.called_at)
        name = tool_call.tool_name
        duration = format_duration(tool_call.duration_ms or 0)

        return f"[{ts}] {icon} {name} completed ({duration})"

    def print_session_start(self, session: MonitoredSession) -> None:
        """Output session start message"""
        self.print(self.format_session_start(session))

    def print_session_end(
        self, session: MonitoredSession, summary: Optional[SessionSummary] = None
    ) -> None:
        """Output session end message"""
        self.print(self.format_session_end(session, summary))

    def print_step(self, step: SessionStep) -> None:
        """Output step message"""
        self.print(self.format_step(step))

    def print_tool_complete(self, tool_call: ToolCallRecord) -> None:
        """Output tool call complete message"""
        self.print(self.format_tool_complete(tool_call))


# ============================================================
# JSON Formatter
# ============================================================


class JsonFormatter:
    """JSON output formatter

    Formats session data into JSON output for easy machine processing.
    """

    def __init__(self, output: TextIO = sys.stdout):
        """Initialize formatter

        Args:
            output: Output stream
        """
        self.output = output

    def _output(self, event_type: str, data: Dict[str, Any]) -> None:
        """Output JSON event

        Args:
            event_type: Event type
            data: Event data
        """
        event = {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
        print(json.dumps(event, ensure_ascii=False), file=self.output, flush=True)

    def emit_session_start(self, session: MonitoredSession) -> None:
        """Output session start event"""
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
        """Output session end event"""
        data = {
            "session_id": session.session_id,
            "status": session.status.value,
            "ended_at": (session.ended_at or session.last_activity).isoformat(),
        }
        if summary:
            data["summary"] = summary.model_dump(mode="json")
        self._output("session_end", data)

    def emit_step(self, step: SessionStep) -> None:
        """Output step event"""
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
        """Output tool call complete event"""
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
# Formatter Factory
# ============================================================


def create_formatter(
    json_mode: bool = False,
    output: Optional[TextIO] = None,
    use_icons: bool = True,
):
    """Create formatter

    Args:
        json_mode: Whether to use JSON format
        output: Custom output stream
        use_icons: Whether to use emoji icons

    Returns:
        TerminalFormatter or JsonFormatter instance
    """
    if json_mode:
        return JsonFormatter(output or sys.stdout)
    else:
        return TerminalFormatter(output or sys.stderr, use_icons=use_icons)
