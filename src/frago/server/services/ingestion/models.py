"""Data structures for the task ingestion layer."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"      # 消息到了，PA 还没看
    QUEUED = "queued"        # PA 决策了 run，等执行器取
    EXECUTING = "executing"  # 执行器正在跑
    COMPLETED = "completed"  # 终态
    FAILED = "failed"        # 终态


@dataclass
class IngestedTask:
    """A task ingested from an external channel into frago.

    唯一数据模型。内存 dict 是主操作对象，JSON 文件只是持久化镜像。
    字段按生命周期逐步回填。
    """

    # ── 消息入口写入（Ingestion Scheduler） ──
    id: str
    channel: str
    channel_message_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now())
    reply_context: dict[str, Any] = field(default_factory=dict)

    # ── PA 决策 run 时回填（数组，每次 append，消费取 [-1]）──
    run_descriptions: list[str] = field(default_factory=list)
    run_prompts: list[str] = field(default_factory=list)

    # ── 执行器启动 agent 后回填 ──
    session_id: str | None = None        # agent session / run_id
    pid: int | None = None               # agent 进程 PID

    # ── 执行完成后回填 ──
    result_summary: str | None = None
    error: str | None = None
    completed_at: datetime | None = None

    # ── 恢复跟踪 ──
    retry_count: int = 0
    recovery_count: int = 0
