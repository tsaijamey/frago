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
