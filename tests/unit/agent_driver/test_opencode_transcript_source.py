"""opencode 记录来源的单测（spec 20260725 Phase 2）。

临时 SQLite 库经 ``FRAGO_OPENCODE_DB`` 指过去，NEVER 触碰用户真库。守住六件事：
文本片段成记录、合成片段被丢弃、工具片段产出调用与结果两条、思考与步骤片段被丢弃、
游标只前进不重发、``seek_to_end`` 之后不重放历史。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.agent_driver.drivers.opencode import OpencodeTranscriptSource
from frago.session import opencode_store

_SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL
);
CREATE TABLE message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
CREATE TABLE part (
    id text PRIMARY KEY,
    message_id text NOT NULL,
    session_id text NOT NULL,
    time_created integer NOT NULL,
    time_updated integer NOT NULL,
    data text NOT NULL
);
"""

_SES = "ses_a"


class FakeSession:
    """driver 只从会话对象上取 session_id / native_session_id / cwd。"""

    def __init__(self, session_id: str = "frago-1", *, native: bool = False) -> None:
        self.session_id = session_id
        self.native_session_id = native
        self.cwd = "/w"


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "opencode.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO session (id, directory, title, time_created) VALUES (?,?,'',?)",
        (_SES, "/w", 100),
    )
    conn.commit()
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    yield conn
    conn.close()


def _add_message(conn, mid: str, created: int, role: str) -> None:
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, data) VALUES (?,?,?,?)",
        (mid, _SES, created, json.dumps({"role": role, "parentID": None})),
    )
    conn.commit()


def _add_part(
    conn, pid: str, mid: str, created: int, data: dict[str, Any], updated: int | None = None
) -> None:
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
        "VALUES (?,?,?,?,?,?)",
        (pid, mid, _SES, created, created if updated is None else updated, json.dumps(data)),
    )
    conn.commit()


def _update_part(conn, pid: str, updated: int, data: dict[str, Any]) -> None:
    """原地改写片段——opencode 真实的写法：先插空壳，再把内容 UPDATE 进去。"""
    conn.execute(
        "UPDATE part SET time_updated = ?, data = ? WHERE id = ?",
        (updated, json.dumps(data), pid),
    )
    conn.commit()


def _bound_source(session_id: str = "frago-1") -> OpencodeTranscriptSource:
    """一个已认领会话的来源（绑定文件由目录级 conftest 隔离到临时路径）。"""
    opencode_store.put_binding(session_id, _SES, "/w")
    return OpencodeTranscriptSource(FakeSession(session_id))


