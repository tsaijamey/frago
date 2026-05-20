"""Regression for Bug I (2026-05-20): recovery must not sweep up a live
executing task.

recover_pending_tasks runs every heartbeat and re-enqueues non-terminal
tasks for PA, incrementing recovery_count each time and marking them stale
after MAX_RECOVERY=2. The old code did this for `executing` tasks whose
sub-agent was still actively running — within ~2 ticks the task was marked
FAILED("stale") while the agent kept working, then the executor flipped it
FAILED→COMPLETED on real exit, plus minutes of "already recovered" log spam.

Recovery is only for tasks orphaned by a crash (executing, no live PID).
A live executing task must be skipped entirely.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from frago.server.services.taskboard import _reset_for_tests, set_board
from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.ingestor import Ingestor
from frago.server.services.taskboard.models import Intent
from frago.server.services.taskboard.timeline import Timeline
from frago.server.services.task_lifecycle import TaskLifecycle


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


def _board(tmp_path) -> TaskBoard:
    return TaskBoard(Timeline(tmp_path / "timeline.jsonl"))


def _executing_run_task(board: TaskBoard, pid: int):
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="etf", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_live",
        sender_id="u1", text="分析", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )
    task = board.append_task(
        "feishu:om_live", Intent(prompt="a\n\nb"), task_type="run", by="test",
    )
    board.mark_task_executing(task.task_id, by="test")
    board.update_task_session(
        task.task_id, run_id="quant-trading",
        claude_session_id="cs1", pid=pid, by="test",
    )
    return task


def test_live_executing_task_not_recovered(tmp_path, monkeypatch):
    """Executing task with a live PID → recovery skips it, no recovery_count
    increment, no stale marking."""
    board = _board(tmp_path)
    set_board(board)
    task = _executing_run_task(board, pid=4242)

    # Force liveness check to report alive
    monkeypatch.setattr(
        "frago.server.services.task_lifecycle._pid_alive", lambda _pid: True,
    )

    msgs = TaskLifecycle().recover_pending_tasks()

    assert msgs == [], "live executing task must not be recovered/re-enqueued"
    assert board.get_task(task.task_id).status == "executing", (
        "live task must stay executing, not be marked stale"
    )
    assert board.get_task(task.task_id).recovery_count == 0


def test_dead_executing_task_is_recovered(tmp_path, monkeypatch):
    """Executing task whose PID is gone (crash-orphaned) → recovery still
    kicks in, so genuine orphans aren't stranded."""
    board = _board(tmp_path)
    set_board(board)
    task = _executing_run_task(board, pid=999999)

    monkeypatch.setattr(
        "frago.server.services.task_lifecycle._pid_alive", lambda _pid: False,
    )

    msgs = TaskLifecycle().recover_pending_tasks()

    assert len(msgs) == 1, "crash-orphaned executing task should be recovered"
    assert msgs[0]["task_id"] == task.task_id
    assert board.get_task(task.task_id).recovery_count == 1
