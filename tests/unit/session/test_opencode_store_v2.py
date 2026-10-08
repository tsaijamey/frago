"""opencode 2.0 那套会话库的读取单测。

2.0 把会话搬到了 ``session_v2`` + ``session_message``：片段不再单独成表，而是嵌在
消息的 ``content`` 数组里；轮次边界从 ``parentID`` 改成 ``seq`` 次序。表结构照
2026-10-09 从本机 2.0.20 的库里实测的形态建，NEVER 触碰用户真实的库。

与 1.18 那套并存是常态：升级当天的库里两套都有，故有一组用例专门盯"两套并起来读"。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.session import opencode_store

_V2_SCHEMA = """
CREATE TABLE session_v2 (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL,
    time_updated integer NOT NULL
);
CREATE TABLE session_message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    type text NOT NULL,
    seq integer NOT NULL,
    time_created integer NOT NULL,
    time_updated integer NOT NULL,
    data text NOT NULL
);
"""

_LEGACY_SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    time_created integer NOT NULL,
    time_updated integer NOT NULL
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
    data text NOT NULL
);
"""


def _dump(data: dict[str, Any]) -> str:
    """按 opencode 真实的存法序列化：中文**原样**存 UTF-8，不做 ``\\uXXXX`` 转义。

    这是 ``sessions_containing`` 那类 LIKE 粗筛成立的前提。用默认的 ``ensure_ascii``
    会把中文写成转义序列，按中文搜就一条都命不中——那是测试自己造出来的假缺陷。
    """
    return json.dumps(data, ensure_ascii=False)


def _build(
    path: Path,
    *,
    v2_sessions: list[tuple[str, str, int, int]] | None = None,
    rows: list[tuple[str, str, str, int, int, int, dict[str, Any]]] | None = None,
    legacy_sessions: list[tuple[str, str, int]] | None = None,
    legacy_messages: list[tuple[str, str, int, dict[str, Any]]] | None = None,
) -> None:
    """v2_sessions: (id, directory, created, updated)；rows: (mid, sid, type, seq, created, updated, data)。"""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_V2_SCHEMA)
        conn.executescript(_LEGACY_SCHEMA)
        for sid, directory, created, updated in v2_sessions or []:
            conn.execute(
                "INSERT INTO session_v2 (id, directory, title, time_created, time_updated) "
                "VALUES (?, ?, '', ?, ?)",
                (sid, directory, created, updated),
            )
        for mid, sid, mtype, seq, created, updated, data in rows or []:
            conn.execute(
                "INSERT INTO session_message "
                "(id, session_id, type, seq, time_created, time_updated, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (mid, sid, mtype, seq, created, updated, _dump(data)),
            )
        for sid, directory, created in legacy_sessions or []:
            conn.execute(
                "INSERT INTO session (id, directory, title, time_created, time_updated) "
                "VALUES (?, ?, '', ?, ?)",
                (sid, directory, created, created),
            )
        for mid, sid, created, data in legacy_messages or []:
            conn.execute(
                "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
                (mid, sid, created, _dump(data)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "opencode.db"
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    return path


def _user(text: str = "hi", *, created: int = 100, synthetic: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {"time": {"created": created}, "text": text, "files": []}
    if synthetic:
        data["synthetic"] = True
    return data


def _assistant(
    content: list[dict[str, Any]],
    *,
    finish: str | None = "stop",
    created: int = 200,
    completed: int | None = 260,
) -> dict[str, Any]:
    time: dict[str, Any] = {"created": created, "streamed": created}
    if completed is not None:
        time["completed"] = completed
    data: dict[str, Any] = {
        "time": time,
        "agent": "build",
        "model": {"id": "m", "providerID": "p"},
        "content": content,
    }
    if finish is not None:
        data["finish"] = finish
    return data


def _text(piece: str) -> dict[str, Any]:
    return {"type": "text", "text": piece}


def _tool(command: str, output: str) -> dict[str, Any]:
    return {
        "type": "tool",
        "id": "call_1",
        "name": "shell",
        "state": {
            "status": "completed",
            "input": {"command": command},
            "content": [{"type": "text", "text": output}],
            "metadata": {"exit": 0},
        },
        "time": {"created": 150},
    }


# ── latest_turn ────────────────────────────────────────────────────
def test_latest_turn_v2_aggregates_until_final_segment(db: Path) -> None:
    """工具段（tool-calls）不算答完，末段（stop）才算；文本跨消息聚成一条。"""
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("do it")),
            (
                "m2",
                "ses_v2",
                "assistant",
                2,
                150,
                160,
                _assistant([_tool("ls", "a\n")], finish="tool-calls"),
            ),
            ("m3", "ses_v2", "assistant", 3, 200, 260, _assistant([_text("done")], finish="stop")),
            (
                "m4",
                "ses_v2",
                "idle",
                4,
                261,
                261,
                {"time": {"created": 261}, "outcome": "succeeded"},
            ),
        ],
    )
    turn = opencode_store.latest_turn("ses_v2")
    assert turn is not None
    assert turn.done is True
    assert turn.parent_id == "m1"
    assert turn.final_message_id == "m3"
    assert turn.completed_at == 260
    assert turn.text == "done"


