"""TaskBoard dataclass schema.

按 spec v1.0.1 §Design Core Concepts 定义对象树。Source frozen=True (Ce ask #2)。

Phase 4 (Yi #133 lock): TaskStatus enum 从 ingestion.models 迁入此模块 (旧
模块物理删). 取值与 board.Task.status Literal 对齐 (queued / executing /
completed / failed / resume_failed / replied) plus legacy PENDING (映射到
msg-level awaiting_decision 语义, 仅 cli/api 兼容用).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal


class TaskStatus(Enum):
    """Legacy task status (Phase 4 迁入). Values map to board.Task.status Literal.

    Yi #133 + HUMAN #152 lock: replaces frago.server.services.ingestion.models
    .TaskStatus (now physically deleted). value 字符串与 board 内部 Literal 一致.
    """

    PENDING = "pending"        # legacy: 消息收到但 PA 未决策 (msg-level awaiting_decision)
    QUEUED = "queued"          # PA 决策了 run, 等执行器取 (board.Task.status="queued")
    EXECUTING = "executing"    # 执行器正在跑 (board.Task.status="executing")
    COMPLETED = "completed"    # 终态 (board.Task.status="completed")
    FAILED = "failed"          # 终态 (board.Task.status="failed")


# ── Legacy IngestedTask / SubTask (Phase 4 迁入 taskboard 层) ────────────────
# Yi #133 + HUMAN #152 + Orchestrator #158: ingestion/models.py 物理删除,
# 其内的旧 IngestedTask + SubTask 迁入此模块. 仍为 executor / task_lifecycle 提供
# 执行上下文 (channel / reply_context / sub_tasks 等 board.Task 不直接持有的字段).
# 后续 phase 可继续合并到 board.Task / board.Session.


@dataclass
class SubTask:
    """Legacy: 一次 run 的完整上下文. Executor 每次启动 / completion 时填充字段.

    PA 决策时 → description, prompt
    执行器启动时 → session_id, claude_session_id, pid, status=EXECUTING
    执行完成时 → result_summary/error, status=COMPLETED/FAILED, completed_at
    """

    description: str = ""
    prompt: str = ""
    session_id: str | None = None         # frago run_id
    claude_session_id: str | None = None  # Claude Code session UUID
    pid: int | None = None
    result_summary: str | None = None
    error: str | None = None
    status: str = "pending"               # 值域同 TaskStatus
    created_at: datetime = field(default_factory=lambda: datetime.now())
    completed_at: datetime | None = None


@dataclass
class IngestedTask:
    """Legacy: A task ingested from an external channel into frago.

    Phase 4 (Yi #133): 从 ingestion/models 迁入 taskboard 层. 与 board.Task 是
    不同抽象 — IngestedTask 持有执行上下文 (channel / reply_context / sub_tasks),
    board.Task 持有状态机 (status / intent / session). Executor 用 IngestedTask
    跑实际执行, board 是单一持久化层.
    """

    id: str
    channel: str
    channel_message_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now())
    reply_context: dict[str, Any] = field(default_factory=dict)
    thread_id: str | None = None
    sub_tasks: list[SubTask] = field(default_factory=list)
    retry_count: int = 0
    recovery_count: int = 0

    @property
    def current_sub(self) -> SubTask | None:
        return self.sub_tasks[-1] if self.sub_tasks else None

    @property
    def session_id(self) -> str | None:
        s = self.current_sub
        return s.session_id if s else None

    @property
    def claude_session_id(self) -> str | None:
        s = self.current_sub
        return s.claude_session_id if s else None

    @property
    def pid(self) -> int | None:
        s = self.current_sub
        return s.pid if s else None

    @property
    def result_summary(self) -> str | None:
        s = self.current_sub
        return s.result_summary if s else None

    @property
    def error(self) -> str | None:
        s = self.current_sub
        return s.error if s else None

    @property
    def completed_at(self) -> datetime | None:
        s = self.current_sub
        return s.completed_at if s else None

    @property
    def run_descriptions(self) -> list[str]:
        return [s.description for s in self.sub_tasks]

    @property
    def run_prompts(self) -> list[str]:
        return [s.prompt for s in self.sub_tasks]


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
    # Executor / recovery bookkeeping (Yi spec v1.2 freeze: single-source on board).
    retry_count: int = 0
    recovery_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


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
