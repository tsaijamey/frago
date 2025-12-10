"""
Session 数据模型定义

定义 Agent 会话监控所需的所有数据结构，包括：
- 枚举类型：AgentType, SessionStatus, StepType, ToolCallStatus
- 核心实体：MonitoredSession, SessionStep, ToolCallRecord, SessionSummary
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举类型
# ============================================================


class AgentType(str, Enum):
    """Agent 工具类型标识"""

    CLAUDE = "claude"  # Claude Code
    CURSOR = "cursor"  # Cursor (预留)
    CLINE = "cline"  # Cline (预留)


class SessionStatus(str, Enum):
    """会话状态"""

    RUNNING = "running"  # 正在执行
    COMPLETED = "completed"  # 正常完成
    ERROR = "error"  # 异常终止
    CANCELLED = "cancelled"  # 用户取消


class StepType(str, Enum):
    """会话步骤类型"""

    USER_MESSAGE = "user_message"  # 用户输入消息
    ASSISTANT_MESSAGE = "assistant_message"  # 助手回复消息
    TOOL_CALL = "tool_call"  # 工具调用请求
    TOOL_RESULT = "tool_result"  # 工具执行结果
    SYSTEM_EVENT = "system_event"  # 系统事件（错误、重试等）


class ToolCallStatus(str, Enum):
    """工具调用状态"""

    PENDING = "pending"  # 等待执行
    SUCCESS = "success"  # 执行成功
    ERROR = "error"  # 执行失败


# ============================================================
# 核心数据模型
# ============================================================


class SessionStep(BaseModel):
    """会话步骤记录

    表示会话中的一个执行步骤。
    """

    step_id: int = Field(..., ge=1, description="步骤序号（从 1 开始）")
    session_id: str = Field(..., description="所属会话 ID")
    type: StepType = Field(..., description="步骤类型")
    timestamp: datetime = Field(..., description="步骤时间戳")
    content_summary: str = Field(
        ..., description="内容（完整内容）"
    )
    raw_uuid: str = Field(..., description="原始记录的 uuid")
    parent_uuid: Optional[str] = Field(None, description="父消息的 uuid")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ToolCallRecord(BaseModel):
    """工具调用记录

    表示一次工具调用的详细信息。
    """

    tool_call_id: str = Field(..., description="工具调用 ID（来自 Claude）")
    session_id: str = Field(..., description="所属会话 ID")
    step_id: int = Field(..., ge=1, description="关联的步骤序号")
    tool_name: str = Field(..., description="工具名称")
    input_summary: str = Field(..., description="输入参数摘要")
    called_at: datetime = Field(..., description="调用时间")
    result_summary: Optional[str] = Field(None, description="执行结果摘要")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    duration_ms: Optional[int] = Field(None, ge=0, description="执行耗时（毫秒）")
    status: ToolCallStatus = Field(
        default=ToolCallStatus.PENDING, description="调用状态"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class MonitoredSession(BaseModel):
    """监控会话

    表示一个被 Frago 监控的 Agent 执行会话。
    """

    session_id: str = Field(..., description="Claude Code 会话 ID")
    agent_type: AgentType = Field(..., description="Agent 类型标识")
    project_path: str = Field(..., description="项目绝对路径")
    source_file: str = Field(..., description="原始会话文件路径")
    started_at: datetime = Field(..., description="监控开始时间")
    ended_at: Optional[datetime] = Field(None, description="监控结束时间")
    status: SessionStatus = Field(
        default=SessionStatus.RUNNING, description="会话状态"
    )
    step_count: int = Field(default=0, ge=0, description="已记录步骤数")
    tool_call_count: int = Field(default=0, ge=0, description="工具调用次数")
    last_activity: datetime = Field(..., description="最后活动时间")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ToolUsageStats(BaseModel):
    """工具使用统计"""

    tool_name: str = Field(..., description="工具名称")
    count: int = Field(..., ge=0, description="使用次数")


class SessionSummary(BaseModel):
    """会话摘要

    会话结束后的统计摘要。
    """

    session_id: str = Field(..., description="会话 ID")
    total_duration_ms: int = Field(..., ge=0, description="总耗时（毫秒）")
    user_message_count: int = Field(default=0, ge=0, description="用户消息数")
    assistant_message_count: int = Field(default=0, ge=0, description="助手消息数")
    tool_call_count: int = Field(default=0, ge=0, description="工具调用总数")
    tool_success_count: int = Field(default=0, ge=0, description="成功的工具调用数")
    tool_error_count: int = Field(default=0, ge=0, description="失败的工具调用数")
    most_used_tools: List[ToolUsageStats] = Field(
        default_factory=list, description="使用最多的工具（前 5）"
    )
    model: Optional[str] = Field(None, description="使用的模型")
    final_status: SessionStatus = Field(..., description="最终状态")

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ============================================================
# 辅助函数
# ============================================================


def truncate_content(content: str, max_length: int = 0) -> str:
    """返回内容（不再截断）

    Args:
        content: 原始内容
        max_length: 已废弃，保留参数兼容性

    Returns:
        原始内容
    """
    return content


def extract_tool_input_summary(input_data: Dict[str, Any]) -> str:
    """从工具输入数据中提取摘要

    Args:
        input_data: 工具调用的 input 参数

    Returns:
        简洁的输入参数摘要
    """
    if not input_data:
        return "(无参数)"

    # 优先提取常见参数
    priority_keys = ["command", "file_path", "pattern", "query", "url", "content"]

    for key in priority_keys:
        if key in input_data:
            value = input_data[key]
            if isinstance(value, str):
                return truncate_content(f"{key}={value}", 100)

    # 如果没有优先参数，提取第一个参数
    first_key = next(iter(input_data.keys()), None)
    if first_key:
        value = input_data[first_key]
        if isinstance(value, str):
            return truncate_content(f"{first_key}={value}", 100)
        return f"{first_key}=..."

    return "(复杂参数)"
