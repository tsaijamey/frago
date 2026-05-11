"""Phase 0 test_taskboard_models.py — 5 用例 (Ce specify 00:18:41)."""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from frago.server.services.taskboard.models import (
    Intent,
    Msg,
    Session,
    Source,
    Task,
    Thread,
)
from frago.server.services.taskboard.timeline import ulid_new


def _now() -> datetime:
    return datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc)


def test_thread_dataclass_round_trip():
    t = Thread(
        thread_id="01HX0",
        status="active",
        origin="external",
        subkind="feishu",
        root_summary="蔡李瓜测试",
        created_at=_now(),
        last_active_at=_now(),
        senders={"u1", "u2"},
    )
    assert t.thread_id == "01HX0"
    assert t.status == "active"
    assert "u1" in t.senders


def test_msg_status_legal_transitions_only():
    src = Source(
        channel="feishu",
        text="hi",
        sender_id="u1",
        parent_ref=None,
        received_at=_now(),
        reply_context=None,
    )
    msg = Msg(msg_id="feishu:om_001", status="received", source=src)
    # 合法 transition: received → awaiting_decision (Phase 1 由 board 公有方法校验)
    msg.status = "awaiting_decision"
    assert msg.status == "awaiting_decision"


def test_task_session_optional():
    t1 = Task(
        task_id="01TASK1",
        status="queued",
        type="run",
        intent=Intent(prompt="摘要\n\n正文"),
    )
    assert t1.session is None

    t2 = Task(
        task_id="01TASK2",
        status="executing",
        type="run",
        intent=Intent(prompt="摘要\n\n正文"),
        session=Session(
            run_id="01RUN1",
            claude_session_id="csid_xxx",
            pid=12345,
            started_at=_now(),
        ),
    )
    assert t2.session is not None
    assert t2.session.run_id == "01RUN1"


def test_source_immutable_after_init():
    """Ce ask #2: Source frozen=True, 直接断言 FrozenInstanceError."""
    src = Source(
        channel="feishu",
        text="x",
        sender_id="u1",
        parent_ref=None,
        received_at=_now(),
        reply_context=None,
    )
    with pytest.raises(FrozenInstanceError):
        src.channel = "email"  # type: ignore[misc]


def test_timeline_entry_ulid_format():
    """Ce specify: 只校 ULID 字符集 + 单调性, 不校函数位置."""
    crockford = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
    prev = ""
    for _ in range(20):
        u = ulid_new()
        assert crockford.match(u), f"bad ulid: {u}"
        assert u > prev, f"ulid not monotonic: {prev!r} >= {u!r}"
        prev = u
