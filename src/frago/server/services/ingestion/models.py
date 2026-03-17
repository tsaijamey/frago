"""Data structures for the task ingestion layer."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


# -- Thinking Architecture enums --


class SemanticType(Enum):
    """Exhaustive semantic classification for any language input."""

    STATEMENT = "statement"  # Information delivery — "服务器挂了", "这是报告"
    DIRECTIVE = "directive"  # Action request — "帮我查一下", "把这个发给张三"
    INQUIRY = "inquiry"  # Information request — "现在几点了", "任务完成了吗"
    META = "meta"  # System control — heartbeat, config change, status query


class ContextBinding(Enum):
    """How input relates to existing context."""

    ACTIVE_TASK_SUPPLEMENT = "active_supplement"  # Supplement to an active task
    COMPLETED_TASK_FOLLOWUP = "completed_followup"  # Follow-up on a completed task
    NEW_AFFAIR = "new_affair"  # Brand new affair, needs a new task
    NON_TRANSACTIONAL = "non_transactional"  # No transaction — chat, ack, idle reply


class ActionType(Enum):
    """Exhaustive action types after decision."""

    NO_ACTION = "no_action"  # Pure info intake, update context only
    RESPOND = "respond"  # Need to respond (answer, ack, clarify)
    EXECUTE = "execute"  # Need to trigger a concrete operation
    DELEGATE = "delegate"  # Beyond current scope, delegate to sub-agent


class ExecutionStrategy(Enum):
    """Layered execution strategy selection."""

    RECIPE_EXACT = "recipe_exact"  # Layer 1: exact match from recipe registry
    REPLY_DIRECT = "reply_direct"  # Layer 1: direct reply (status query etc.)
    RECIPE_SEMANTIC = "recipe_semantic"  # Layer 2: semantic match (Phase 3)
    AGENT_DELEGATE = "agent_delegate"  # Layer 3: delegate to sub-agent


# -- Thinking Architecture data models --


@dataclass
class TaskIndex:
    """Summary-level task index held by Primary Agent — not full details."""

    task_id: str
    channel: str
    one_line_summary: str  # ≤60 chars
    status: TaskStatus
    created_at: datetime
    last_activity_at: datetime
    reply_context_key: str | None = None  # Key for reply chain matching


@dataclass
class ExecutionPlan:
    """What to do and how."""

    strategy: ExecutionStrategy
    target: str  # recipe name / agent prompt / reply content
    params: dict[str, Any] | None = None


@dataclass
class TaskIndexUpdate:
    """Delta update for a single task index entry."""

    task_id: str
    new_summary: str | None = None
    new_status: TaskStatus | None = None


@dataclass
class StateDelta:
    """State changes after execution completes."""

    task_updates: list[TaskIndexUpdate] = field(default_factory=list)
    new_tasks: list[TaskIndex] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    context_compaction: bool = False


@dataclass
class ThinkingResult:
    """Complete result of a thinking architecture decision chain."""

    input_text: str

    # Q1
    semantic_type: SemanticType

    # Q2
    context_binding: ContextBinding

    # Q3
    action_type: ActionType

    # Q4 (None when action_type is NO_ACTION)
    execution_plan: ExecutionPlan | None = None

    # Q5 — filled after execution
    state_delta: StateDelta | None = None


@dataclass
class IngestedTask:
    """A task ingested from an external channel into frago."""

    id: str
    channel: str
    channel_message_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Filled after execution starts
    session_id: str | None = None
    result_summary: str | None = None
    completed_at: datetime | None = None
    error: str | None = None

    # Channel-specific context needed for reply (opaque to TaskStore/Scheduler)
    reply_context: dict[str, Any] = field(default_factory=dict)
