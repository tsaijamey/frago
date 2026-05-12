"""Phase 1 part B 验收线: 'PA 重复响应' 根因消除回归测试.

场景: 同一条飞书消息触发 10 次 ingest → 仅产生 1 个 task, PA 不重复响应.

根因消除路径:
1. board.append_msg 内部 dedup (同 msg_id 不重复 append, 落 duplicate_msg_ingest timeline)
2. 第 1 次 ingest → msg.status=received → PA 看到 → DecisionApplier 输出 1 个 run task,
   msg.status=dispatched
3. 第 2-10 次 ingest 同 msg_id → board 内部 dedup 直接 return, msg.tasks 长度始终 == 1

替代旧 message_cache 兜底机制 (Phase 1 part C 删除 ingestion/scheduler.message_cache).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.decision_applier import DecisionApplier
from frago.server.services.taskboard.ingestor import Ingestor
from frago.server.services.taskboard.timeline import Timeline


def _make_board(tmp_path: Path) -> TaskBoard:
    timeline = Timeline(tmp_path / "timeline.jsonl")
    return TaskBoard(timeline)


def test_repeat_ingest_10x_produces_one_task(tmp_path: Path):
    """根因回归: 同一 msg_id 重复 ingest 10 次, board 仅产 1 个 msg + 1 个 task."""
    board = _make_board(tmp_path)
    ingestor = Ingestor(board)
    da = DecisionApplier(board)

    # 准备: 先 create_thread (scheduler 实际负责, 测试直接做)
    board.create_thread(
        thread_id="T1",
        origin="external",
        subkind="feishu",
        root_summary="测试",
        by="test",
    )

    msg_id_raw = "om_test_001"
    fixed_time = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)

    # 第 1 次 ingest
    ingestor.ingest_external(
        channel="feishu",
        msg_id=msg_id_raw,
        sender_id="u1",
        text="你好",
        parent_ref=None,
        received_at=fixed_time,
        reply_context=None,
        thread_id="T1",
    )
    # PA 看到 → 输出 1 个 run decision
    pa_decisions = [{"action": "run", "msg_id": f"feishu:{msg_id_raw}", "prompt": "调研\n\n详细"}]
    da.handle_pa_output(pa_decisions)

    # 第 2-10 次 ingest 同 msg_id (模拟 scheduler 误重复推送 / 用户多次触发)
    for _ in range(9):
        ingestor.ingest_external(
            channel="feishu",
            msg_id=msg_id_raw,
            sender_id="u1",
            text="你好",
            parent_ref=None,
            received_at=fixed_time,
            reply_context=None,
            thread_id="T1",
        )

    # 关键断言: board 仅含 1 个 msg + 1 个 task (不是 10 个)
    thread = board._threads["T1"]
    assert len(thread.msgs) == 1, (
        f"重复 ingest 10 次后应仅 1 个 msg (dedup), got {len(thread.msgs)}"
    )
    msg = thread.msgs[0]
    assert msg.msg_id == f"feishu:{msg_id_raw}"
    assert len(msg.tasks) == 1, f"应仅 1 个 task (PA 仅看到 1 次), got {len(msg.tasks)}"
    assert msg.tasks[0].type == "run"
    assert msg.status == "dispatched"

    # 验证 timeline 含 9 条 duplicate_msg_ingest entry
    timeline_path = tmp_path / "timeline.jsonl"
    lines = [l for l in timeline_path.read_text().splitlines() if l.strip()]
    import json
    entries = [json.loads(l) for l in lines]
    dup_entries = [e for e in entries if e.get("data_type") == "duplicate_msg_ingest"]
    assert len(dup_entries) == 9, (
        f"应有 9 条 duplicate_msg_ingest entry, got {len(dup_entries)}"
    )


def test_pa_not_invoked_for_duplicate_msg(tmp_path: Path):
    """PA 视角: view_for_pa() 在第 2-10 次 ingest 后 msg.status 仍是 dispatched, 不会重新进 awaiting_decision."""
    board = _make_board(tmp_path)
    ingestor = Ingestor(board)
    da = DecisionApplier(board)

    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="测试", by="test",
    )
    msg_id_raw = "om_pa_001"
    fixed_time = datetime(2026, 5, 12, 11, 0, 0, tzinfo=timezone.utc)

    ingestor.ingest_external(
        channel="feishu", msg_id=msg_id_raw, sender_id="u1", text="x",
        parent_ref=None, received_at=fixed_time, reply_context=None, thread_id="T1",
    )
    da.handle_pa_output([{"action": "run", "msg_id": f"feishu:{msg_id_raw}", "prompt": "s\n\nb"}])

    # 第 2 次 ingest
    ingestor.ingest_external(
        channel="feishu", msg_id=msg_id_raw, sender_id="u1", text="x",
        parent_ref=None, received_at=fixed_time, reply_context=None, thread_id="T1",
    )

    view = board.view_for_pa()
    # PA 看到的 msg.status 应该是 dispatched (不是 awaiting_decision), 不会再触发新 decision
    threads = view["threads"]
    msgs = threads[0]["msgs"]
    assert len(msgs) == 1
    assert msgs[0]["status"] == "dispatched"


def test_mark_task_replied_and_close_msg(tmp_path: Path):
    """Phase 1 part B 新 board 方法: mark_task_replied + close_msg_if_terminal 闭环."""
    board = _make_board(tmp_path)
    ingestor = Ingestor(board)
    da = DecisionApplier(board)

    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="测试", by="test",
    )
    msg_id_raw = "om_close_001"
    fixed_time = datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)

    ingestor.ingest_external(
        channel="feishu", msg_id=msg_id_raw, sender_id="u1", text="x",
        parent_ref=None, received_at=fixed_time, reply_context=None, thread_id="T1",
    )
    full_msg_id = f"feishu:{msg_id_raw}"
    # PA reply (经 DecisionApplier 路径自动调 mark_task_replied + close_msg_if_terminal)
    da.handle_pa_output([{"action": "reply", "msg_id": full_msg_id, "prompt": "回复\n\n详细"}])

    msg = board._find_msg(full_msg_id)
    assert msg is not None
    assert len(msg.tasks) == 1
    assert msg.tasks[0].type == "reply"
    assert msg.tasks[0].status == "replied"
    assert msg.status == "closed"


def test_dismiss_action_marks_msg_dismissed(tmp_path: Path):
    """Phase 1 part B 新方法: mark_msg_dismissed 路径 (PA dismiss action)."""
    board = _make_board(tmp_path)
    ingestor = Ingestor(board)
    da = DecisionApplier(board)

    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="测试", by="test",
    )
    msg_id_raw = "om_dismiss_001"
    fixed_time = datetime(2026, 5, 12, 13, 0, 0, tzinfo=timezone.utc)

    ingestor.ingest_external(
        channel="feishu", msg_id=msg_id_raw, sender_id="u1", text="x",
        parent_ref=None, received_at=fixed_time, reply_context=None, thread_id="T1",
    )
    full_msg_id = f"feishu:{msg_id_raw}"
    da.handle_pa_output([{"action": "dismiss", "msg_id": full_msg_id, "prompt": "spam\n\n忽略"}])

    msg = board._find_msg(full_msg_id)
    assert msg is not None
    assert msg.status == "dismissed"
