"""Phase 1 test_taskboard_decision_applier.py — T3.1~T3.4 (Ce specify 00:18:41)."""

from __future__ import annotations

import pytest

from frago.server.services.taskboard.board import TaskBoard
from frago.server.services.taskboard.decision_applier import (
    DecisionApplier,
    validate_prompt_format,
)
from frago.server.services.taskboard.timeline import Timeline


def _make_board(tmp_path):
    timeline = Timeline(tmp_path / "timeline.jsonl")
    return TaskBoard(timeline)


def test_t3_1_action_invalid_reject(tmp_path):
    """T3.1 — action ∉ {run, reply, resume, dismiss} → reject(action_invalid)."""
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    da.handle_pa_output([{"action": "delete", "msg_id": "m1", "prompt": "x\n\ny"}])
    view = board.view_for_pa()
    rejections = view["recent_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "action_invalid"
    assert rejections[0]["original_action"] == "delete"


def test_t3_2_prompt_format_invalid_first_line_too_long(tmp_path):
    """T3.2 子 case 1: 首行 >80 字 → reject."""
    long_first = "x" * 100
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    da.handle_pa_output([{"action": "run", "msg_id": "m1", "prompt": f"{long_first}\n\ny"}])
    rejections = board.view_for_pa()["recent_rejections"]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "prompt_format_invalid"


def test_t3_2_prompt_format_invalid_no_blank_line(tmp_path):
    """T3.2 子 case 2: 缺空行分隔 → reject."""
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    da.handle_pa_output([{"action": "run", "msg_id": "m1", "prompt": "summary\nbody-without-blank"}])
    rejections = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "prompt_format_invalid" for r in rejections)


def test_t3_2_prompt_format_invalid_code_fence_in_first_line(tmp_path):
    """T3.2 子 case 3: 首行含 ``` 围栏 → reject."""
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    da.handle_pa_output([{"action": "run", "msg_id": "m1", "prompt": "summary ```\n\nbody"}])
    rejections = board.view_for_pa()["recent_rejections"]
    assert any(r["reason"] == "prompt_format_invalid" for r in rejections)


def test_validate_prompt_format_valid(tmp_path):
    """T3.2 valid case: 首行 ≤80 + 空行 + 正文 → None (合法)."""
    assert validate_prompt_format("摘要\n\n正文") is None
    assert validate_prompt_format("摘要 80 字以内\n\n正文 multi-line\nactually 多行") is None


def test_t3_3_summary_first_line_not_truncate(tmp_path):
    """T3.3 — original_prompt_head 取首行 (而非 prompt[:80] 硬截断)."""
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    # 这条 prompt 首行 92 字 (>80), 会触发 prompt_format_invalid
    prompt = "短摘要" + "x" * 100 + "\n\nbody"
    da.handle_pa_output([{"action": "run", "msg_id": "m1", "prompt": prompt}])
    rejections = board.view_for_pa()["recent_rejections"]
    # original_prompt_head 是首行截断前 80 字, 不混入正文
    assert "\n" not in rejections[0]["original_prompt_head"]


def test_run_decision_with_raw_msg_id_prefixes_with_channel(tmp_path):
    """Regression (2026-05-19 sub-agent never launches):

    PA sees msg_id via PA_MESSAGE_TEMPLATE which renders the unprefixed
    channel_message_id (e.g. `om_x100b...`). Board stores `feishu:om_x100b...`.
    Without channel-prefix normalization, board.append_task → _find_msg miss →
    IllegalTransitionError → swallowed by DecisionApplier → no task created →
    executor's poll loop never sees a queued task → user's run goes nowhere.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="japan stock", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_x100b_run_test",
        sender_id="u1", text="日本股市", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )

    # PA-shaped decision: raw msg_id + separate channel field (mirror production)
    DecisionApplier(board).handle_pa_output([{
        "action": "run",
        "msg_id": "om_x100b_run_test",
        "channel": "feishu",
        "description": "japan stock",
        "prompt": "调查日本股市\n\n2026-05-20 开盘情况",
    }])

    queued = board.get_queued_tasks()
    assert len(queued) == 1, (
        f"run decision should produce a queued task, got {len(queued)}. "
        f"Cause: channel-prefix normalization missing — _find_msg saw "
        f"`om_x100b_run_test` while board has `feishu:om_x100b_run_test`."
    )
    assert queued[0].type == "run"
    assert queued[0].status == "queued"


def test_run_decision_with_already_prefixed_msg_id_not_double_prefixed(tmp_path):
    """Scheduled msgs arrive with msg_id already in `scheduled:<id>:<iso>` form
    and channel=scheduled. Normalizer must not double-prefix to
    `scheduled:scheduled:...`.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="scheduled",
        root_summary="cron", by="test",
    )
    # Ingest with a msg_id that already includes a colon in the raw portion
    Ingestor(board).ingest_external(
        channel="scheduled", msg_id="job_42:2026-05-20T08:00:00",
        sender_id="__scheduler__", text="cron fired", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )

    # PA echoes back the full prefixed msg_id (because scheduled tasks
    # are exposed to PA via PA_SCHEDULED_TASK_TEMPLATE with the prefixed form)
    DecisionApplier(board).handle_pa_output([{
        "action": "run",
        "msg_id": "scheduled:job_42:2026-05-20T08:00:00",
        "channel": "scheduled",
        "description": "cron",
        "prompt": "执行 cron\n\nbody",
    }])

    queued = board.get_queued_tasks()
    assert len(queued) == 1, "scheduled msg_id should not be double-prefixed"


