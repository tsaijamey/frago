"""
Frago Session Module - Agent Session Monitoring and Data Persistence

Provides real-time monitoring and data storage capabilities for Agent tool execution sessions
such as Claude Code.

Core components:
- models: Session data models (MonitoredSession, SessionStep, ToolCallRecord, SessionSummary)
- parser: JSONL incremental parser
- storage: Session data persistent storage
- formatter: Terminal output formatter
- monitor: File system monitoring and session tracking

Environment variables:
- FRAGO_SESSION_DIR: Custom session storage directory (default ~/.frago/sessions/)
- FRAGO_CLAUDE_DIR: Custom Claude Code session directory (default ~/.claude/projects/)
- FRAGO_MONITOR_ENABLED: Whether to enable monitoring (default 1, set to 0 to disable)
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
from frago.session.service import (
    ActionContractError,
    SessionOntologyService,
    get_default_session_service,
)
from frago.session.store import (
    SessionOntologyRecord,
    SessionOntologyStore,
    get_default_session_store,
)

__all__ = [
    # Enum types
    "AgentType",
    "SessionStatus",
    "StepType",
    "ToolCallStatus",
    # Data models
    "MonitoredSession",
    "SessionStep",
    "ToolCallRecord",
    "SessionSummary",
    # Ontology Layer (Gate 3 & Gate 4)
    "ActionContractError",
    "SessionOntologyRecord",
    "SessionOntologyService",
    "SessionOntologyStore",
    "get_default_session_service",
    "get_default_session_store",
    "locate_session_file",
]


def __getattr__(name: str):
    if name == "locate_session_file":
        from frago.session.record_reader import locate_session_file

        return locate_session_file
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
