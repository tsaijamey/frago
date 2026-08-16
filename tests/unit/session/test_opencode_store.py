"""opencode 会话库只读访问层 + 身份映射的单测（spec 20260725 Phase 1）。

全部自建临时 SQLite 库（表结构照 opencode 1.18.0 实测），经 ``FRAGO_OPENCODE_DB``
指过去。NEVER 触碰用户真实的 ``~/.local/share/opencode/opencode.db``。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.init.opencode_plugin import get_injection_markers
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
    data text NOT NULL
);
"""


def _build_db(
    path: Path,
    *,
    sessions: list[tuple[str, str, int]] | None = None,
    messages: list[tuple[str, str, int, dict[str, Any]]] | None = None,
    parts: list[tuple[str, str, str, int, dict[str, Any]]] | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        for sid, directory, created in sessions or []:
            conn.execute(
                "INSERT INTO session (id, directory, title, time_created) "
                "VALUES (?, ?, '', ?)",
                (sid, directory, created),
            )
        for mid, sid, created, data in messages or []:
            conn.execute(
                "INSERT INTO message (id, session_id, time_created, data) "
                "VALUES (?, ?, ?, ?)",
                (mid, sid, created, json.dumps(data)),
            )
        for pid, mid, sid, created, data in parts or []:
            conn.execute(
                "INSERT INTO part (id, message_id, session_id, time_created, data) "
                "VALUES (?, ?, ?, ?, ?)",
                (pid, mid, sid, created, json.dumps(data)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "opencode.db"
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(path))
    return path


def _user() -> dict[str, Any]:
    return {"role": "user", "parentID": None, "finish": None, "time": {"created": 1}}


def _assistant(parent: str, finish: str | None, completed: int | None = None) -> dict[str, Any]:
    return {
        "role": "assistant",
        "parentID": parent,
        "finish": finish,
        "time": {"created": 1, "completed": completed},
    }


# ── db_path ────────────────────────────────────────────────────────
def test_db_path_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "x.db"))
    assert opencode_store.db_path() == tmp_path / "x.db"


def test_db_path_defaults_when_env_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRAGO_OPENCODE_DB", raising=False)
    assert opencode_store.db_path() == opencode_store.DEFAULT_DB_PATH


# ── latest_turn ────────────────────────────────────────────────────
def test_latest_turn_aggregates_across_tool_calls_until_stop(db: Path) -> None:
    """一轮里有 tool-calls 中途段 + 末条 stop → done，文本跨消息聚合。"""
    _build_db(
        db,
        sessions=[("ses_a", "/w", 100)],
        messages=[
            ("m_user", "ses_a", 10, _user()),
            ("m_tool", "ses_a", 20, _assistant("m_user", "tool-calls", 25)),
            ("m_stop", "ses_a", 30, _assistant("m_user", "stop", 35)),
        ],
        parts=[
            ("p1", "m_tool", "ses_a", 21, {"type": "step-start"}),
            ("p2", "m_tool", "ses_a", 22, {"type": "text", "text": "let me look"}),
            ("p3", "m_tool", "ses_a", 23, {"type": "tool", "text": "ls"}),
            ("p4", "m_stop", "ses_a", 31, {"type": "text", "text": "there are 3 files"}),
        ],
    )
    turn = opencode_store.latest_turn("ses_a")
    assert turn is not None
    assert turn.done is True
    assert turn.final_message_id == "m_stop"
    assert turn.parent_id == "m_user"
    assert turn.text == "let me look\nthere are 3 files"
    assert turn.completed_at == 35


def test_latest_turn_tool_calls_only_is_not_done(db: Path) -> None:
    """本轮只有 tool-calls（还没答完）→ NEVER 判为答完，也没有锚点。"""
    _build_db(
        db,
        sessions=[("ses_a", "/w", 100)],
        messages=[
            ("m_user", "ses_a", 10, _user()),
            ("m_tool", "ses_a", 20, _assistant("m_user", "tool-calls", 25)),
        ],
        parts=[("p1", "m_tool", "ses_a", 21, {"type": "text", "text": "half answer"})],
    )
    turn = opencode_store.latest_turn("ses_a")
    assert turn is not None
    assert turn.done is False
    assert turn.final_message_id is None
    assert turn.completed_at is None


