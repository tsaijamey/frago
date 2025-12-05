"""
Frago Session 模块 - Agent 会话监控与数据持久化

提供对 Claude Code 等 Agent 工具执行会话的实时监控和数据存储能力。

核心组件:
- models: 会话数据模型 (MonitoredSession, SessionStep, ToolCallRecord, SessionSummary)
- parser: JSONL 增量解析器
- storage: 会话数据持久化存储
- formatter: 终端输出格式化器
- monitor: 文件系统监控和会话跟踪

环境变量:
- FRAGO_SESSION_DIR: 自定义会话存储目录（默认 ~/.frago/sessions/）
- FRAGO_CLAUDE_DIR: 自定义 Claude Code 会话目录（默认 ~/.claude/projects/）
- FRAGO_MONITOR_ENABLED: 是否启用监控（默认 1，设为 0 禁用）
"""

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    SessionSummary,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
)

__all__ = [
    # 枚举类型
    "AgentType",
    "SessionStatus",
    "StepType",
    "ToolCallStatus",
    # 数据模型
    "MonitoredSession",
    "SessionStep",
    "ToolCallRecord",
    "SessionSummary",
]
