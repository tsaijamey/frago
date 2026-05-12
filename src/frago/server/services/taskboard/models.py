"""TaskBoard dataclass schema.

按 spec v1.0.1 §Design Core Concepts 定义对象树。Source frozen=True (Ce ask #2)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ── Thread / Msg / Task 三层 ─────────────────────────────────────────────────


@dataclass
class Thread:
    thread_id: str
    status: Literal["active", "dormant", "closed", "archived"]
    origin: Literal["external", "internal", "scheduled"]
    subkind: str
    root_summary: str
    created_at: datetime
    last_active_at: datetime
    senders: set[str] = field(default_factory=set)
    msgs: list[Msg] = field(default_factory=list)
    # B-2b: 取代 ThreadStore 的 tags + run_instance_id 字段
    tags: list[str] = field(default_factory=list)
    run_instance_id: str | None = None


@dataclass
class Msg:
    msg_id: str
    status: Literal[
        "received",
        "awaiting_decision",
        "dispatched",
        "closed",
        "dismissed",
    ]
    source: Source
    tasks: list[Task] = field(default_factory=list)


@dataclass(frozen=True)
class Source:
    """历史事实只读 (Ce ask #2: frozen=True)。"""

    channel: str
    text: str
    sender_id: str
    parent_ref: str | None
    received_at: datetime
    reply_context: dict[str, Any] | None = None


@dataclass
class Task:
    task_id: str
    status: Literal[
        "queued",
        "executing",
        "completed",
        "failed",
        "resume_failed",
        "replied",
    ]
    type: Literal["run", "reply"]
    intent: Intent
    session: Session | None = None
    result: Result | None = None


@dataclass
class Intent:
    prompt: str  # 首行 ≤80 字摘要 + 空行 + 正文 (Applier 校验, Phase 1 实施)


@dataclass
class Session:
    run_id: str
    claude_session_id: str | None
    pid: int | None
    started_at: datetime
    ended_at: datetime | None = None


@dataclass
class Result:
    summary: str
    error: str | None = None


# ── Timeline 与 reject 记录 ────────────────────────────────────────────────


@dataclass
class TimelineEntry:
    """append-only, 单一持久化点 ~/.frago/timeline/timeline.jsonl。"""

    entry_id: str
    ts: datetime
    data_type: str
    by: str
    thread_id: str | None = None
    msg_id: str | None = None
    task_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class RejectionRecord:
    """view_for_pa.recent_rejections 暴露给 PA。"""

    ts: datetime
    reason: str
    offending_msg_id: str | None
    offending_task_id: str | None
    original_action: str
    original_prompt_head: str


class IllegalTransitionError(RuntimeError):
    """状态机非法 transition 时由 board 公有方法抛出。"""


class DuplicateMarkerError(RuntimeError):
    """同 thread_id 第二次 archive_marker。Phase 2 vacuum 路径实施。"""


class PostArchiveAppendError(RuntimeError):
    """thread 已归档后又被 append entry。Phase 1 applier 实施。"""


class ClaudeSessionNotFoundError(RuntimeError):
    """Case A spawn_resume 时 CSID 已失效。Phase 1 ResumeApplier 实施。"""
