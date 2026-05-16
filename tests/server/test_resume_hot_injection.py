"""End-to-end tests for PA resume hot-injection
(spec 20260501-pa-resume-hot-injection).

These tests cover the Python writer half (ResumeInbox + executor.execute_resume).
Rust reader correctness is covered by frago-core's own integration tests.
Spec 20260512 v1.2 freeze: Executor takes a board, not a TaskStore.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from frago.server.services import resume_inbox as inbox_mod
from frago.server.services.executor import Executor
from frago.server.services.resume_inbox import PENDING_DIR_NAME, ResumeInbox


def _make_board_task(task_id, run_id, csid):
    """Build a MagicMock board.Task with .session populated."""
    t = MagicMock()
    sess = MagicMock()
    sess.run_id = run_id
    sess.claude_session_id = csid
    t.session = sess
    t.task_id = task_id
    return t


def _executor_with_board_task(task, *, thread_id="thread-1"):
    board = MagicMock()
    board.get_task = MagicMock(return_value=task)
    thread = MagicMock()
    thread.thread_id = thread_id
    board.get_thread_for_task = MagicMock(return_value=thread)
    ex = Executor(
        board=board,
        pa_enqueue_message=AsyncMock(),
        broadcast_pa_event=AsyncMock(),
    )
    return ex


@pytest.fixture(autouse=True)
def isolated_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_mod, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path / "projects"


@pytest.fixture(autouse=True)
def silent_trace(tmp_path, monkeypatch):
    from frago.server.services import trace as trace_mod
    monkeypatch.setattr(trace_mod, "TRACE_DIR", tmp_path / "traces")


@pytest.mark.asyncio
async def test_single_session_resume(isolated_inbox):
    """PA decision → inbox file with the prompt body and session id."""
    csid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    task = _make_board_task("t_1", "run-A", csid)
    ex = _executor_with_board_task(task)

    result = await ex.execute_resume("t_1", "立刻终止当前 fetch")
    assert result["status"] == "ok"

    inbox = isolated_inbox / "run-A" / csid / PENDING_DIR_NAME
    files = sorted(inbox.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["claude_session_id"] == csid
    assert payload["prompt"] == "立刻终止当前 fetch"
    assert payload["task_id"] == "t_1"
    assert payload["schema_version"] == 1


@pytest.mark.asyncio
async def test_concurrent_sessions_isolated():
    """Two sessions resume in parallel → each inbox sees only its own prompt."""
    csid_a = "11111111-1111-4111-8111-111111111111"
    csid_b = "22222222-2222-4222-8222-222222222222"

    task_a = _make_board_task("t_A", "run-A", csid_a)
    task_b = _make_board_task("t_B", "run-B", csid_b)
    tasks = {"t_A": task_a, "t_B": task_b}
    threads = {"t_A": MagicMock(thread_id="thr-A"), "t_B": MagicMock(thread_id="thr-B")}

    board = MagicMock()
    board.get_task = MagicMock(side_effect=lambda tid: tasks[tid])
    board.get_thread_for_task = MagicMock(side_effect=lambda tid: threads[tid])
    ex = Executor(
        board=board,
        pa_enqueue_message=AsyncMock(),
        broadcast_pa_event=AsyncMock(),
    )

    await ex.execute_resume("t_A", "for A")
    await ex.execute_resume("t_B", "for B")

    a_pending = ResumeInbox.list_pending("run-A", csid_a)
    b_pending = ResumeInbox.list_pending("run-B", csid_b)
    assert [p.prompt for p in a_pending] == ["for A"]
    assert [p.prompt for p in b_pending] == ["for B"]


@pytest.mark.asyncio
async def test_no_tool_use_keeps_pending(isolated_inbox):
    """Without a hook drain, the pending file stays put for the next tool_use."""
    csid = "33333333-3333-4333-8333-333333333333"
    ex = _executor_with_board_task(_make_board_task("t_1", "run-A", csid))

    await ex.execute_resume("t_1", "delayed prompt")
    inbox = isolated_inbox / "run-A" / csid / PENDING_DIR_NAME
    assert len(list(inbox.glob("*.json"))) == 1

    # Simulate "agent never called a tool" by waiting briefly and re-checking.
    time.sleep(0.05)
    assert len(list(inbox.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_multiple_pending_merged_in_order():
    """Multiple resume decisions accumulate; lexicographic file order == arrival order."""
    csid = "44444444-4444-4444-8444-444444444444"
    ex = _executor_with_board_task(_make_board_task("t_1", "run-A", csid))

    prompts = ["one", "two", "three", "four"]
    for p in prompts:
        await ex.execute_resume("t_1", p)
        time.sleep(0.005)  # ensure distinct timestamps when test runs fast

    pending = ResumeInbox.list_pending("run-A", csid)
    assert [p.prompt for p in pending] == prompts


@pytest.mark.asyncio
async def test_corrupt_pending_skipped(isolated_inbox):
    """Garbage JSON in the inbox is skipped silently by list_pending."""
    csid = "55555555-5555-4555-8555-555555555555"
    ex = _executor_with_board_task(_make_board_task("t_1", "run-A", csid))

    await ex.execute_resume("t_1", "real-prompt")

    inbox = isolated_inbox / "run-A" / csid / PENDING_DIR_NAME
    (inbox / "0000-00-00T00-00-00__bogus.json").write_text("not json", encoding="utf-8")

    pending = ResumeInbox.list_pending("run-A", csid)
    assert [p.prompt for p in pending] == ["real-prompt"]
