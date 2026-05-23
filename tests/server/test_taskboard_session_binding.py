"""Phase 2 tests: thread↔session binding via board.bind_pa_session.

Spec: 20260522-pa-per-conversation-session Phase 2.

Acceptance criteria:
  1. bind_pa_session sets thread.pa_session_id and writes timeline entry
  2. Idempotent: same session_id → no second timeline entry
  3. Fold: server restart (re-fold) preserves the binding
  4. Unbound thread exposes pa_session_id=None
"""

from __future__ import annotations

import pytest

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import IllegalTransitionError
from frago.server.services.taskboard.timeline import Timeline, ulid_new


def _make_timeline(tmp_path):
    path = tmp_path / "timeline.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return Timeline(path)


def _fresh_board(timeline):
    return TaskBoard(timeline)


def _create_thread(board, tid=None):
    thread_id = tid or ulid_new()
    board.create_thread(
        thread_id=thread_id,
        origin="external",
        subkind="feishu",
        root_summary="test thread",
        by="test",
    )
    return thread_id


# ── bind_pa_session ──────────────────────────────────────────────────────────


def test_bind_pa_session_sets_field(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)

    board.bind_pa_session(tid, "sess_001", by="test")

    t = board.get_thread(tid)
    assert t["pa_session_id"] == "sess_001"


def test_bind_pa_session_writes_timeline_entry(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)

    board.bind_pa_session(tid, "sess_002", by="test")

    entries = list(board._timeline.iter_entries())
    bind_entries = [e for e in entries if e.get("data_type") == "thread_bound_to_session"]
    assert len(bind_entries) == 1
    assert bind_entries[0]["data"]["session_id"] == "sess_002"
    assert bind_entries[0]["thread_id"] == tid
    assert bind_entries[0]["by"] == "test"


def test_bind_pa_session_idempotent(tmp_path):
    """Same session_id bound twice → only one timeline entry (no dupe)."""
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)

    board.bind_pa_session(tid, "sess_003", by="test")
    board.bind_pa_session(tid, "sess_003", by="test")

    entries = list(board._timeline.iter_entries())
    bind_entries = [e for e in entries if e.get("data_type") == "thread_bound_to_session"]
    assert len(bind_entries) == 1


def test_bind_pa_session_overwrite(tmp_path):
    """Bind new session_id → second entry written, field updated."""
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)

    board.bind_pa_session(tid, "sess_A", by="test")
    board.bind_pa_session(tid, "sess_B", by="test")

    t = board.get_thread(tid)
    assert t["pa_session_id"] == "sess_B"

    entries = list(board._timeline.iter_entries())
    bind_entries = [e for e in entries if e.get("data_type") == "thread_bound_to_session"]
    assert len(bind_entries) == 2


def test_bind_pa_session_missing_thread(tmp_path):
    """Binding a non-existent thread → IllegalTransitionError."""
    board = _fresh_board(_make_timeline(tmp_path))

    with pytest.raises(IllegalTransitionError) as exc_info:
        board.bind_pa_session("nonexistent", "sess_004", by="test")
    assert exc_info.value.reason == "thread_missing"


# ── view_for_pa exposes pa_session_id ────────────────────────────────────────


def test_view_for_pa_exposes_pa_session_id(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)
    board.bind_pa_session(tid, "sess_005", by="test")

    view = board.view_for_pa()
    threads = view.get("threads", [])
    bound = [t for t in threads if t["id"] == tid]
    assert len(bound) == 1
    assert bound[0]["pa_session_id"] == "sess_005"


def test_view_for_pa_unbound_is_none(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)

    view = board.view_for_pa()
    threads = view.get("threads", [])
    unbound = [t for t in threads if t["id"] == tid]
    assert len(unbound) == 1
    assert unbound[0]["pa_session_id"] is None


# ── list_threads / get_thread expose pa_session_id ──────────────────────────


def test_list_threads_exposes_pa_session_id(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)
    board.bind_pa_session(tid, "sess_006", by="test")

    threads = board.list_threads()
    bound = [t for t in threads if t["thread_id"] == tid]
    assert len(bound) == 1
    assert bound[0]["pa_session_id"] == "sess_006"


def test_get_thread_exposes_pa_session_id(tmp_path):
    board = _fresh_board(_make_timeline(tmp_path))
    tid = _create_thread(board)
    board.bind_pa_session(tid, "sess_007", by="test")

    t = board.get_thread(tid)
    assert t["pa_session_id"] == "sess_007"


# ── fold reconstruction ──────────────────────────────────────────────────────


def test_fold_preserves_binding(tmp_path):
    """Server restart (re-fold) preserves pa_session_id mapping."""
    timeline = _make_timeline(tmp_path)
    board = _fresh_board(timeline)
    tid = _create_thread(board)
    board.bind_pa_session(tid, "sess_fold_001", by="test")

    board2 = TaskBoard.fold(timeline._path)

    t = board2.get_thread(tid)
    assert t is not None
    assert t["pa_session_id"] == "sess_fold_001"


def test_fold_reconstructs_multiple_bindings(tmp_path):
    """Multiple threads with different pa_session_ids survive fold."""
    timeline = _make_timeline(tmp_path)
    board = _fresh_board(timeline)
    tid_a = _create_thread(board, ulid_new())
    tid_b = _create_thread(board, ulid_new())
    board.bind_pa_session(tid_a, "sess_fold_A", by="test")
    board.bind_pa_session(tid_b, "sess_fold_B", by="test")

    board2 = TaskBoard.fold(timeline._path)

    assert board2.get_thread(tid_a)["pa_session_id"] == "sess_fold_A"
    assert board2.get_thread(tid_b)["pa_session_id"] == "sess_fold_B"


def test_fold_unbound_remains_none(tmp_path):
    """Thread never bound → pa_session_id stays None after fold."""
    timeline = _make_timeline(tmp_path)
    board = _fresh_board(timeline)
    tid = _create_thread(board)

    board2 = TaskBoard.fold(timeline._path)

    t = board2.get_thread(tid)
    assert t["pa_session_id"] is None