# ── 未认领 ──────────────────────────────────────────────────────────
def test_unclaimed_session_yields_nothing(db) -> None:
    """还没认领到 opencode 会话 id → 空列表 + native id 为 None（上层据此退避）。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "answer"})

    source = OpencodeTranscriptSource(FakeSession("frago-unbound"))
    assert source.native_session_id is None
    assert source.poll_once() == []
    source.seek_to_end()  # 也不能崩
    assert source.poll_once() == []


@pytest.mark.usefixtures("db")
def test_native_session_id_reports_binding() -> None:
    source = _bound_source()
    assert source.native_session_id == _SES


# ── 文本片段 ────────────────────────────────────────────────────────
def test_assistant_text_part_becomes_record(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "there are 3 files"})

    records = _bound_source().poll_once()

    assert len(records) == 1
    assert records[0].role == "assistant"
    assert records[0].content_text == "there are 3 files"
    assert records[0].tool_calls == []
    assert records[0].tool_results == []


def test_synthetic_text_part_is_dropped(db) -> None:
    """合成片段是 opencode 注入的编辑器上下文，NEVER 当答案投出去。"""
    _add_message(db, "m0", 5, "user")
    _add_part(db, "p0", "m0", 6, {"type": "text", "text": "<editor ctx>", "synthetic": True})
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "real answer"})

    records = _bound_source().poll_once()

    assert [r.content_text for r in records] == ["real answer"]


def test_user_text_part_is_not_emitted(db) -> None:
    """user 侧文本由主路径自己投递，来源只发助手记录，否则前端会出现两遍。"""
    _add_message(db, "m0", 5, "user")
    _add_part(db, "p0", "m0", 6, {"type": "text", "text": "count the files"})

    assert _bound_source().poll_once() == []


# ── 工具片段 ────────────────────────────────────────────────────────
def test_completed_tool_part_emits_call_then_result(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(
        db,
        "p1",
        "m1",
        11,
        {
            "type": "tool",
            "callID": "call_1",
            "tool": "bash",
            "state": {
                "status": "completed",
                "input": {"command": "ls -la", "nested": {"deep": ["a"]}},
                "output": "file1\nfile2",
            },
        },
    )

    records = _bound_source().poll_once()

    assert len(records) == 2
    call = records[0].tool_calls[0]
    assert call["id"] == "call_1"
    assert call["name"] == "bash"
    # 完整 input 原样保留，嵌套结构不丢。
    assert call["input"] == {"command": "ls -la", "nested": {"deep": ["a"]}}
    result = records[1].tool_results[0]
    assert result["tool_use_id"] == "call_1"
    assert result["content"] == "file1\nfile2"
    assert result["is_error"] is False
    # 同一片段的两条记录 uuid 必须不同，否则前端按 uuid 去重会吃掉一条。
    assert records[0].uuid != records[1].uuid


def test_running_tool_part_emits_only_the_call(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(
        db,
        "p1",
        "m1",
        11,
        {"type": "tool", "callID": "call_1", "tool": "bash", "state": {"status": "running"}},
    )

    records = _bound_source().poll_once()

    assert len(records) == 1
    assert records[0].tool_calls[0]["id"] == "call_1"
    assert records[0].tool_results == []


def test_errored_tool_part_marks_result_as_error(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(
        db,
        "p1",
        "m1",
        11,
        {
            "type": "tool",
            "callID": "call_1",
            "tool": "bash",
            "state": {"status": "error", "error": "command not found"},
        },
    )

    records = _bound_source().poll_once()

    assert len(records) == 2
    result = records[1].tool_results[0]
    assert result["is_error"] is True
    assert result["content"] == "command not found"


# ── 丢弃类片段 ──────────────────────────────────────────────────────
def test_reasoning_and_step_parts_are_dropped(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "step-start"})
    _add_part(db, "p2", "m1", 12, {"type": "reasoning", "text": "secret plan"})
    _add_part(db, "p3", "m1", 13, {"type": "text", "text": "the answer"})
    _add_part(db, "p4", "m1", 14, {"type": "step-finish"})
    _add_part(db, "p5", "m1", 15, {"type": "some-future-kind"})

    records = _bound_source().poll_once()

    assert [r.content_text for r in records] == ["the answer"]


# ── 游标 ────────────────────────────────────────────────────────────
def test_cursor_never_re_emits(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "first"})

    source = _bound_source()
    assert [r.content_text for r in source.poll_once()] == ["first"]
    assert source.poll_once() == []

    _add_part(db, "p2", "m1", 12, {"type": "text", "text": "second"})
    assert [r.content_text for r in source.poll_once()] == ["second"]
    assert source.poll_once() == []


def test_cursor_advances_past_filtered_parts(db) -> None:
    """全被过滤掉的一批也要吃掉位置，否则下一拍重复扫同一批。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "reasoning", "text": "thinking"})

    source = _bound_source()
    assert source.poll_once() == []
    assert source._cursor is not None
    assert source._cursor.part_id == "p1"


def test_cursor_disambiguates_same_millisecond(db) -> None:
    """同一毫秒落多个片段：靠 id 做次级键，既不漏也不重发。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "a"})

    source = _bound_source()
    assert [r.content_text for r in source.poll_once()] == ["a"]

    _add_part(db, "p2", "m1", 11, {"type": "text", "text": "b"})
    assert [r.content_text for r in source.poll_once()] == ["b"]
    assert source.poll_once() == []


def test_seek_to_end_skips_existing_history(db) -> None:
    """续接既有会话时历史 NEVER 被当新增重放。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "history"})

    source = _bound_source()
    source.seek_to_end()
    assert source.poll_once() == []

    _add_part(db, "p2", "m1", 12, {"type": "text", "text": "fresh"})
    assert [r.content_text for r in source.poll_once()] == ["fresh"]


