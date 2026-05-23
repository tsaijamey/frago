"""Phase 3 tests: per-thread PA session routing, thread_id backfill, fallback.

Spec: 20260522-pa-per-conversation-session Phase 3.

Acceptance criteria (6 spec test points):
  1. Two chat_ids → two AgentSession internal_ids; each bootstrap only its own thread
  2. PA reply to thread A structurally cannot deliver to thread B (群级错发回归)
  3. 9 message types without thread_id correctly backfilled via _resolve_thread_id
  4. schedule_failed → fallback session (no crash)
  5. Serial dispatch: one thread at a time
  6. view_for_pa(thread_id=...) backward compat: None = full, specific = filtered
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from frago.server.services.primary_agent_service import PrimaryAgentService
from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import (
    Intent,
    Msg,
    Source,
    Task,
)
from frago.server.services.taskboard.timeline import Timeline, ulid_new

# ── helpers ──────────────────────────────────────────────────────────────────


def _fresh_pa():
    """Create a fresh PrimaryAgentService bypassing singleton."""
    svc = PrimaryAgentService.__new__(PrimaryAgentService)
    svc.__init__()
    return svc


def _make_timeline(tmp_path):
    path = tmp_path / "timeline.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return Timeline(path)


def _make_board(tmp_path) -> TaskBoard:
    board = TaskBoard(_make_timeline(tmp_path))
    return board


def _add_thread(board: TaskBoard, tid: str | None = None, chat_id: str | None = None) -> str:
    thread_id = tid or ulid_new()
    tags = [f"conv:feishu:{chat_id}"] if chat_id else []
    board.create_thread(
        thread_id=thread_id,
        origin="external",
        subkind="feishu",
        root_summary="test",
        by="test",
        tags=tags,
    )
    return thread_id


def _add_msg(board: TaskBoard, thread_id: str, msg_id: str, channel: str = "feishu") -> None:
    msg = Msg(
        msg_id=msg_id,
        status="awaiting_decision",
        source=Source(
            channel=channel,
            text="hello",
            sender_id="u1",
            parent_ref=None,
            received_at=__import__("datetime").datetime.now(),
            reply_context={"chat_id": "oc_test"},
        ),
    )
    board.append_msg(thread_id, msg, by="test")


# ── _resolve_thread_id (spec test point 3) ──────────────────────────────────


def test_resolve_thread_id_internal_reflection_routes_to_fallback(tmp_path):
    """internal_reflection has no board thread → fallback (None), never binds a session.

    Regression (2026-05-23 生产事故): 旧实现直接返回 reflection 原始 thread_id,
    后续 bind_pa_session 因 board 无该 thread 抛 thread missing, PA 会话创建崩溃,
    每个 reflection tick 必崩。Spec §不做什么 4: 仅 origin=external 绑专属会话。
    """
    board = _make_board(tmp_path)
    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        tid = svc._resolve_thread_id({"type": "internal_reflection", "thread_id": "tid_native"})
    assert tid is None


def test_resolve_thread_id_external_thread_id_direct(tmp_path):
    """A message carrying an external thread_id directly still routes to its session."""
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "user_message", "thread_id": tid})
    assert result == tid


def test_resolve_thread_id_from_task_id(tmp_path):
    """Messages with task_id → thread resolved via board.get_thread_for_task."""
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    msg_id = f"om_{ulid_new()[:8]}"
    _add_msg(board, tid, msg_id)
    # Add a task to the msg
    msg = board._find_msg(msg_id)
    task = Task(
        task_id="task_001",
        status="queued",
        type="run",
        intent=Intent(prompt="test"),
    )
    msg.tasks.append(task)

    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "agent_completed", "task_id": "task_001"})
    assert result == tid


def test_resolve_thread_id_from_msg_id(tmp_path):
    """Messages with msg_id only → thread resolved via board.thread_id_of_msg."""
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    _add_msg(board, tid, "om_resolve_msg")

    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "user_message", "msg_id": "om_resolve_msg"})
    assert result == tid


def test_resolve_thread_id_schedule_failed_no_id(tmp_path):
    """schedule_failed has neither task_id nor msg_id → returns None (fallback)."""
    board = _make_board(tmp_path)

    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "schedule_failed", "name": "test"})
    assert result is None


def test_resolve_thread_id_run_failed_with_msg_id(tmp_path):
    """run_failed carries msg_id → resolved via thread_id_of_msg."""
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    _add_msg(board, tid, "om_run_fail")

    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "run_failed", "msg_id": "om_run_fail"})
    assert result == tid


def test_resolve_thread_id_unknown_msg_type_no_match(tmp_path):
    """Messages whose msg_id/task_id don't match any board thread → None (fallback)."""
    board = _make_board(tmp_path)

    with patch("frago.server.services.primary_agent_service.get_board", return_value=board):
        svc = _fresh_pa()
        result = svc._resolve_thread_id({"type": "user_message", "msg_id": "nonexistent"})
    assert result is None