def test_latest_turn_v2_not_done_while_streaming(db: Path) -> None:
    """正在生成的那条没有 time.completed → 本轮未答完。"""
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("do it")),
            (
                "m2",
                "ses_v2",
                "assistant",
                2,
                150,
                160,
                _assistant([_tool("ls", "a\n")], finish="tool-calls"),
            ),
            (
                "m3",
                "ses_v2",
                "assistant",
                3,
                200,
                210,
                _assistant([_text("partial")], finish=None, completed=None),
            ),
        ],
    )
    turn = opencode_store.latest_turn("ses_v2")
    assert turn is not None
    assert turn.done is False
    assert turn.final_message_id is None
    assert turn.text == "partial"


def test_latest_turn_v2_only_reads_the_latest_turn(db: Path) -> None:
    """上一轮的回答 MUST 不进本轮文本。"""
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("first")),
            ("m2", "ses_v2", "assistant", 2, 150, 160, _assistant([_text("old answer")])),
            ("m3", "ses_v2", "user", 3, 300, 300, _user("second")),
            ("m4", "ses_v2", "assistant", 4, 320, 340, _assistant([_text("new answer")])),
        ],
    )
    turn = opencode_store.latest_turn("ses_v2")
    assert turn is not None
    assert turn.parent_id == "m3"
    assert turn.text == "new answer"


def test_latest_turn_v2_synthetic_user_is_not_the_anchor(db: Path) -> None:
    """opencode 自己注入的编辑器上下文落在真人提问之后，不能当轮次锚点。

    拿它当锚点，本轮一条助手消息都圈不到，本轮就永远判不出答完——那正是"静默等到
    超时"的形态。
    """
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("real question")),
            ("m2", "ses_v2", "assistant", 2, 150, 200, _assistant([_text("answer")])),
            ("m3", "ses_v2", "synthetic", 3, 210, 210, _user("editor context")),
        ],
    )
    turn = opencode_store.latest_turn("ses_v2")
    assert turn is not None
    assert turn.done is True
    assert turn.parent_id == "m1"
    assert turn.text == "answer"


# ── 会话存在性 / 目录 / 认领 ────────────────────────────────────────
def test_claim_session_finds_v2_row(db: Path) -> None:
    _build(db, v2_sessions=[("ses_v2", "/w", 500, 900)])
    assert opencode_store.claim_session("/w", since_ms=100) == "ses_v2"
    # 起算点之后的才算这一场：更早的老会话 MUST 认不到。
    assert opencode_store.claim_session("/w", since_ms=600) is None


def test_claim_session_prefers_the_newer_of_the_two_stores(db: Path) -> None:
    """升级当天两套表都有新行时，取创建更晚的那条。"""
    _build(
        db,
        v2_sessions=[("ses_new", "/w", 900, 950)],
        legacy_sessions=[("ses_old", "/w", 500)],
    )
    assert opencode_store.claim_session("/w", since_ms=100) == "ses_new"


def test_session_exists_and_directory_cover_both_stores(db: Path) -> None:
    _build(
        db,
        v2_sessions=[("ses_v2", "/v2dir", 1, 2)],
        legacy_sessions=[("ses_old", "/olddir", 1)],
    )
    assert opencode_store.session_exists("ses_v2") is True
    assert opencode_store.session_exists("ses_old") is True
    assert opencode_store.session_exists("ses_missing") is False
    assert opencode_store.session_directory("ses_v2") == "/v2dir"
    assert opencode_store.session_directory("ses_old") == "/olddir"


def test_session_exists_true_when_db_corrupt_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """库读不动 → 保守答"在"（不可读不等于被删）。"""
    broken = tmp_path / "broken.db"
    broken.write_text("not a sqlite file at all", encoding="utf-8")
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(broken))
    assert opencode_store.session_exists("ses_a") is True
    assert opencode_store.list_sessions() == []


# ── 全量读取 ────────────────────────────────────────────────────────
def test_list_sessions_unions_both_stores(db: Path) -> None:
    _build(
        db,
        v2_sessions=[("ses_v2", "/v2dir", 1, 400)],
        legacy_sessions=[("ses_old", "/olddir", 1)],
    )
    listed = {row.session_id: row for row in opencode_store.list_sessions()}
    assert set(listed) == {"ses_v2", "ses_old"}
    assert listed["ses_v2"].directory == "/v2dir"
    assert listed["ses_v2"].time_updated == 400


def test_last_assistant_finish_reads_v2_rows(db: Path) -> None:
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user()),
            (
                "m2",
                "ses_v2",
                "assistant",
                2,
                150,
                160,
                _assistant([_text("x")], finish="tool-calls"),
            ),
            ("m3", "ses_v2", "assistant", 3, 200, 260, _assistant([_text("y")], finish="stop")),
        ],
    )
    assert opencode_store.last_assistant_finish("ses_v2") == "stop"


