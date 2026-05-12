"""Phase 1 test_taskboard_applier_invariants.py — Ce Gap 2 新增 (T5.2 + T_B1.1/T_B1.2).

T5.2 (post_archive_reject) — applier 公共不变量
T_B1.1 (scheduled fast-path Msg 状态) — Ingestor.ingest_scheduled 行为
T_B1.2 (Source default 完整性) — scheduled channel 字段约定
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.ingestor import Ingestor
from frago.server.services.taskboard.timeline import Timeline


def _make_board(tmp_path):
    timeline = Timeline(tmp_path / "timeline.jsonl")
    return TaskBoard(timeline)


def test_t_b1_1_scheduled_fast_path_msg_dispatched(tmp_path):
    """T_B1.1 — scheduled trigger 经 ingest_scheduled 后, Msg 应进 dispatched 状态.

    Phase 1 当前实现: append_msg(received) → append_task 后 msg.status → dispatched.
    最终 board 中 msg.status == "dispatched" (不应停留在 awaiting_decision).
    """
    board = _make_board(tmp_path)
    ing = Ingestor(board)
    msg = ing.ingest_scheduled(
        schedule_id="job_123",
        prompt="定时任务摘要\n\n正文",
        trigger_at=datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC),
        job_name="daily_report",
    )
    # msg 进 board 后, status 应为 dispatched (append_task 改的)
    assert msg.status == "dispatched"
    # board 内 thread 存在
    threads = list(board._threads.values())
    scheduled_threads = [t for t in threads if t.origin == "scheduled"]
    assert len(scheduled_threads) == 1
    assert scheduled_threads[0].subkind == "daily_report"


def test_t_b1_2_source_default_completeness(tmp_path):
    """T_B1.2 — scheduled msg.source 字段完整性 (Yi B1 决议 default 值)."""
    board = _make_board(tmp_path)
    ing = Ingestor(board)
    trigger_at = datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC)
    msg = ing.ingest_scheduled(
        schedule_id="job_xyz",
        prompt="测试\n\n正文",
        trigger_at=trigger_at,
        job_name="test_job",
    )
    src = msg.source
    assert src.channel == "scheduled"
    assert src.sender_id == "__scheduler__"
    assert src.parent_ref == "job_xyz"
    assert src.received_at == trigger_at
    assert src.text == "测试\n\n正文"
    assert src.reply_context is None


def test_t_b1_2_source_frozen_immutable(tmp_path):
    """Phase 0 Source frozen=True 在 scheduled 路径也成立."""
    from dataclasses import FrozenInstanceError

    board = _make_board(tmp_path)
    ing = Ingestor(board)
    msg = ing.ingest_scheduled(
        schedule_id="j", prompt="x\n\ny",
        trigger_at=datetime.now(UTC), job_name="j",
    )
    with pytest.raises(FrozenInstanceError):
        msg.source.channel = "external"  # type: ignore[misc]


def test_t5_2_post_archive_reject(tmp_path):
    """T5.2 — thread 已 archived 后 append entry → applier reject (Phase 2 vacuum).

    步骤:
    1. 建 thread + 首个 msg + 首个 task (active 状态)
    2. board.record_thread_archived(tid) → thread.status='archived' + marker entry
    3. 同 thread_id 第二次 append_msg → reject post_archive_append
       (Msg 不进 thread.msgs, recent_rejections 增 1 条)
    4. 二次 record_thread_archived 同 tid → reject duplicate_marker
    """
    from datetime import datetime

    from frago.server.services.taskboard.models import Msg, Source

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T_ARCH", origin="external", subkind="feishu",
        root_summary="x", by="test",
    )
    # 装个初始 msg 让 thread 有内容
    init_msg = Msg(
        msg_id="feishu:init",
        status="awaiting_decision",
        source=Source(
            channel="feishu", text="hi", sender_id="u1",
            parent_ref=None, received_at=datetime.now(UTC),
        ),
    )
    board.append_msg("T_ARCH", init_msg, by="test")
    assert len(board._threads["T_ARCH"].msgs) == 1

    # 标 thread archived
    board.record_thread_archived("T_ARCH", by="vacuum")
    assert board._threads["T_ARCH"].status == "archived"

    # post-archive append_msg: 应进 reject 通道, msgs 不增加
    late_msg = Msg(
        msg_id="feishu:late",
        status="awaiting_decision",
        source=Source(
            channel="feishu", text="too late", sender_id="u2",
            parent_ref=None, received_at=datetime.now(UTC),
        ),
    )
    board.append_msg("T_ARCH", late_msg, by="test")
    assert len(board._threads["T_ARCH"].msgs) == 1, (
        f"post-archive msg 不应进 thread, got {len(board._threads['T_ARCH'].msgs)}"
    )

    rejections = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "post_archive_append" for r in rejections), (
        f"应有 post_archive_append rejection, got reasons="
        f"{[r['reason'] for r in rejections]}"
    )

    # duplicate marker reject
    board.record_thread_archived("T_ARCH", by="vacuum")
    rejections2 = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "duplicate_marker" for r in rejections2), (
        f"二次 archive 同 thread 应 reject duplicate_marker, got reasons="
        f"{[r['reason'] for r in rejections2]}"
    )


def test_scheduled_thread_not_merged(tmp_path):
    """B1 决议: scheduled channel 不归并, 每次触发独立 thread."""
    board = _make_board(tmp_path)
    ing = Ingestor(board)
    msg1 = ing.ingest_scheduled(
        schedule_id="job_A", prompt="x\n\ny",
        trigger_at=datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC),
        job_name="A",
    )
    msg2 = ing.ingest_scheduled(
        schedule_id="job_A", prompt="x\n\ny",
        trigger_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=UTC),
        job_name="A",
    )
    # 同 schedule_id 但不同 trigger_at 应产生不同 thread (不归并)
    threads = [t for t in board._threads.values() if t.origin == "scheduled"]
    assert len(threads) == 2
    assert msg1.msg_id != msg2.msg_id