# ── _session_for: create / cache per thread (spec test point 1) ─────────────


def test_session_for_creates_and_caches(tmp_path):
    """_session_for creates a session for a thread, caches it, subsequent calls return cache."""
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    svc = _fresh_pa()

    # Mock AgentService.start_task_attached to return a fake session
    fake_internal_id = "int_001"
    fake_session = MagicMock()
    fake_session.is_running = True

    async def fake_start_task_attached(**_kwargs):
        from frago.server.services.agent_service import AgentService
        AgentService._attached_sessions[fake_internal_id] = fake_session
        return {"status": "ok", "internal_id": fake_internal_id}

    async def fake_wait_for_session_id(*_args, **_kwargs):
        return "claude_sess_001"

    with patch.multiple(
        svc,
        _wait_for_session_id=fake_wait_for_session_id,
    ), patch(
        "frago.server.services.agent_service.AgentService.start_task_attached",
        side_effect=fake_start_task_attached,
    ), patch(
        "frago.server.services.primary_agent_service.get_board",
        return_value=board,
    ):
        import asyncio
        sess = asyncio.run(svc._session_for(tid))

    assert sess is fake_session
    assert svc._session_ids.get(tid) == "claude_sess_001"
    assert board.get_thread(tid)["pa_session_id"] == "claude_sess_001"

    # Second call returns cache
    sess2 = asyncio.run(svc._session_for(tid))
    assert sess2 is fake_session


def test_session_for_two_threads_two_sessions(tmp_path):
    """Two threads each get their own AgentSession, distinct session_ids."""
    board = _make_board(tmp_path)
    tid_a = _add_thread(board, chat_id="oc_A")
    tid_b = _add_thread(board, chat_id="oc_B")
    svc = _fresh_pa()

    call_count = 0

    async def fake_start_task_attached(**_kwargs):
        nonlocal call_count
        call_count += 1
        fake_internal_id = f"int_{call_count}"
        fake_session = MagicMock()
        fake_session.is_running = True
        from frago.server.services.agent_service import AgentService
        AgentService._attached_sessions[fake_internal_id] = fake_session
        return {"status": "ok", "internal_id": fake_internal_id}

    async def fake_wait_for_session_id(internal_id, **_kwargs):
        return f"claude_{internal_id}"

    with patch.multiple(
        svc,
        _wait_for_session_id=fake_wait_for_session_id,
    ), patch(
        "frago.server.services.agent_service.AgentService.start_task_attached",
        side_effect=fake_start_task_attached,
    ), patch(
        "frago.server.services.primary_agent_service.get_board",
        return_value=board,
    ):
        import asyncio
        sess_a = asyncio.run(svc._session_for(tid_a))
        sess_b = asyncio.run(svc._session_for(tid_b))

    assert sess_a is not sess_b
    assert svc._session_ids[tid_a] != svc._session_ids[tid_b]
    assert svc._session_ids[tid_a] == "claude_int_1"
    assert svc._session_ids[tid_b] == "claude_int_2"