def test_sessions_containing_searches_v2_messages(db: Path) -> None:
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("找一下那笔对账单")),
            ("m2", "ses_v2", "assistant", 2, 150, 160, _assistant([_text("好的")])),
        ],
    )
    assert opencode_store.sessions_containing(["对账单"]) == {"ses_v2"}
    assert opencode_store.sessions_containing(["不存在的词"]) == set()


# ── 片段：嵌在消息里的那套 ──────────────────────────────────────────
def test_session_parts_flattens_embedded_content(db: Path) -> None:
    """v2 的片段嵌在消息里，摊出来要跟 1.18 的条目同形状。"""
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "user", 1, 100, 100, _user("do it")),
            (
                "m2",
                "ses_v2",
                "assistant",
                2,
                150,
                160,
                _assistant([_tool("ls", "a\n"), _text("done")]),
            ),
        ],
    )
    items = opencode_store.session_parts("ses_v2")
    assert [(item["message_id"], item["part"]["type"]) for item in items] == [
        ("m1", "text"),
        ("m2", "tool"),
        ("m2", "text"),
    ]
    assert [item["role"] for item in items] == ["user", "assistant", "assistant"]
    # 片段 id 在消息内唯一且排序稳定（补零）。
    assert items[1]["part_id"] == "m2:0000"
    assert items[2]["part_id"] == "m2:0001"


def test_v2_tool_part_is_renamed_to_the_legacy_shape(db: Path) -> None:
    """工具片段的两处改名：``name``→``tool``、``state.content``→``state.output``。

    下游的 ``part_payloads`` 只认 1.18 那套字段名，翻译不到位就整条工具记录丢失。
    """
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m2", "ses_v2", "assistant", 2, 150, 160, _assistant([_tool("ls -la", "total 0\n")])),
        ],
    )
    items = opencode_store.session_parts("ses_v2")
    assert len(items) == 1
    part = items[0]["part"]
    assert part["tool"] == "shell"
    assert part["state"]["output"] == "total 0\n"

    payloads = opencode_store.part_payloads(items[0], "ses_v2")
    kinds = [kind for kind, _ in payloads]
    assert kinds == [opencode_store.PART_TOOL_CALL, opencode_store.PART_TOOL_RESULT]
    assert payloads[0][1]["tool_calls"][0]["name"] == "shell"
    assert payloads[0][1]["tool_calls"][0]["input"] == {"command": "ls -la"}
    assert payloads[1][1]["tool_results"][0]["content"] == "total 0\n"
    assert payloads[1][1]["tool_results"][0]["is_error"] is False


def test_user_text_is_captured_from_the_message_field(db: Path) -> None:
    """用户消息的正文挂在 ``data.text`` 上，不在 ``content`` 数组里。

    漏了这一步，归档与搜索里用户说过的话一个字都不剩——会话详情只剩助手那半边。
    """
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[("m1", "ses_v2", "user", 1, 100, 100, _user("帮我看看那笔对账单"))],
    )
    items = opencode_store.session_parts("ses_v2")
    assert [item["part"]["type"] for item in items] == ["text"]
    assert items[0]["role"] == "user"
    payloads = opencode_store.part_payloads(items[0], "ses_v2", include_user=True)
    assert [kind for kind, _ in payloads] == [opencode_store.PART_USER_TEXT]
    assert payloads[0][1]["content"] == "帮我看看那笔对账单"


def test_synthetic_message_parts_are_dropped(db: Path) -> None:
    """注入的编辑器上下文不能当答案混进流里。

    两种落点都要挡住：2.0 把注入单列成 ``type == "synthetic"`` 的消息；同一条规则
    在 1.18 是片段上的 ``synthetic`` 字段，故 user 消息自带该字段时也要认。
    """
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "synthetic", 1, 100, 100, _user("editor context")),
            ("m2", "ses_v2", "user", 2, 110, 110, _user("marked inline", synthetic=True)),
        ],
    )
    items = opencode_store.session_parts("ses_v2")
    # 整条 synthetic 的消息根本不成条目；带标记的 user 消息成条目但产出被丢弃。
    assert [item["message_id"] for item in items] == ["m2"]
    for item in items:
        assert opencode_store.part_payloads(item, "ses_v2", include_user=True) == []


def test_parts_since_v2_advances_cursor_on_message_rows(db: Path) -> None:
    """游标锚在消息行上：片段被过滤掉也要前进，否则下一拍重扫同一批。"""
    _build(
        db,
        v2_sessions=[("ses_v2", "/w", 1, 400)],
        rows=[
            ("m1", "ses_v2", "assistant", 1, 100, 150, _assistant([_text("a")])),
            ("m2", "ses_v2", "assistant", 2, 160, 220, _assistant([_text("b")])),
        ],
    )
    items, cursor = opencode_store.parts_since("ses_v2", None)
    assert len(items) == 2
    assert cursor == opencode_store.PartCursor(time_updated=220, part_id="m2")
    assert opencode_store.latest_cursor("ses_v2") == cursor

    # 取过之后带上游标再来一次：只有边界那一拍会被复取（>= 的半开区间），
    # 更早的那条不再出现。
    again, _ = opencode_store.parts_since("ses_v2", cursor)
    assert [item["part_id"] for item in again] == ["m2:0000"]