def test_duplicate_run_inflight_rejected(tmp_path):
    """Bug H (2026-05-20 dup-artefact): a PA session rotation drops the
    in-memory 'I already dispatched a run for this msg' record, so PA
    re-scans the board and dispatches a SECOND run for the same message —
    two sub-agents do identical work, user gets duplicate artefacts.
    board.append_task must reject a fresh run while one is in flight.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="etf", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_dup",
        sender_id="u1", text="分析 ETF", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )

    da = DecisionApplier(board)
    run_decision = {
        "action": "run", "msg_id": "om_dup", "channel": "feishu",
        "description": "etf", "prompt": "分析\n\n详细",
    }
    da.handle_pa_output([run_decision])   # run ① — accepted
    da.handle_pa_output([run_decision])   # run ② — must be rejected

    queued = board.get_queued_tasks()
    assert len(queued) == 1, (
        f"second run for the same in-flight msg must be rejected, "
        f"got {len(queued)} queued tasks"
    )
    reasons = [r["reason"] for r in board.view_for_pa()["recent_rejections"]]
    assert "duplicate_run_inflight" in reasons


def test_second_run_allowed_after_first_completes(tmp_path):
    """The guard is scoped to in-flight (queued/executing) runs only — once
    the first run reaches a terminal state a follow-up run is permitted.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="etf", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_seq",
        sender_id="u1", text="分析", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )
    da = DecisionApplier(board)
    da.handle_pa_output([{
        "action": "run", "msg_id": "om_seq", "channel": "feishu",
        "description": "x", "prompt": "a\n\nb",
    }])
    first = board.get_queued_tasks()[0]
    board.mark_task_executing(first.task_id, by="test")
    board.mark_task_completed(first.task_id, summary="done", by="test")

    # Now a fresh run is allowed (no in-flight run remains)
    da.handle_pa_output([{
        "action": "run", "msg_id": "om_seq", "channel": "feishu",
        "description": "y", "prompt": "c\n\nd",
    }])
    queued = board.get_queued_tasks()
    assert len(queued) == 1, "follow-up run after completion should be accepted"


def test_reply_then_run_batch_does_not_block_run(tmp_path):
    """Regression for the Bug J fix's own regression (2026-05-20 12:22):
    PA commonly emits [reply(ack), run] in ONE decision batch. If the reply
    closes the msg immediately, the subsequent run hits a closed msg and is
    rejected (illegal_transition) — sub-agent never launches. Closing must be
    deferred to end-of-batch so the queued run keeps the msg open.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="topic", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_batch",
        sender_id="u1", text="研究一下", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )

    DecisionApplier(board).handle_pa_output([
        {"action": "reply", "msg_id": "om_batch", "channel": "feishu",
         "text": "收到，正在研究，稍等"},
        {"action": "run", "msg_id": "om_batch", "channel": "feishu",
         "description": "research", "prompt": "研究主题\n\n详细展开"},
    ])

    queued = board.get_queued_tasks()
    assert len(queued) == 1 and queued[0].type == "run", (
        f"run in [reply, run] batch must be dispatched, got {len(queued)} "
        f"queued tasks"
    )
    # msg must stay open (run is in flight), NOT closed by the interim reply
    parent = board.get_msg_for_task(queued[0].task_id)
    assert parent.status == "dispatched", (
        f"msg must stay open while run is queued, got {parent.status}"
    )


def test_reply_by_task_id_closes_parent_msg(tmp_path):
    """Bug J (2026-05-20 dup-artefact, send ③): replying by task_id (no
    msg_id) used to mark the task replied but never closed the parent msg.
    The msg lingered in `dispatched`, a reflection tick later judged it
    unanswered and re-sent the whole analysis + PNG. The task_id reply path
    must resolve and close the parent msg.
    """
    from datetime import datetime, timezone

    from frago.server.services.taskboard.ingestor import Ingestor

    board = _make_board(tmp_path)
    board.create_thread(
        thread_id="T1", origin="external", subkind="feishu",
        root_summary="etf", by="test",
    )
    Ingestor(board).ingest_external(
        channel="feishu", msg_id="om_reply",
        sender_id="u1", text="分析", parent_ref=None,
        received_at=datetime.now(timezone.utc),
        reply_context={}, thread_id="T1",
    )
    da = DecisionApplier(board)
    # PA dispatches a run, sub-agent finishes
    da.handle_pa_output([{
        "action": "run", "msg_id": "om_reply", "channel": "feishu",
        "description": "x", "prompt": "a\n\nb",
    }])
    run_task = board.get_queued_tasks()[0]
    board.mark_task_executing(run_task.task_id, by="test")
    board.mark_task_completed(run_task.task_id, summary="done", by="test")

    # PA replies by task_id ONLY (no msg_id) — the production shape that left
    # the msg open.
    da.handle_pa_output([{
        "action": "reply", "task_id": run_task.task_id,
        "channel": "feishu", "text": "结论 + 图",
    }])

    parent = board.get_msg_for_task(run_task.task_id)
    assert parent.status == "closed", (
        f"parent msg must be closed after task_id reply, got {parent.status} "
        f"— otherwise a reflection tick re-replies"
    )


def test_t3_4_recent_rejections_exposed_in_view_for_pa(tmp_path):
    """T3.4 — recent_rejections 在 view_for_pa() 顶层暴露, PA 下轮可见."""
    board = _make_board(tmp_path)
    da = DecisionApplier(board)
    # 触发 2 次拒绝
    da.handle_pa_output([
        {"action": "invalid1", "msg_id": "m1", "prompt": "x\n\ny"},
        {"action": "invalid2", "msg_id": "m2", "prompt": "x\n\ny"},
    ])
    view = board.view_for_pa()
    assert "recent_rejections" in view
    assert len(view["recent_rejections"]) == 2
    # 含 offending_msg_id / reason / original_action 字段
    r0 = view["recent_rejections"][0]
    assert "offending_msg_id" in r0
    assert "reason" in r0
    assert "original_action" in r0
