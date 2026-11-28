"""Phase 2 单测：tmux driver 输出经既有 AgentAdapter 归一化落 storage。

storage 目录用 tmp_path monkeypatch，避免污染真实 ~/.frago。
"""

from __future__ import annotations

import pytest

from frago.agent_driver.tmux_session import TurnResult
from frago.agent_driver.transcript import write_turn
from frago.session.models import AgentType


@pytest.fixture()
def storage_base(tmp_path, monkeypatch):
    base = tmp_path / "sessions"
    monkeypatch.setattr(
        "frago.session.storage.get_session_base_dir", lambda: base
    )
    return base


def _result(text: str) -> TurnResult:
    return TurnResult(text=text, raw_delta=text, status="ok", duration_ms=10)


def test_agent_type_enum_has_opencode_and_codex() -> None:
    assert AgentType("opencode") is AgentType.OPENCODE
    assert AgentType("codex") is AgentType.CODEX


def test_adapters_registered_for_new_agents() -> None:
    from frago.session.monitor import get_adapter

    assert get_adapter(AgentType.OPENCODE) is not None
    assert get_adapter(AgentType.CODEX) is not None
    assert get_adapter(AgentType.CLAUDE) is not None


def test_parse_turn_builds_parsed_record() -> None:
    from datetime import datetime

    from frago.session.monitor import get_adapter

    adapter = get_adapter(AgentType.OPENCODE)
    rec = adapter.parse_turn(
        role="assistant",
        content="hi there",
        session_id="s1",
        uuid="u1",
        timestamp=datetime.now(),
    )
    assert rec.record_type == "assistant"
    assert rec.content_text == "hi there"
    assert rec.session_id == "s1"