# ── 原地改写（真实写法）────────────────────────────────────────────
def test_text_part_filled_in_by_updates_streams_increments(db) -> None:
    """先建空壳、再分两次把正文更新进来 → 依次拿到两段增量，拼起来是全文、无重复。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": ""})

    source = _bound_source()
    assert source.poll_once() == []  # 空壳还没有内容可发

    _update_part(db, "p1", 20, {"type": "text", "text": "There are "})
    first = [r.content_text for r in source.poll_once()]
    assert first == ["There are "]

    _update_part(db, "p1", 30, {"type": "text", "text": "There are 2 files."})
    second = source.poll_once()
    assert [r.content_text for r in second] == ["2 files."]
    # uuid 必须分开，否则前端按 uuid 去重会把后一段吃掉。
    assert second[0].uuid != "p1"
    assert source.poll_once() == []


def test_tool_part_completed_by_update_emits_call_then_result_once(db) -> None:
    """未完成态先出现、随后被更新为完成态 → 调用一条、结果一条，再轮询不重复。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(
        db,
        "p1",
        "m1",
        11,
        {"type": "tool", "callID": "call_1", "tool": "bash", "state": {"status": "running"}},
    )

    source = _bound_source()
    first = source.poll_once()
    assert len(first) == 1
    assert first[0].tool_calls[0]["id"] == "call_1"

    assert source.poll_once() == []  # 状态没变，不重复发调用

    _update_part(
        db,
        "p1",
        25,
        {
            "type": "tool",
            "callID": "call_1",
            "tool": "bash",
            "state": {"status": "completed", "input": {"command": "ls"}, "output": "f1\nf2"},
        },
    )
    second = source.poll_once()
    assert len(second) == 1
    assert second[0].tool_results[0]["content"] == "f1\nf2"

    assert source.poll_once() == []
    assert source.poll_once() == []


def test_same_part_seen_repeatedly_is_not_re_emitted(db) -> None:
    """游标按更新时间取增量，同一片段会被反复取回——账本必须把重复压掉。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "once"})

    source = _bound_source()
    assert [r.content_text for r in source.poll_once()] == ["once"]
    for _ in range(3):
        assert source.poll_once() == []


def test_seek_to_end_skips_history_that_is_not_updated_again(db) -> None:
    """锚基线后，已存在且不再被改写的历史片段 NEVER 回流。"""
    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "history"})
    _add_part(
        db,
        "p2",
        "m1",
        12,
        {"type": "tool", "callID": "c0", "tool": "bash", "state": {"status": "completed"}},
    )

    source = _bound_source()
    source.seek_to_end()
    assert source.poll_once() == []
    assert source.poll_once() == []

    _add_part(db, "p3", "m1", 20, {"type": "text", "text": "fresh"})
    assert [r.content_text for r in source.poll_once()] == ["fresh"]


def test_missing_db_does_not_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "nope.db"))
    source = _bound_source("frago-nodb")
    source.seek_to_end()
    assert source.poll_once() == []


def test_corrupt_part_json_is_skipped_not_fatal(db) -> None:
    _add_message(db, "m1", 10, "assistant")
    db.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
        "VALUES (?,?,?,?,?,?)",
        ("p1", "m1", _SES, 11, 11, "{not json"),
    )
    db.commit()
    _add_part(db, "p2", "m1", 12, {"type": "text", "text": "ok"})

    assert [r.content_text for r in _bound_source().poll_once()] == ["ok"]


# ── 流式串联 ────────────────────────────────────────────────────────
def test_streamer_consumes_the_source(db) -> None:
    """TranscriptStreamer 对这个来源与对文件版一视同仁（主路径零 agent 分支）。"""
    from frago.agent_driver.streamer import TranscriptStreamer

    _add_message(db, "m1", 10, "assistant")
    _add_part(db, "p1", "m1", 11, {"type": "text", "text": "streamed"})

    streamer = TranscriptStreamer(_bound_source())
    assert streamer.native_session_id == _SES
    assert [r.content_text for r in streamer.poll_once()] == ["streamed"]
