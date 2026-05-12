"""Phase A acceptance: board public API used by executor / daemon.

spec 20260512-msg-task-board-redesign v1.2 (single-source freeze):
TaskStore is being torn out; board.timeline.jsonl is the only persistence.
The methods exercised below replace the corresponding TaskStore.* surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from frago.server.services.taskboard import (
    _reset_for_tests,
    set_board,
)
from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import (
    IllegalTransitionError,
    Intent,
    Msg,
    Source,
)
from frago.server.services.taskboard.timeline import Timeline


def _fresh_board(tmp_path: Path) -> tuple[TaskBoard, Path]:
    """Build a clean board rooted at tmp_path (no real ~/.frago touch)."""
    timeline_path = tmp_path / "timeline.jsonl"
    timeline = Timeline(timeline_path)
    return TaskBoard(timeline), timeline_path


def _seed_thread_msg(board: TaskBoard, *, channel="feishu") -> str:
    """Create one thread + one msg, return the msg_id used."""
    board.create_thread(
        thread_id="T_A",
        origin="external",
        subkind=channel,
        root_summary="root",
        by="test",
    )
    msg = Msg(
        msg_id="m_001",
        status="received",
        source=Source(
            channel=channel,
            text="hello",
            sender_id="u1",
            parent_ref=None,
            received_at=__import__("datetime").datetime.now().astimezone(),
        ),
    )
    board.append_msg("T_A", msg, by="test")
    return "m_001"


@pytest.fixture(autouse=True)
def _reset():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_get_queued_tasks_returns_only_queued(tmp_path):
    board, _ = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p1"), task_type="run", by="test")
    t2 = board.append_task(msg_id, Intent(prompt="p2"), task_type="run", by="test")
    # Move t2 → executing so only t1 remains queued
    board.mark_task_executing(t2.task_id, by="test")

    queued = board.get_queued_tasks()
    assert [t.task_id for t in queued] == [t1.task_id]


def test_get_executing_tasks(tmp_path):
    board, _ = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p1"), task_type="run", by="test")
    board.mark_task_executing(t1.task_id, by="test")

    executing = board.get_executing_tasks()
    assert [t.task_id for t in executing] == [t1.task_id]


def test_get_task_and_get_msg_and_thread_for_task(tmp_path):
    board, _ = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    assert board.get_task(t1.task_id).task_id == t1.task_id
    assert board.get_msg_for_task(t1.task_id).msg_id == msg_id
    assert board.get_thread_for_task(t1.task_id).thread_id == "T_A"
    assert board.get_task("nonexistent") is None
    assert board.get_msg_for_task("nope") is None
    assert board.get_thread_for_task("nope") is None


def test_increment_retry_count_writes_timeline(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    assert board.increment_retry_count(t1.task_id, by="executor") == 1
    assert board.increment_retry_count(t1.task_id, by="executor") == 2
    assert board.get_task(t1.task_id).retry_count == 2

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    retry_entries = [e for e in lines if e.get("data_type") == "task_retry"]
    assert len(retry_entries) == 2
    assert retry_entries[-1]["data"]["retry_count"] == 2
    assert retry_entries[-1]["task_id"] == t1.task_id


def test_increment_recovery_count(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    new_count = board.increment_recovery_count(t1.task_id, by="daemon")
    assert new_count == 1
    assert board.get_task(t1.task_id).recovery_count == 1

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    recovery_entries = [e for e in lines if e.get("data_type") == "task_recovery"]
    assert len(recovery_entries) == 1


def test_update_task_session_writes_fields(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    board.update_task_session(
        t1.task_id,
        run_id="run_xyz",
        claude_session_id="csid_abc",
        pid=12345,
        by="executor",
    )
    task = board.get_task(t1.task_id)
    assert task.session is not None
    assert task.session.run_id == "run_xyz"
    assert task.session.claude_session_id == "csid_abc"
    assert task.session.pid == 12345

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    sess_entries = [e for e in lines if e.get("data_type") == "task_session_updated"]
    assert len(sess_entries) == 1
    assert sess_entries[0]["data"]["run_id"] == "run_xyz"
    assert sess_entries[0]["data"]["pid"] == 12345


def test_mark_task_executing_transitions_status(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    board.mark_task_executing(t1.task_id, by="executor")
    assert board.get_task(t1.task_id).status == "executing"

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    state_entries = [
        e for e in lines
        if e.get("data_type") == "task_state"
        and e.get("data", {}).get("status") == "executing"
    ]
    assert len(state_entries) == 1
    assert state_entries[0]["data"]["prev_status"] == "queued"


def test_mark_task_executing_idempotent_and_invalid(tmp_path):
    board, _ = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")

    board.mark_task_executing(t1.task_id, by="executor")
    # 2nd call no-op (already executing)
    board.mark_task_executing(t1.task_id, by="executor")
    # mark completed then attempt executing again raises
    board.mark_task_completed(t1.task_id, summary="ok", by="executor")
    with pytest.raises(IllegalTransitionError):
        board.mark_task_executing(t1.task_id, by="executor")


def test_mark_task_completed_records_result_and_state(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")
    board.mark_task_executing(t1.task_id, by="executor")
    board.mark_task_completed(t1.task_id, summary="all done", by="executor")

    task = board.get_task(t1.task_id)
    assert task.status == "completed"
    assert task.result is not None
    assert task.result.summary == "all done"

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    completed_state = [
        e for e in lines
        if e.get("data_type") == "task_state"
        and e.get("data", {}).get("status") == "completed"
    ]
    assert len(completed_state) == 1


def test_mark_task_failed_records_error(tmp_path):
    board, timeline_path = _fresh_board(tmp_path)
    set_board(board)
    msg_id = _seed_thread_msg(board)
    t1 = board.append_task(msg_id, Intent(prompt="p"), task_type="run", by="test")
    board.mark_task_executing(t1.task_id, by="executor")
    board.mark_task_failed(t1.task_id, error="boom", by="executor")

    task = board.get_task(t1.task_id)
    assert task.status == "failed"
    assert task.result.error == "boom"

    lines = [json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()]
    failed_state = [
        e for e in lines
        if e.get("data_type") == "task_state"
        and e.get("data", {}).get("status") == "failed"
    ]
    assert len(failed_state) == 1
    assert failed_state[0]["data"]["error"] == "boom"


def test_missing_task_records_rejection(tmp_path):
    board, _ = _fresh_board(tmp_path)
    set_board(board)
    # No task exists yet — every mutation that targets task_id="nope" should
    # record a rejection rather than crash.
    assert board.increment_retry_count("nope", by="x") == 0
    assert board.increment_recovery_count("nope", by="x") == 0
    board.update_task_session(
        "nope", run_id="r", claude_session_id=None, pid=None, by="x",
    )
    board.mark_task_executing("nope", by="x")
    board.mark_task_completed("nope", summary="", by="x")
    board.mark_task_failed("nope", error="e", by="x")

    rejections = board.view_for_pa()["recent_rejections"]
    assert len(rejections) >= 6  # at least one per missing-task action