def test_write_turn_persists_metadata_and_steps(storage_base) -> None:
    ok = write_turn(
        "sess-oc",
        "opencode",
        "/work/proj",
        "say hello",
        _result("hello!"),
    )
    assert ok is True

    session_dir = storage_base / "opencode" / "sess-oc"
    assert (session_dir / "metadata.json").exists()
    assert (session_dir / "steps.jsonl").exists()

    steps = (session_dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(steps) == 2  # user + assistant
    assert "say hello" in steps[0]
    assert "hello!" in steps[1]


def test_write_turn_appends_across_turns(storage_base) -> None:
    write_turn("s2", "codex", "/w", "q1", _result("a1"))
    write_turn("s2", "codex", "/w", "q2", _result("a2"))

    import json

    meta = json.loads(
        (storage_base / "codex" / "s2" / "metadata.json").read_text(encoding="utf-8")
    )
    assert meta["step_count"] == 4
    assert meta["agent_type"] == "codex"
    steps = (storage_base / "codex" / "s2" / "steps.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(steps) == 4


def test_write_turn_claude_uses_existing_adapter(storage_base) -> None:
    ok = write_turn("s3", "claude", "/w", "hey", _result("yo"))
    assert ok is True
    assert (storage_base / "claude" / "s3" / "metadata.json").exists()


@pytest.mark.usefixtures("storage_base")
def test_list_sessions_sees_tmux_session() -> None:
    from frago.session.storage import list_sessions

    write_turn("s-list", "opencode", "/w", "hello", _result("world"))
    sessions = list_sessions(agent_type=AgentType.OPENCODE, limit=10)
    assert any(s.session_id == "s-list" for s in sessions)


@pytest.mark.parametrize(
    ("turn_status", "expected_session_status", "expect_ended_at"),
    [
        ("ok", "completed", True),
        ("needs_input", "awaiting_input", False),
        ("error", "error", True),
        ("timeout", "error", True),
    ],
)
def test_write_turn_persists_terminal_status_and_ended_at(
    storage_base,
    turn_status: str,
    expected_session_status: str,
    expect_ended_at: bool,
) -> None:
    import json

    sid = f"sess-{turn_status}"
    res = TurnResult(text=f"out-{turn_status}", raw_delta="", status=turn_status, duration_ms=42)
    assert write_turn(sid, "claude", "/w", "prompt", res) is True

    meta = json.loads((storage_base / "claude" / sid / "metadata.json").read_text(encoding="utf-8"))
    assert meta["status"] == expected_session_status
    if expect_ended_at:
        assert meta["ended_at"] is not None
    else:
        assert meta["ended_at"] is None


@pytest.mark.parametrize("agent_type", ["claude", "codex", "opencode", "agy", "coreagent"])
def test_persist_turn_result_skips_native_transcript_drivers(
    storage_base, agent_type: str
) -> None:
    """AC-1：具备原生持久化转录的驱动严禁由外层再写 tmux:// 合成双轨目录。"""
    from frago.agent_driver.transcript import persist_turn_result

    raw_sid = "62d0beb0-d029-4820-8a79-c7727b7dd7cb"
    res = TurnResult(text="ok", raw_delta="", status="ok", duration_ms=1500)
    written = persist_turn_result(
        session_id=raw_sid,
        agent_type=agent_type,
        project_path="/w",
        user_prompt="scheduled run",
        result=res,
        native_session_id=False,
        source="schedule-employee",
    )
    assert written is False
    assert not (storage_base / agent_type / raw_sid).exists()


def test_persist_turn_result_writes_non_native_driver_with_canonical_sid(
    storage_base,
) -> None:
    """无原生转录驱动经统一出口落盘时，强制复用唯一规范会话编号（不分裂 raw_sid 目录）。"""
    from frago.agent_driver.driver import AgentDriver, PaneMatcher
    from frago.agent_driver.transcript import persist_turn_result

    non_native_driver = AgentDriver(
        agent_type="claude",
        launch_command=lambda _ctx: "echo ok",
        ready_signal=PaneMatcher(name="ready", pattern=r"."),
        submit=lambda _s, _p: None,
        done_signal=PaneMatcher(name="done", pattern=r"."),
        extract=lambda s: s,
        transcript_source=None,
        native_transcript=False,
    )
    raw_sid = "62d0beb0-d029-4820-8a79-c7727b7dd7cb"
    from frago.agent_driver.drivers.claude import session_id_for

    expected_canonical = session_id_for(raw_sid, native=False)
    res = TurnResult(text="hello", raw_delta="", status="ok", duration_ms=5000)

    written = persist_turn_result(
        session_id=raw_sid,
        agent_type="claude",
        project_path="/w",
        user_prompt="ping",
        result=res,
        native_session_id=False,
        source="schedule-employee",
        driver=non_native_driver,
    )
    assert written is True
    assert not (storage_base / "claude" / raw_sid).exists()
    assert (storage_base / "claude" / expected_canonical / "metadata.json").exists()


def test_write_turn_timeout_honest_system_event_timestamps_and_schedule_source(
    storage_base,
) -> None:
    """AC-4：>70KB 超长提示词超时不伪造 assistant 答复，保留 started_at < ended_at 与 schedule 来源。"""
    import json
    from datetime import datetime, timedelta

    from frago.session.models import SessionSource, StepType

    long_prompt = "<frago-employee>" + ("A" * 75_000) + "</frago-employee>"
    t0 = datetime(2026, 11, 28, 9, 0, 0)
    t1 = t0 + timedelta(seconds=120)
    # 即便 result.text 误带残片，超时状态也绝不写入 role="assistant"
    res = TurnResult(
        text="<frago-employee>屏抓残片",
        raw_delta="raw pane",
        status="timeout",
        duration_ms=120_000,
        started_at=t0,
        ended_at=t1,
    )
    sid = "sess-long-timeout"
    assert (
        write_turn(sid, "claude", "/w", long_prompt, res, source="schedule-employee")
        is True
    )

    meta = json.loads(
        (storage_base / "claude" / sid / "metadata.json").read_text(encoding="utf-8")
    )
    assert meta["source"] == SessionSource.SCHEDULE.value
    assert meta["status"] == "error"
    started_at = datetime.fromisoformat(meta["started_at"])
    ended_at = datetime.fromisoformat(meta["ended_at"])
    assert started_at < ended_at
    assert (ended_at - started_at).total_seconds() == pytest.approx(120.0, abs=1.0)

    steps_raw = [
        json.loads(line)
        for line in (storage_base / "claude" / sid / "steps.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(steps_raw) == 2
    assert steps_raw[0]["type"] == StepType.USER_MESSAGE.value
    assert steps_raw[1]["type"] == StepType.SYSTEM_EVENT.value
    assert all(s["type"] != StepType.ASSISTANT_MESSAGE.value for s in steps_raw)
    assert "屏抓残片" not in steps_raw[1]["content_summary"]
    assert "[timeout]" in steps_raw[1]["content_summary"]


@pytest.mark.parametrize(
    ("raw_source", "expected"),
    [
        ("schedule-employee", "schedule"),
        ("schedule_employee", "schedule"),
        ("schedule", "schedule"),
        ("employee-invoke", "worker"),
        ("worker", "worker"),
        ("web", "web"),
        ("terminal", "terminal"),
        ("feishu", "channel"),
        ("unknown", "unknown"),
    ],
)
def test_coerce_source_preserves_canonical_origins(
    raw_source: str, expected: str
) -> None:
    from frago.agent_driver.transcript import _coerce_source

    assert _coerce_source(raw_source).value == expected


