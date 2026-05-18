"""Tests for Executor.execute_resume hot-injection path
(spec 20260501-pa-resume-hot-injection).

Phase B (spec 20260512 freeze): board is the single source — these tests
inject a MagicMock board exposing get_task / get_thread_for_task.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from frago.server.services import resume_inbox as inbox_mod
from frago.server.services.executor import Executor
from frago.server.services.resume_inbox import ResumeInbox


def _make_board_task(
    *,
    session_run_id: str | None = None,
    claude_session_id: str | None = None,
):
    """Build a MagicMock board.Task with .session.run_id / claude_session_id."""
    t = MagicMock()
    if session_run_id is None and claude_session_id is None:
        t.session = None
    else:
        sess = MagicMock()
        sess.run_id = session_run_id
        sess.claude_session_id = claude_session_id
        t.session = sess
    return t


def _make_executor(*, board_task_return, thread_id="T_hot"):
    board = MagicMock()
    board.get_task = MagicMock(return_value=board_task_return)
    thread = MagicMock()
    thread.thread_id = thread_id
    board.get_thread_for_task = MagicMock(
        return_value=thread if board_task_return is not None else None,
    )
    ex = Executor(
        board=board,
        pa_enqueue_message=AsyncMock(),
        broadcast_pa_event=AsyncMock(),
    )
    return ex, board


@pytest.fixture(autouse=True)
def isolated_inbox(tmp_path, monkeypatch):
    """Redirect ResumeInbox writes into tmp_path so tests don't pollute ~/.frago."""
    monkeypatch.setattr(inbox_mod, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path / "projects"


@pytest.mark.asyncio
async def test_resume_fails_when_task_missing(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    ex, _board = _make_executor(board_task_return=None)
    result = await ex.execute_resume("t_nonexistent", "new prompt")
    assert result["status"] == "failed"
    assert result["reason"] == "task_not_found"


@pytest.mark.asyncio
async def test_resume_fails_when_session_id_missing(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    task = _make_board_task(session_run_id=None, claude_session_id=None)
    ex, _board = _make_executor(board_task_return=task)
    result = await ex.execute_resume("t_1", "new prompt")
    assert result["status"] == "failed"
    assert result["reason"] == "missing_session_id"


@pytest.mark.asyncio
async def test_resume_fails_when_claude_session_id_missing(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    task = _make_board_task(session_run_id="run-A", claude_session_id=None)
    ex, _board = _make_executor(board_task_return=task)
    result = await ex.execute_resume("t_1", "new prompt")
    assert result["status"] == "failed"
    assert result["reason"] == "missing_claude_session_id"


@pytest.mark.asyncio
async def test_resume_writes_inbox_file(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    csid = "11111111-1111-4111-8111-111111111111"
    task = _make_board_task(session_run_id="run-A", claude_session_id=csid)
    ex, _board = _make_executor(board_task_return=task)

    result = await ex.execute_resume("t_1", "补充新规则")
    assert result["status"] == "ok"
    assert result["claude_session_id"] == csid

    pending = ResumeInbox.list_pending("run-A", csid)
    assert len(pending) == 1
    assert pending[0].prompt == "补充新规则"
    assert pending[0].task_id == "t_1"


@pytest.mark.asyncio
async def test_resume_does_not_kill_process(tmp_path, monkeypatch):
    """Hot-injection MUST NOT touch the running sub-agent process."""
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    csid = "22222222-2222-4222-8222-222222222222"
    task = _make_board_task(session_run_id="run-A", claude_session_id=csid)
    ex, _board = _make_executor(board_task_return=task)

    kill_called = []

    def _spy(*args, **_kwargs):
        kill_called.append(args)

    monkeypatch.setattr("os.kill", _spy)

    result = await ex.execute_resume("t_1", "新指令")
    assert result["status"] == "ok"
    assert kill_called == []


@pytest.mark.asyncio
async def test_resume_multiple_pending_preserved(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")

    csid = "33333333-3333-4333-8333-333333333333"
    task = _make_board_task(session_run_id="run-A", claude_session_id=csid)
    ex, _board = _make_executor(board_task_return=task)

    await ex.execute_resume("t_1", "first")
    await ex.execute_resume("t_1", "second")
    await ex.execute_resume("t_1", "third")

    pending = ResumeInbox.list_pending("run-A", csid)
    assert [p.prompt for p in pending] == ["first", "second", "third"]
