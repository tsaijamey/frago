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

    B-2a: ExecutionApplier.start_task 写 task_started entry, 多次 start (resume Case A)
    累积 N 条; 本测试构造 2 次 start (模拟 resume Case A) 验证 timeline 有 2 条
    task_started entry, 且可按 task_id 过滤.
    """
    from frago.server.services.taskboard.execution_applier import ExecutionApplier
    from frago.server.services.taskboard.models import Intent
    from frago.server.services.taskboard.timeline import Timeline

    timeline = Timeline(tmp_path / "timeline.jsonl")
    board = TaskBoard(timeline)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="x", by="test",
    )
    # 制造一个 msg + task (走 Ingestor → DecisionApplier 路径的简化版)
    from frago.server.services.taskboard.models import Msg, Source
    msg = Msg(
        msg_id="feishu:m1",
        status="awaiting_decision",
        source=Source(
            channel="feishu", text="t", sender_id="u",
            parent_ref=None, received_at=datetime.now(),
        ),
    )
    board.append_msg("T1", msg, by="test")
    task = board.append_task("feishu:m1", Intent(prompt="s\n\nb"),
                             task_type="run", by="test")

    ea = ExecutionApplier(board)
    ea.start_task(task.task_id, run_id="run1", pid=1001, csid="csid1")
    # 模拟 finish 后再 resume Case A: 走 finish_task → start_task (新 run_id, 同 task_id)
    ea.finish_task(task.task_id, result_summary="done", status="completed")
    # 模拟新一轮 start (resume Case A 复用 task_id, 新 run_id)
    with board._lock:
        # 直接调 timeline.append_entry 模拟 spawn_resume 后的 ExecutionApplier.start_task
        # (因为 ExecutionApplier.start_task 要求 task.status ∈ {queued, executing},
        # completed 状态实际由 ResumeApplier 在 set status="executing" 后调 ExecutionApplier;
        # 这里直接写 timeline entry 验证 history 结构.)
        board._timeline.append_entry(
            data_type="task_started",
            by="ResumeApplier",
            task_id=task.task_id,
            data={"run_id": "run2", "pid": 1002, "csid": "csid1"},
        )

    entries = list(timeline.iter_entries())
    task_started = [e for e in entries if e.get("data_type") == "task_started"
                    and e.get("task_id") == task.task_id]
    assert len(task_started) == 2, (
        f"应有 2 条 task_started entry (init + resume), got {len(task_started)}"
    )
    run_ids = [e["data"]["run_id"] for e in task_started]
    assert run_ids == ["run1", "run2"], f"run_id sequence 错: {run_ids}"


def test_t9_7a_task_history_structure(tmp_path, monkeypatch):
    """T9.7a — frago task history CLI 返回结构正确.

    走 cli/task_commands.py task_history 函数, 验证 JSON 输出含 task_id /
    count / entries, 每个 entry 含 task_id 字段.
    """
    import json as _json

    from click.testing import CliRunner

    from frago.cli.task_commands import task_history

    # 准备一个 fake timeline.jsonl in tmp_path/.frago/timeline
    home = tmp_path / "home"
    timeline_dir = home / ".frago" / "timeline"
    timeline_dir.mkdir(parents=True)
    tl_path = timeline_dir / "timeline.jsonl"
    entries = [
        {"entry_id": "e1", "ts": "2026-05-12T10:00:00",
         "data_type": "task_started", "task_id": "T_ABC",
         "data": {"run_id": "r1"}, "by": "test"},
        {"entry_id": "e2", "ts": "2026-05-12T10:01:00",
         "data_type": "task_finished", "task_id": "T_ABC",
         "data": {"status": "completed"}, "by": "test"},
        {"entry_id": "e3", "ts": "2026-05-12T10:02:00",
         "data_type": "task_started", "task_id": "T_OTHER",
         "data": {"run_id": "r2"}, "by": "test"},
    ]
    tl_path.write_text(
        "\n".join(_json.dumps(e) for e in entries),
        encoding="utf-8",
    )

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("pathlib.Path.home", lambda: home)

    runner = CliRunner()
    result = runner.invoke(task_history, ["T_ABC"])
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    payload = _json.loads(result.output)
    assert payload["task_id"] == "T_ABC"
    assert payload["count"] == 2, f"应只返回 T_ABC 的 2 条, got {payload}"
    for e in payload["entries"]:
        assert e["task_id"] == "T_ABC"


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
