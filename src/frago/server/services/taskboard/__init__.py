"""TaskBoard package: 单一 timeline.jsonl 持久化 + 四 Applier 闭环。

spec: .claude/docs/spec-driven-plan/20260512-msg-task-board-redesign.md
"""

from __future__ import annotations

import threading
from pathlib import Path

from frago.server.services.taskboard.board import TaskBoard, boot
from frago.server.services.taskboard.models import (
    Intent,
    Msg,
    RejectionRecord,
    Result,
    Session,
    Source,
    Task,
    TaskStatus,
    Thread,
    TimelineEntry,
)
from frago.server.services.taskboard.timeline import Timeline, ulid_new

_board_singleton: TaskBoard | None = None
_singleton_lock = threading.Lock()


def get_board() -> TaskBoard:
    """Process-wide TaskBoard singleton. 首次调用 boot ~/.frago timeline。

    生产路径 (ingestion/scheduler / executor / scheduler_service / reflection_tick)
    共享同一 board, 单一 timeline.jsonl 源。
    """
    global _board_singleton
    if _board_singleton is None:
        with _singleton_lock:
            if _board_singleton is None:
                _board_singleton = boot(Path.home() / ".frago")
    return _board_singleton


def set_board(board: TaskBoard) -> None:
    """Test hook: 注入自定义 board (覆盖单例)."""
    global _board_singleton
    with _singleton_lock:
        _board_singleton = board


def _reset_for_tests() -> None:
    """Test hook: 清空单例 (下次 get_board 重新 boot)."""
    global _board_singleton
    with _singleton_lock:
        _board_singleton = None


__all__ = [
    "TaskBoard",
    "Thread",
    "Msg",
    "Task",
    "TaskStatus",
    "Source",
    "Intent",
    "Session",
    "Result",
    "TimelineEntry",
    "RejectionRecord",
    "Timeline",
    "ulid_new",
    "boot",
    "get_board",
    "set_board",
]
