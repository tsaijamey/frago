"""
Session Data Models

Defines all data structures required for Agent session monitoring, including:
- Enum types: AgentType, SessionStatus, StepType, ToolCallStatus
- Core entities: MonitoredSession, SessionStep, ToolCallRecord, SessionSummary
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# Enum Types
# ============================================================


class AgentType(str, Enum):
    """Agent tool type identifier"""

    CLAUDE = "claude"  # Claude Code
    CURSOR = "cursor"  # Cursor (reserved)
    CLINE = "cline"  # Cline (reserved)


class SessionStatus(str, Enum):
    """Session status"""

    RUNNING = "running"  # Currently running
    COMPLETED = "completed"  # Completed normally
    ERROR = "error"  # Terminated with error
    CANCELLED = "cancelled"  # Cancelled by user


class StepType(str, Enum):
    """Session step type"""

    USER_MESSAGE = "user_message"  # User input message
    ASSISTANT_MESSAGE = "assistant_message"  # Assistant response message
    TOOL_CALL = "tool_call"  # Tool call request
    TOOL_RESULT = "tool_result"  # Tool execution result
    SYSTEM_EVENT = "system_event"  # System event (error, retry, etc.)


class ToolCallStatus(str, Enum):
    """Tool call status"""

    PENDING = "pending"  # Waiting for execution
    SUCCESS = "success"  # Executed successfully
    ERROR = "error"  # Execution failed


class SessionSource(str, Enum):
    """Session source - distinguishes how the session was created"""

    TERMINAL = "terminal"  # Created via terminal/CLI
    WEB = "web"  # Created via web interface
    UNKNOWN = "unknown"  # Legacy data or cannot be determined


# ============================================================
# Core Data Models
# ============================================================


class SessionStep(BaseModel):
    """Session step record

    Represents an execution step in a session.
    """

    step_id: int = Field(..., ge=1, description="Step sequence number (starts from 1)")
    session_id: str = Field(..., description="Associated session ID")
    type: StepType = Field(..., description="Step type")
    timestamp: datetime = Field(..., description="Step timestamp")
    content_summary: str = Field(
        ..., description="Content (full content)"
    )
    raw_uuid: str = Field(..., description="UUID of the original record")
    parent_uuid: Optional[str] = Field(None, description="UUID of the parent message")
    tool_call_id: Optional[str] = Field(None, description="Tool call ID for pairing tool_call and tool_result")
    tool_name: Optional[str] = Field(None, description="Tool name for tool_call steps")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ToolCallRecord(BaseModel):
    """Tool call record

    Represents detailed information about a tool call.
    """

    tool_call_id: str = Field(..., description="Tool call ID (from Claude)")
    session_id: str = Field(..., description="Associated session ID")
    step_id: int = Field(..., ge=1, description="Associated step sequence number")
    tool_name: str = Field(..., description="Tool name")
    input_summary: str = Field(..., description="Input parameter summary")
    called_at: datetime = Field(..., description="Call time")
    result_summary: Optional[str] = Field(None, description="Execution result summary")
    completed_at: Optional[datetime] = Field(None, description="Completion time")
    duration_ms: Optional[int] = Field(None, ge=0, description="Execution duration (milliseconds)")
    status: ToolCallStatus = Field(
        default=ToolCallStatus.PENDING, description="Call status"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class MonitoredSession(BaseModel):
    """Monitored session

    Represents an Agent execution session monitored by Frago.
    """

    session_id: str = Field(..., description="Claude Code session ID")
    agent_type: AgentType = Field(..., description="Agent type identifier")
    project_path: str = Field(..., description="Project absolute path")
    name: Optional[str] = Field(None, description="Session name from first user message")
    source_file: str = Field(..., description="Original session file path")
    started_at: datetime = Field(..., description="Monitoring start time")
    ended_at: Optional[datetime] = Field(None, description="Monitoring end time")
    status: SessionStatus = Field(
        default=SessionStatus.RUNNING, description="Session status"
    )
    step_count: int = Field(default=0, ge=0, description="Number of recorded steps")
    tool_call_count: int = Field(default=0, ge=0, description="Number of tool calls")
    last_activity: datetime = Field(..., description="Last activity time")
    source: SessionSource = Field(
        default=SessionSource.UNKNOWN,
        description="Session source (terminal/web/unknown)",
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ToolUsageStats(BaseModel):
    """Tool usage statistics"""

    tool_name: str = Field(..., description="Tool name")
    count: int = Field(..., ge=0, description="Usage count")


class SessionSummary(BaseModel):
    """Session summary

    Statistical summary after session ends.
    """

    session_id: str = Field(..., description="Session ID")
    total_duration_ms: int = Field(..., ge=0, description="Total duration (milliseconds)")
    user_message_count: int = Field(default=0, ge=0, description="User message count")
    assistant_message_count: int = Field(default=0, ge=0, description="Assistant message count")
    tool_call_count: int = Field(default=0, ge=0, description="Total tool call count")
    tool_success_count: int = Field(default=0, ge=0, description="Successful tool call count")
    tool_error_count: int = Field(default=0, ge=0, description="Failed tool call count")
    most_used_tools: List[ToolUsageStats] = Field(
        default_factory=list, description="Most used tools (top 5)"
    )
    model: Optional[str] = Field(None, description="Model used")
    final_status: SessionStatus = Field(..., description="Final status")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ============================================================
# Helper Functions
# ============================================================


def truncate_content(content: str, max_length: int = 0) -> str:
    """Return content (no longer truncates)

    Args:
        content: Original content
        max_length: Deprecated, kept for parameter compatibility

    Returns:
        Original content
    """
    return content


def extract_tool_input_summary(input_data: Dict[str, Any]) -> str:
    """Extract summary from tool input data

    Args:
        input_data: Tool call input parameters

    Returns:
        Concise input parameter summary
    """
    if not input_data:
        return "(no parameters)"

    # Extract common parameters first
    priority_keys = ["command", "file_path", "pattern", "query", "url", "content"]

    for key in priority_keys:
        if key in input_data:
            value = input_data[key]
            if isinstance(value, str):
                return truncate_content(f"{key}={value}", 100)

    # If no priority parameters, extract first parameter
    first_key = next(iter(input_data.keys()), None)
    if first_key:
        value = input_data[first_key]
        if isinstance(value, str):
            return truncate_content(f"{first_key}={value}", 100)
        return f"{first_key}=..."

    return "(complex parameters)"