def test_latest_turn_drops_reasoning_parts(db: Path) -> None:
    _build_db(
        db,
        sessions=[("ses_a", "/w", 100)],
        messages=[
            ("m_user", "ses_a", 10, _user()),
            ("m_stop", "ses_a", 20, _assistant("m_user", "stop", 25)),
        ],
        parts=[
            ("p1", "m_stop", "ses_a", 21, {"type": "reasoning", "text": "secret plan"}),
            ("p2", "m_stop", "ses_a", 22, {"type": "text", "text": "the answer"}),
            ("p3", "m_stop", "ses_a", 23, {"type": "step-finish"}),
        ],
    )
    turn = opencode_store.latest_turn("ses_a")
    assert turn is not None
    assert turn.text == "the answer"
    assert "secret plan" not in turn.text


def test_latest_turn_scopes_to_newest_user_message(db: Path) -> None:
    """多轮常驻会话：只取最新一轮，NEVER 把上一轮的答案带出来。"""
    _build_db(
        db,
        sessions=[("ses_a", "/w", 100)],
        messages=[
            ("m_u1", "ses_a", 10, _user()),
            ("m_a1", "ses_a", 20, _assistant("m_u1", "stop", 25)),
            ("m_u2", "ses_a", 30, _user()),
            ("m_a2", "ses_a", 40, _assistant("m_u2", "stop", 45)),
        ],
        parts=[
            ("p1", "m_a1", "ses_a", 21, {"type": "text", "text": "first answer"}),
            ("p2", "m_a2", "ses_a", 41, {"type": "text", "text": "second answer"}),
        ],
    )
    turn = opencode_store.latest_turn("ses_a")
    assert turn is not None
    assert turn.parent_id == "m_u2"
    assert turn.final_message_id == "m_a2"
    assert turn.text == "second answer"


def test_latest_turn_unknown_session_returns_none(db: Path) -> None:
    _build_db(db, sessions=[("ses_a", "/w", 100)])
    assert opencode_store.latest_turn("ses_missing") is None


def test_latest_turn_missing_db_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "nope.db"))
    assert opencode_store.latest_turn("ses_a") is None


def test_latest_turn_corrupt_db_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken.db"
    broken.write_text("not a sqlite file at all", encoding="utf-8")
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(broken))
    assert opencode_store.latest_turn("ses_a") is None
    assert opencode_store.claim_session("/w", 0) is None


def test_latest_turn_corrupt_message_json_is_skipped(db: Path) -> None:
    """单条消息的 data 损坏不能把整轮读崩，只当它不存在。"""
    _build_db(
        db,
        sessions=[("ses_a", "/w", 100)],
        messages=[("m_user", "ses_a", 10, _user())],
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, data) VALUES (?,?,?,?)",
        ("m_bad", "ses_a", 20, "{not json"),
    )
    conn.commit()
    conn.close()
    turn = opencode_store.latest_turn("ses_a")
    assert turn is not None
    assert turn.done is False


# ── claim_session ──────────────────────────────────────────────────
def test_claim_session_picks_newest_in_directory_and_window(db: Path) -> None:
    _build_db(
        db,
        sessions=[
            ("ses_old", "/w", 100),
            ("ses_new", "/w", 300),
            ("ses_other", "/elsewhere", 400),
        ],
    )
    assert opencode_store.claim_session("/w", 200) == "ses_new"


def test_claim_session_rejects_other_directory(db: Path) -> None:
    _build_db(db, sessions=[("ses_other", "/elsewhere", 400)])
    assert opencode_store.claim_session("/w", 0) is None


def test_claim_session_rejects_rows_before_window(db: Path) -> None:
    _build_db(db, sessions=[("ses_old", "/w", 100)])
    assert opencode_store.claim_session("/w", 200) is None


