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
class SubTask:
    """一次 run 的完整上下文。PA 每次决策 run/resume 时 append 一个。

    字段按生命周期逐步回填：
      PA 决策时 → description, prompt
      执行器启动时 → session_id, claude_session_id, pid, status=EXECUTING
      执行完成时 → result_summary/error, status=COMPLETED/FAILED, completed_at
    """

    description: str = ""
    prompt: str = ""
    session_id: str | None = None         # frago run_id (Run 实例目录名)
    claude_session_id: str | None = None  # Claude Code session UUID (JSONL 文件名)
    pid: int | None = None                # agent 进程 PID
    result_summary: str | None = None
    error: str | None = None
    status: str = "pending"               # 独立于 task 级 status，值域同 TaskStatus
    created_at: datetime = field(default_factory=lambda: datetime.now())
    completed_at: datetime | None = None


@dataclass
class IngestedTask:
    """A task ingested from an external channel into frago.

    唯一数据模型。内存 dict 是主操作对象，JSON 文件只是持久化镜像。
    字段按生命周期逐步回填。

    run 级信息统一收进 sub_tasks，每次 PA 决策 run 时 append 一个 SubTask。
    消费端取 sub_tasks[-1] 获取当前 run 上下文。
    """

    # ── 消息入口写入（Ingestion Scheduler） ──
    id: str
    channel: str
    channel_message_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now())
    reply_context: dict[str, Any] = field(default_factory=dict)

    # ── run 级信息（每次 PA 决策 run 时 append）──
    sub_tasks: list[SubTask] = field(default_factory=list)

    # ── 恢复跟踪 ──
    retry_count: int = 0
    recovery_count: int = 0

    # ── 便捷属性：兼容消费端 task.xxx 访问模式 ──
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
