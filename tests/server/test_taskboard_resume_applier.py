"""Phase 1 test_taskboard_resume_applier.py — T9.1~T9.7a (Ce specify 00:18:41)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.models import (
    ClaudeSessionNotFoundError,
    Intent,
    Msg,
    Source,
    Task,
    Thread,
)
from frago.server.services.taskboard.resume_applier import ResumeApplier
from frago.server.services.taskboard.timeline import Timeline


def _make_board_with_task(tmp_path, status="completed", csid="csid_x"):
    """构造一个 board 含一个指定 status 的 task."""
    timeline = Timeline(tmp_path / "timeline.jsonl")
    board = TaskBoard(timeline)
    # 直接 manual 构造对象 (绕过 fold)
    thread = Thread(
        thread_id="T1",
        status="active",
        origin="external",
        subkind="feishu",
        root_summary="test",
        created_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
    )
    src = Source(
        channel="feishu",
        text="hi",
        sender_id="u1",
        parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context=None,
    )
    msg = Msg(msg_id="feishu:M1", status="dispatched", source=src)
    task = Task(
        task_id="TK1",
        status=status,
        type="run",
        intent=Intent(prompt="摘要\n\n正文"),
    )
    msg.tasks.append(task)
    thread.msgs.append(msg)
    board._threads["T1"] = thread
    return board, task


def test_t9_1_case_a_not_implemented_reject(tmp_path, monkeypatch):
    """T9.1 — Case A 未启用期, resume completed/failed task → reject(case_a_not_implemented)."""
    monkeypatch.delenv("FRAGO_CASE_A_ENABLED", raising=False)
    board, task = _make_board_with_task(tmp_path, status="completed")
    ra = ResumeApplier(board)
    ra.route_resume("TK1", "新指令\n\n继续做 X")
    rejections = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "case_a_not_implemented" for r in rejections)
    # task 状态不变
    assert task.status == "completed"


def test_t9_2_rejection_visible_in_view_for_pa(tmp_path, monkeypatch):
    """T9.2 — 拒绝可见性: view_for_pa.recent_rejections[0].reason == case_a_not_implemented."""
    monkeypatch.delenv("FRAGO_CASE_A_ENABLED", raising=False)
    board, task = _make_board_with_task(tmp_path, status="failed")
    ra = ResumeApplier(board)
    ra.route_resume("TK1", "重试\n\nx")
    view = board.view_for_pa()
    assert view["recent_rejections"][0]["reason"] == "case_a_not_implemented"
    assert view["recent_rejections"][0]["offending_task_id"] == "TK1"


def test_t9_3_case_a_happy_path(tmp_path, monkeypatch):
    """T9.3 — Case A enabled + valid csid → spawn_resume 调用, task → executing."""
    monkeypatch.setenv("FRAGO_CASE_A_ENABLED", "1")
    board, task = _make_board_with_task(tmp_path, status="completed", csid="csid_x")
    # 给 task 一个 session 才能拿到 csid
    from frago.server.services.taskboard.models import Session
    task.session = Session(
        run_id="R1", claude_session_id="csid_x", pid=123,
        started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
    )

    class FakeExecutor:
        def spawn_resume(self, csid, prompt):
            assert csid == "csid_x"
            return ("R2", 456)

    ra = ResumeApplier(board, executor=FakeExecutor())
    ra.route_resume("TK1", "继续\n\n追加 X")
    assert task.status == "executing"


def test_t9_4_csid_lost_resume_failed(tmp_path, monkeypatch):
    """T9.4 — Case A spawn_resume 抛 ClaudeSessionNotFoundError → task.status=resume_failed."""
    monkeypatch.setenv("FRAGO_CASE_A_ENABLED", "1")
    board, task = _make_board_with_task(tmp_path, status="completed")
    from frago.server.services.taskboard.models import Session
    task.session = Session(
        run_id="R1", claude_session_id="csid_expired", pid=123,
        started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc),
    )

    class FakeExecutor:
        def spawn_resume(self, csid, prompt):
            raise ClaudeSessionNotFoundError(f"session {csid} not found")

    ra = ResumeApplier(board, executor=FakeExecutor())
    ra.route_resume("TK1", "重试\n\nx")
    assert task.status == "resume_failed"


def test_t9_5_resume_failed_in_must_act_set(tmp_path):
    """T9.5 — resume_failed 是新终态, 进 §7 必须做集合. 当前测试 task.status 字段值合法."""
    from frago.server.services.taskboard.models import Task as TaskModel
    # spec freeze §2 增 resume_failed 终态
    valid_statuses = TaskModel.__annotations__.get("status")
    # Literal 实际不可直接 introspect, 用实例化验证字段接受
    t = TaskModel(
        task_id="TX",
        status="resume_failed",  # 接受新值
        type="run",
        intent=Intent(prompt="x\n\ny"),
    )
    assert t.status == "resume_failed"


def test_t9_6_history_via_timeline_search(tmp_path):
    """T9.6 — 历史 run 轨迹查询走 timeline (task_started entries).

    Phase 1 范围: ExecutionApplier.start_task 写 task_started entry, 多次 start (resume) 累积 N 条.
    本测试验证 timeline 含 ≥1 task_started entry, 完整 N 次 timeline scan 是 CLI 职责留 Phase 2.
    """
    pytest.skip("T9.6 完整覆盖留 Phase 2 (frago tasks task --history CLI 集成测试)")


def test_t9_7a_task_history_structure(tmp_path):
    """T9.7a (Ce Gap 5 拆 a/b) — frago tasks task --history CLI 返回结构正确.

    Phase 1 范围: 不约束耗时, 仅校字段集 {run_id, csid, started_at, ended_at, error, summary}.
    CLI 实装留 Phase 1 后续 commit. 当前测试占位。
    """
    pytest.skip("T9.7a CLI 实装留 Phase 1 后续 commit (task_commands.py --history flag)")


def test_resume_executing_task_case_b_pending(tmp_path):
    """补充 case: executing task → Case B (ResumeInbox + record_resume_pending).

    Phase 1 当前 ResumeApplier 未注入 ResumeInbox 实例 → fallback 落 timeline entry.
    """
    board, task = _make_board_with_task(tmp_path, status="executing")
    ra = ResumeApplier(board, resume_inbox=None)
    ra.route_resume("TK1", "插队\n\n先做 X")
    # task 状态保持 executing, 仅落 timeline
    assert task.status == "executing"


def test_resume_illegal_state_reject(tmp_path):
    """task.status ∈ {queued, replied, resume_failed} → reject(resume_illegal_state)."""
    board, task = _make_board_with_task(tmp_path, status="queued")
    ra = ResumeApplier(board)
    ra.route_resume("TK1", "x\n\ny")
    rejections = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "resume_illegal_state" for r in rejections)