def test_claim_session_matches_through_symlinked_directory(
    db: Path, tmp_path: Path
) -> None:
    """库里存真实路径、调用方给软链接路径 → 必须认得到。

    macOS 上 ``/tmp`` 就是 ``/private/tmp`` 的软链接，这不是边角场景。
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    _build_db(db, sessions=[("ses_real", str(real), 300)])
    assert opencode_store.claim_session(str(link / "sub"), 200) is None
    assert opencode_store.claim_session(str(link), 200) == "ses_real"


def test_claim_session_still_matches_unresolved_value_in_db(
    db: Path, tmp_path: Path
) -> None:
    """库里万一存的是未解析的原值，按原值再查一次也要命中。"""
    real = tmp_path / "real2"
    real.mkdir()
    link = tmp_path / "link2"
    link.symlink_to(real)
    _build_db(db, sessions=[("ses_raw", str(link), 300)])
    assert opencode_store.claim_session(str(link), 200) == "ses_raw"


def test_put_binding_stores_resolved_directory(
    bindings: Path, tmp_path: Path
) -> None:
    real = tmp_path / "real3"
    real.mkdir()
    link = tmp_path / "link3"
    link.symlink_to(real)
    opencode_store.put_binding("frago-sym", "ses_x", str(link))
    payload = json.loads(bindings.read_text(encoding="utf-8"))
    assert payload["frago-sym"]["directory"] == str(real.resolve())


# ── session_exists ─────────────────────────────────────────────────
def test_session_exists_true_for_present_row(db: Path) -> None:
    _build_db(db, sessions=[("ses_a", "/w", 100)])
    assert opencode_store.session_exists("ses_a") is True


def test_session_exists_false_for_deleted_row(db: Path) -> None:
    _build_db(db, sessions=[("ses_a", "/w", 100)])
    assert opencode_store.session_exists("ses_gone") is False


def test_session_exists_true_when_db_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """库不可读 ≠ 会话不存在，NEVER 因一次读失败清掉好绑定。"""
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "nope.db"))
    assert opencode_store.session_exists("ses_a") is True


def test_session_exists_true_when_db_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken2.db"
    broken.write_text("not a sqlite file at all", encoding="utf-8")
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(broken))
    assert opencode_store.session_exists("ses_a") is True


def test_claim_session_missing_db_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "nope.db"))
    assert opencode_store.claim_session("/w", 0) is None


# ── part_payloads：synthetic 丢弃与 frago-hook 注入剥离 ─────────────
#
# 这套覆盖原先挂在 opencode 归档同步的测试里（同步会走 ``part_payloads``）。同步
# 现在改成纯备份、不再经过这一层，但这些行为对实时流与会话详情展示依然有效，所以
# 覆盖搬到这里，直接对着 ``part_payloads`` 断言。
_BEGIN, _END = get_injection_markers()


def _item(
    part: dict[str, Any],
    *,
    role: str = "user",
    part_id: str = "p_u",
    message_id: str = "m_u",
) -> dict[str, Any]:
    """``session_parts`` 每个元素的形状。"""
    return {
        "part": part,
        "role": role,
        "message_id": message_id,
        "time_created": 1_700_000_000_000,
        "time_updated": 1_700_000_000_000,
        "part_id": part_id,
    }


def _injected(*blocks: str) -> str:
    return "".join(f"\n\n{_BEGIN}\n{b}\n{_END}" for b in blocks)


def _contents(item: dict[str, Any]) -> list[tuple[str, str]]:
    """``(种类, 正文)``，把断言从时间戳等无关字段里摘出来。"""
    return [
        (kind, record["content"])
        for kind, record in opencode_store.part_payloads(
            item, "ses_a", include_user=True
        )
    ]


def test_synthetic_parts_are_dropped() -> None:
    """注入回显不是对话内容，NEVER 产出记录。"""
    item = _item({"type": "text", "text": "<editor context>", "synthetic": True})
    assert opencode_store.part_payloads(item, "ses_a", include_user=True) == []


def test_single_injection_is_stripped_from_user_text() -> None:
    item = _item({"type": "text", "text": "ping" + _injected("行为守则全文")})
    assert _contents(item) == [(opencode_store.PART_USER_TEXT, "ping")]


def test_multiple_injections_are_all_stripped() -> None:
    """首轮会同时带 SessionStart 与 UserPromptSubmit 两段注入，MUST 全部剥掉。"""
    item = _item(
        {
            "type": "text",
            "text": _injected("守则一") + "\n真正的提问" + _injected("守则二", "守则三"),
        }
    )
    assert _contents(item) == [(opencode_store.PART_USER_TEXT, "真正的提问")]


def test_user_text_that_is_only_injection_produces_no_payload() -> None:
    item = _item({"type": "text", "text": _injected("守则全文")})
    assert opencode_store.part_payloads(item, "ses_a", include_user=True) == []


def test_assistant_text_with_the_same_markers_is_kept() -> None:
    """注入只出现在用户侧；助手引用了同样的标记 NEVER 剥（防过度剥离）。"""
    text = f"标记长这样：{_BEGIN}示例{_END}"
    item = _item({"type": "text", "text": text}, role="assistant", part_id="p_a")
    assert _contents(item) == [(opencode_store.PART_TEXT, text)]


def test_image_description_markers_are_stripped_too() -> None:
    """视觉转述走独立标记，MUST 同样剥掉——它不是用户打的字。"""
    from frago.init.opencode_plugin import get_all_injection_markers

    pairs = dict(get_all_injection_markers())
    img_begin, img_end = "<image-file-desc>", pairs["<image-file-desc>"]

    item = _item(
        {"type": "text", "text": f"\n\n{img_begin}\n转述内容\n{img_end}\n\n真的提问"}
    )
    assert _contents(item) == [(opencode_store.PART_USER_TEXT, "真的提问")]


# ── 身份映射 ────────────────────────────────────────────────────────
@pytest.fixture
def bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "opencode-sessions.json"
    monkeypatch.setattr(opencode_store, "BINDINGS_PATH", path)
    return path


def test_binding_roundtrip(bindings: Path) -> None:
    assert opencode_store.get_binding("frago-1") is None
    opencode_store.put_binding("frago-1", "ses_x", "/w")
    assert opencode_store.get_binding("frago-1") == "ses_x"
    payload = json.loads(bindings.read_text(encoding="utf-8"))
    assert payload["frago-1"]["directory"] == "/w"
    assert isinstance(payload["frago-1"]["claimed_at"], int)


@pytest.mark.usefixtures("bindings")
def test_binding_second_entry_does_not_clobber_first() -> None:
    opencode_store.put_binding("frago-1", "ses_x", "/w")
    opencode_store.put_binding("frago-2", "ses_y", "/w2")
    assert opencode_store.get_binding("frago-1") == "ses_x"
    assert opencode_store.get_binding("frago-2") == "ses_y"


@pytest.mark.usefixtures("bindings")
def test_drop_binding() -> None:
    opencode_store.put_binding("frago-1", "ses_x", "/w")
    opencode_store.drop_binding("frago-1")
    assert opencode_store.get_binding("frago-1") is None
    # 掉一个不存在的绑定不报错。
    opencode_store.drop_binding("frago-1")


def test_binding_missing_file_reads_as_unbound(bindings: Path) -> None:
    assert not bindings.exists()
    assert opencode_store.get_binding("anything") is None


def test_binding_corrupt_file_reads_as_unbound_and_recovers(bindings: Path) -> None:
    bindings.write_text("{ this is not json", encoding="utf-8")
    assert opencode_store.get_binding("frago-1") is None
    # 损坏文件不能挡住后续写入。
    opencode_store.put_binding("frago-1", "ses_x", "/w")
    assert opencode_store.get_binding("frago-1") == "ses_x"


def test_binding_non_object_payload_reads_as_unbound(bindings: Path) -> None:
    bindings.write_text('["not", "a", "map"]', encoding="utf-8")
    assert opencode_store.get_binding("frago-1") is None