def test_session_for_fallback_creates_fallback(tmp_path):
    """thread_id=None → fallback session created."""
    board = _make_board(tmp_path)
    svc = _fresh_pa()

    async def fake_start_task_attached(**_kwargs):
        from frago.server.services.agent_service import AgentService
        fake_session = MagicMock()
        fake_session.is_running = True
        AgentService._attached_sessions["int_fallback"] = fake_session
        return {"status": "ok", "internal_id": "int_fallback"}

    async def fake_wait_for_session_id(*_args, **_kwargs):
        return "claude_fallback"

    with patch.multiple(
        svc,
        _wait_for_session_id=fake_wait_for_session_id,
    ), patch(
        "frago.server.services.agent_service.AgentService.start_task_attached",
        side_effect=fake_start_task_attached,
    ), patch(
        "frago.server.services.primary_agent_service.get_board",
        return_value=board,
    ):
        import asyncio
        sess = asyncio.run(svc._session_for(None))

    assert sess is svc._fallback_session
    assert svc._fallback_session_id == "claude_fallback"


# ── bootstrap filtering (spec test point 1: only own thread) ────────────────


def test_bootstrap_only_contains_own_thread(tmp_path):
    """build_bootstrap with thread_id → board view only contains that thread."""
    board = _make_board(tmp_path)
    tid_a = _add_thread(board, chat_id="oc_A")
    _add_thread(board, chat_id="oc_B")  # other thread should be excluded

    from frago.server.services.pa_context_builder import _build_board_section

    with patch("frago.server.services.taskboard.get_board", return_value=board):
        view = _build_board_section(thread_id=tid_a)
    assert view is not None
    # The rendered output should mention tid_a
    assert tid_a in view
    # But NOT the other thread's data
    assert "oc_B" not in view


# ── _set_msg_thread_id backfill ─────────────────────────────────────────────


def test_set_msg_thread_id_backfills():
    svc = _fresh_pa()
    msg = {"type": "agent_completed", "task_id": "t1"}
    svc._set_msg_thread_id(msg, "tid_backfill")
    assert msg["thread_id"] == "tid_backfill"


def test_set_msg_thread_id_skips_none():
    svc = _fresh_pa()
    msg = {"type": "agent_completed", "task_id": "t1"}
    svc._set_msg_thread_id(msg, None)
    assert "thread_id" not in msg


# ── view_for_pa backward compat (spec test point 6) ────────────────────────


def test_view_for_pa_none_returns_all(tmp_path):
    """view_for_pa() without thread_id returns all threads (backward compat)."""
    board = _make_board(tmp_path)
    _add_thread(board)
    _add_thread(board)

    view_all = board.view_for_pa()
    assert len(view_all["threads"]) == 2

    view_default = board.view_for_pa()  # no arg
    assert len(view_default["threads"]) == 2


def test_view_for_pa_filtered(tmp_path):
    """view_for_pa(thread_id=...) returns only that thread."""
    board = _make_board(tmp_path)
    tid_a = _add_thread(board)
    _add_thread(board)

    view = board.view_for_pa(thread_id=tid_a)
    assert len(view["threads"]) == 1
    assert view["threads"][0]["id"] == tid_a


# ── pa_session_id exposed in views (regression guard) ───────────────────────


def test_view_for_pa_exposes_pa_session_id(tmp_path):
    board = _make_board(tmp_path)
    tid = _add_thread(board)
    board.bind_pa_session(tid, "sess_abc", by="test")

    view = board.view_for_pa(thread_id=tid)
    assert view["threads"][0]["pa_session_id"] == "sess_abc"

    view_all = board.view_for_pa()
    match = [t for t in view_all["threads"] if t["id"] == tid]
    assert match[0]["pa_session_id"] == "sess_abc"


# ── rotation counters per-thread ────────────────────────────────────────────


def test_should_rotate_per_thread():
    svc = _fresh_pa()
    svc._total_turns["thread_A"] = 31  # exceeds ROTATION_TURN_THRESHOLD
    svc._total_turns["thread_B"] = 5

    assert svc._should_rotate("thread_A")
    assert not svc._should_rotate("thread_B")
    assert not svc._should_rotate(None)  # fallback untouched


def test_should_rotate_fallback():
    svc = _fresh_pa()
    svc._fallback_total_turns = 31

    assert svc._should_rotate(None)
    assert not svc._should_rotate("thread_X")  # per-thread untouched
