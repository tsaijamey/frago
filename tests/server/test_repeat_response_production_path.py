"""Phase 1 part B-2a 验收线 (Yi #82 项 9): 真生产路径回归测试.

走完整 IngestionScheduler.poll_recipe → ingest_message → Ingestor.ingest_external
→ board.append_msg → timeline.jsonl 路径, 断言:

1. 同一 msg_id 触发 10 次 ingest_message → board 仅产 1 个 Msg + 0 个 Task
   (无 PA 决策, dispatch 不会发生 — 仅断言 dedup 生效)
2. timeline.jsonl 含 9 条 duplicate_msg_ingest entry
3. ingestion/scheduler 文件内不再有 message_cache.json 持久化 helper
   (验证 B-2a "摘 message_cache 全部 helper" 约束生效)

Spec 20260512 v1.2 freeze: TaskStore 物理删除, board.timeline.jsonl 是唯一源.
本测试不再注入 store.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from frago.server.services.ingestion.scheduler import (
    ChannelConfig,
    IngestionScheduler,
)
from frago.server.services.taskboard import _reset_for_tests, set_board
from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.timeline import Timeline


def _make_isolated_board(tmp_path: Path) -> TaskBoard:
    """Boot a clean TaskBoard rooted at tmp_path."""
    timeline = Timeline(tmp_path / "timeline.jsonl")
    return TaskBoard(timeline)


@pytest.fixture(autouse=True)
def _reset_board_singleton():
    """每个测试用独立 board, 避免单例污染."""
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_production_path_repeat_ingest_10x_one_msg(tmp_path: Path):
    """根因消除回归 (生产路径):
    poll_recipe 返回同 msg_id 10 次 → IngestionScheduler.ingest_message
    → Ingestor.ingest_external → board 仅 1 msg, timeline 9 dup."""
    board = _make_isolated_board(tmp_path)
    set_board(board)

    ch_cfg = ChannelConfig(
        name="feishu",
        poll_recipe="dummy_poll",
        notify_recipe="dummy_notify",
        poll_interval_seconds=120,
    )

    scheduler = IngestionScheduler(channels=[ch_cfg])

    # Stub thread_classifier to avoid hitting real classifier (taskboard/thread_classifier
    # accesses real board; we want isolation).
    from frago.server.services.taskboard.thread_classifier import ClassifyResult

    fake_classify = ClassifyResult(
        thread_id="T_PROD_001",
        parent_ref=None,
        layer="new",
        is_new=True,
    )

    with patch(
        "frago.server.services.taskboard.thread_classifier.classify",
        return_value=fake_classify,
    ), patch(
        "frago.server.services.taskboard.thread_classifier.ensure_thread",
    ), patch(
        "frago.server.services.trace.trace_entry",
    ):
        msg_payload = {
            "id": "om_prod_001",
            "prompt": "测试生产路径",
            "reply_context": {"sender_id": "u_prod"},
        }

        async def run_10x():
            results = []
            for _ in range(10):
                ok = await scheduler.ingest_message(ch_cfg, msg_payload)
                results.append(ok)
            return results

        results = asyncio.run(run_10x())

    # ── 断言 1: board 仅 1 个 msg ───────────────────────────────────────
    thread = board._threads.get("T_PROD_001")
    assert thread is not None, "thread T_PROD_001 should exist on board"
    assert len(thread.msgs) == 1, (
        f"重复 ingest 10 次后 board 应仅 1 msg (dedup), got {len(thread.msgs)}"
    )
    msg = thread.msgs[0]
    assert msg.msg_id == "feishu:om_prod_001"

    # ── 断言 2: timeline 含 9 条 duplicate_msg_ingest entry ───────────
    timeline_path = tmp_path / "timeline.jsonl"
    lines = [
        json.loads(line) for line in timeline_path.read_text().splitlines() if line.strip()
    ]
    dup_entries = [e for e in lines if e.get("data_type") == "duplicate_msg_ingest"]
    assert len(dup_entries) == 9, (
        f"应有 9 条 duplicate_msg_ingest entry, got {len(dup_entries)}\n"
        f"all entries: {[e.get('data_type') for e in lines]}"
    )

    # ── 断言 3: 至少 1 条 msg_received entry (首次 ingest) ─────────────
    msg_received_entries = [e for e in lines if e.get("data_type") == "msg_received"]
    assert len(msg_received_entries) == 1, (
        f"应有 1 条 msg_received entry, got {len(msg_received_entries)}"
    )

    # ── 断言 4: 全部 ingest 都返回 True (board.append_msg dedup 内部 swallow) ─
    # ingest_message 返回 True 仅代表 "payload 合法 + 不被前置过滤跳过";
    # 实际 dedup 由 board.append_msg 内的 duplicate_msg_ingest 处理.
    assert results[0] is True, "first ingest should return True"


def test_scheduler_module_has_no_message_cache_persistence():
    """B-2a 硬约束验证 (Yi #82 项 9 子条款):
    ingestion/scheduler.py 内不应再有 message_cache.json 持久化 helper.

    具体检查:
    - 不再 import CACHE_FILE 常量
    - 不再有 _load_cache / _save_cache 函数
    - 不再 read/write message_cache.json
    """
    import frago.server.services.ingestion.scheduler as scheduler_mod

    src = Path(scheduler_mod.__file__).read_text(encoding="utf-8")

    forbidden = [
        "CACHE_FILE",                # legacy module constant
        "_load_cache",               # legacy helper
        "_save_cache",               # legacy helper
        "message_cache.json",        # legacy persistence target
    ]
    found = [pat for pat in forbidden if re.search(re.escape(pat), src)]
    assert not found, (
        f"ingestion/scheduler.py 仍含 message_cache 持久化痕迹: {found}\n"
        f"B-2a 硬约束: 必须摘除全部持久化 helper, 内存 shim 不算违规"
    )


def test_scheduler_module_has_no_taskstore_or_ingested_tasks_json():
    """Phase D 硬约束 (spec 20260512 v1.2): scheduler 不应再有 TaskStore /
    ingested_tasks.json 持久化痕迹 (excluding docstring mentions).
    """
    import ast as _ast
    import frago.server.services.ingestion.scheduler as scheduler_mod

    src = Path(scheduler_mod.__file__).read_text(encoding="utf-8")
    tree = _ast.parse(src)
    # Strip module-level docstring so it doesn't count as a code-level reference.
    if (
        tree.body and isinstance(tree.body[0], _ast.Expr)
        and isinstance(tree.body[0].value, _ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    code_src = _ast.unparse(tree)

    forbidden = [
        "TaskStore",
        "ingested_tasks.json",
        "legacy_store",
    ]
    found = [pat for pat in forbidden if re.search(re.escape(pat), code_src)]
    assert not found, (
        f"ingestion/scheduler.py 仍含 TaskStore 痕迹: {found}\n"
        f"Phase D 硬约束: TaskStore 物理删除, scheduler 只走 board"
    )


def test_scheduler_ingest_message_routes_to_board(tmp_path: Path):
    """B-2a wire-up 回归: ingest_message 必须实际调到 board."""
    board = _make_isolated_board(tmp_path)
    set_board(board)

    ch_cfg = ChannelConfig(
        name="feishu",
        poll_recipe="dummy_poll",
        notify_recipe="dummy_notify",
    )

    scheduler = IngestionScheduler(channels=[ch_cfg])

    from frago.server.services.taskboard.thread_classifier import ClassifyResult
    fake_classify = ClassifyResult(
        thread_id="T_WIRE_001", parent_ref=None, layer="new", is_new=True,
    )

    with patch(
        "frago.server.services.taskboard.thread_classifier.classify",
        return_value=fake_classify,
    ), patch(
        "frago.server.services.taskboard.thread_classifier.ensure_thread",
    ), patch(
        "frago.server.services.trace.trace_entry",
    ):
        asyncio.run(scheduler.ingest_message(ch_cfg, {
            "id": "om_wire_001",
            "prompt": "wire-up check",
            "reply_context": {},
        }))

    # board 上应已有 thread + msg
    assert "T_WIRE_001" in board._threads
    assert any(
        m.msg_id == "feishu:om_wire_001"
        for m in board._threads["T_WIRE_001"].msgs
    )
