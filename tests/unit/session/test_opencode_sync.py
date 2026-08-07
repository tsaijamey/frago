"""opencode 会话归档同步的单测（spec 20260725 Phase 3）。

临时会话库（``FRAGO_OPENCODE_DB``）+ 临时会话存储目录（``FRAGO_SESSION_DIR`` /
``FRAGO_PROJECTS_DIR``）。NEVER 触碰用户真实的 ``~/.local/share/opencode/opencode.db``
与 ``~/.frago/sessions/``。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.init.opencode_plugin import get_injection_markers
from frago.session import opencode_sync
from frago.session.models import AgentType, SessionStatus, StepType
from frago.session.storage import read_metadata, read_steps

_SCHEMA = """
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
    time_updated integer NOT NULL,
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

# 足够久远的时刻：距今远超 IDLE_SECONDS，故"已 stop 的会话"判为完成。
_T0 = 1_700_000_000_000


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """临时会话库 + 隔离的会话存储目录。返回库路径。"""
    db = tmp_path / "opencode.db"
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(db))
    monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("FRAGO_PROJECTS_DIR", str(tmp_path / "projects"))
    return db


def _connect(db: Path) -> sqlite3.Connection:
    fresh = not db.exists()
    conn = sqlite3.connect(db)
    if fresh:
        conn.executescript(_SCHEMA)
    return conn


def _add_session(
    db: Path,
    session_id: str = "ses_a",
    *,
    directory: str = "/work/proj",
    title: str = "Ping pong test",
    created: int = _T0,
    updated: int = _T0 + 1000,
) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO session (id, directory, title, time_created, time_updated) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, directory, title, created, updated),
        )
        conn.commit()
    finally:
        conn.close()


def _touch_session(db: Path, session_id: str, updated: int) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "UPDATE session SET time_updated = ? WHERE id = ?", (updated, session_id)
        )
        conn.commit()
    finally:
        conn.close()


def _add_message(
    db: Path,
    message_id: str,
    created: int,
    role: str,
    *,
    session_id: str = "ses_a",
    parent: str | None = None,
    finish: str | None = None,
) -> None:
    data: dict[str, Any] = {"role": role, "parentID": parent, "finish": finish}
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (message_id, session_id, created, created, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def _add_part(
    db: Path,
    part_id: str,
    message_id: str,
    created: int,
    data: dict[str, Any],
    *,
    session_id: str = "ses_a",
) -> None:
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (part_id, message_id, session_id, created, created, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def _simple_turn(db: Path) -> None:
    """一问一答，助手已 stop。"""
    _add_session(db)
    _add_message(db, "m_u", _T0 + 10, "user")
    _add_part(db, "p_u", "m_u", _T0 + 11, {"type": "text", "text": "ping"})
    _add_message(db, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(db, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})


# ── 首次归档 ────────────────────────────────────────────────────────
def test_first_sync_archives_session(env: Path) -> None:
    _simple_turn(env)

    result = opencode_sync.sync_opencode_sessions()

    assert result.synced == 1
    assert result.updated == 0
    assert result.errors == []

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.agent_type == AgentType.OPENCODE
    assert meta.project_path == "/work/proj"
    assert meta.step_count == 2

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.type for s in steps] == [
        StepType.USER_MESSAGE,
        StepType.ASSISTANT_MESSAGE,
    ]
    assert steps[0].content_summary == "ping"
    assert steps[1].content_summary == "pong"


def test_title_comes_from_the_session_database(env: Path) -> None:
    """标题用 opencode 自己生成的那条，NEVER 截提示词前 N 字。"""
    _simple_turn(env)
    opencode_sync.sync_opencode_sessions()

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.name == "Ping pong test"


def test_finished_and_idle_session_is_completed(env: Path) -> None:
    _simple_turn(env)
    opencode_sync.sync_opencode_sessions()

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.status == SessionStatus.COMPLETED
    assert meta.ended_at is not None


def test_session_without_stop_is_running(env: Path) -> None:
    """最后一条助手消息还停在 tool-calls → 还在跑，NEVER 判完成。"""
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(env, "p_u", "m_u", _T0 + 11, {"type": "text", "text": "ping"})
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="tool-calls")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "working"})

    opencode_sync.sync_opencode_sessions()

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.status == SessionStatus.RUNNING
    assert meta.ended_at is None


# ── 幂等与增量 ──────────────────────────────────────────────────────
def test_second_sync_without_changes_is_skipped(env: Path) -> None:
    _simple_turn(env)
    assert opencode_sync.sync_opencode_sessions().synced == 1

    again = opencode_sync.sync_opencode_sessions()
    assert again.synced == 0
    assert again.updated == 0
    assert again.skipped == 1

    # 步骤没有被重复追加。
    assert len(read_steps("ses_a", AgentType.OPENCODE)) == 2


def test_new_messages_produce_an_incremental_update(env: Path) -> None:
    _simple_turn(env)
    opencode_sync.sync_opencode_sessions()

    _add_message(env, "m_u2", _T0 + 30, "user")
    _add_part(env, "p_u2", "m_u2", _T0 + 31, {"type": "text", "text": "again?"})
    _add_message(env, "m_a2", _T0 + 40, "assistant", parent="m_u2", finish="stop")
    _add_part(env, "p_a2", "m_a2", _T0 + 41, {"type": "text", "text": "pong again"})
    _touch_session(env, "ses_a", _T0 + 5000)

    second = opencode_sync.sync_opencode_sessions()
    assert second.synced == 0
    assert second.updated == 1

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == [
        "ping",
        "pong",
        "again?",
        "pong again",
    ]


def test_since_updated_cache_skips_untouched_sessions(env: Path) -> None:
    _simple_turn(env)
    cache: dict[str, int] = {}
    assert opencode_sync.sync_opencode_sessions(since_updated_cache=cache).synced == 1
    assert cache["ses_a"] == _T0 + 1000

    second = opencode_sync.sync_opencode_sessions(since_updated_cache=cache)
    assert second.skipped == 1
    assert second.synced == 0


# ── 工具轮次 ────────────────────────────────────────────────────────
def test_tool_turn_produces_call_and_result_steps(env: Path) -> None:
    """一次工具轮次：用户 → 工具调用 + 工具结果 → 终答，共 4 步。"""
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(env, "p_u", "m_u", _T0 + 11, {"type": "text", "text": "list files"})
    _add_message(env, "m_t", _T0 + 20, "assistant", parent="m_u", finish="tool-calls")
    _add_part(env, "p_reason", "m_t", _T0 + 21, {"type": "reasoning", "text": "think"})
    _add_part(
        env,
        "p_tool",
        "m_t",
        _T0 + 22,
        {
            "type": "tool",
            "tool": "bash",
            "callID": "call_1",
            "state": {"status": "completed", "input": {"command": "ls"}, "output": "a\nb"},
        },
    )
    _add_message(env, "m_a", _T0 + 30, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 31, {"type": "text", "text": "2 files"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.type for s in steps] == [
        StepType.USER_MESSAGE,
        StepType.TOOL_CALL,
        StepType.TOOL_RESULT,
        StepType.ASSISTANT_MESSAGE,
    ]
    assert steps[1].tool_name == "bash"
    assert steps[1].tool_call_id == "call_1"

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.step_count == 4
    assert meta.tool_call_count == 1
    # 思考片段 NEVER 进归档。
    assert all("think" not in s.content_summary for s in steps)


def test_synthetic_parts_are_dropped(env: Path) -> None:
    """注入回显不是对话内容，NEVER 归档。"""
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(
        env,
        "p_syn",
        "m_u",
        _T0 + 11,
        {"type": "text", "text": "<editor context>", "synthetic": True},
    )
    _add_part(env, "p_u", "m_u", _T0 + 12, {"type": "text", "text": "ping"})
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == ["ping", "pong"]


# ── frago-hook 注入的剥离 ───────────────────────────────────────────
_BEGIN, _END = get_injection_markers()


def _injected(*blocks: str) -> str:
    return "".join(f"\n\n{_BEGIN}\n{b}\n{_END}" for b in blocks)


def test_single_injection_is_stripped_from_user_step(env: Path) -> None:
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(
        env,
        "p_u",
        "m_u",
        _T0 + 11,
        {"type": "text", "text": "ping" + _injected("行为守则全文")},
    )
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == ["ping", "pong"]


def test_multiple_injections_are_all_stripped(env: Path) -> None:
    """首轮会同时带 SessionStart 与 UserPromptSubmit 两段注入，MUST 全部剥掉。"""
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(
        env,
        "p_u",
        "m_u",
        _T0 + 11,
        {
            "type": "text",
            "text": _injected("守则一") + "\n真正的提问" + _injected("守则二", "守则三"),
        },
    )
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == ["真正的提问", "pong"]
    assert all("守则" not in s.content_summary for s in steps)


def test_user_message_that_is_only_injection_produces_no_step(env: Path) -> None:
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(env, "p_u", "m_u", _T0 + 11, {"type": "text", "text": _injected("守则全文")})
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == ["pong"]
    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.step_count == 1


def test_assistant_text_with_the_same_markers_is_kept(env: Path) -> None:
    """注入只出现在用户侧；助手引用了同样的标记 NEVER 剥（防过度剥离）。"""
    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(env, "p_u", "m_u", _T0 + 11, {"type": "text", "text": "ping"})
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(
        env,
        "p_a",
        "m_a",
        _T0 + 21,
        {"type": "text", "text": f"标记长这样：{_BEGIN}示例{_END}"},
    )

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert steps[1].content_summary == f"标记长这样：{_BEGIN}示例{_END}"


def test_image_description_markers_are_stripped_too(env: Path) -> None:
    """视觉转述走独立标记，归档层 MUST 同样剥掉——它不是用户打的字。"""
    from frago.init.opencode_plugin import get_all_injection_markers

    pairs = dict(get_all_injection_markers())
    img_begin, img_end = "<image-file-desc>", pairs["<image-file-desc>"]

    _add_session(env)
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(
        env,
        "p_u",
        "m_u",
        _T0 + 11,
        {
            "type": "text",
            "text": f"\n\n{img_begin}\n转述内容\n{img_end}\n\n真的提问",
        },
    )
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()

    steps = read_steps("ses_a", AgentType.OPENCODE)
    assert [s.content_summary for s in steps] == ["真的提问", "pong"]
    assert all("转述内容" not in s.content_summary for s in steps)


# ── 标题刷新 ────────────────────────────────────────────────────────
def test_placeholder_title_is_refreshed_on_resync(env: Path) -> None:
    """opencode 事后把占位标题改写成语义标题，归档 MUST 跟着变。"""
    _add_session(env, title="New session - 2026-07-25T02:11:00")
    _add_message(env, "m_u", _T0 + 10, "user")
    _add_part(env, "p_u", "m_u", _T0 + 11, {"type": "text", "text": "ping"})
    _add_message(env, "m_a", _T0 + 20, "assistant", parent="m_u", finish="stop")
    _add_part(env, "p_a", "m_a", _T0 + 21, {"type": "text", "text": "pong"})

    opencode_sync.sync_opencode_sessions()
    first = read_metadata("ses_a", AgentType.OPENCODE)
    assert first is not None
    assert first.name == "New session - 2026-07-25T02:11:00"

    conn = _connect(env)
    try:
        conn.execute("UPDATE session SET title = ? WHERE id = ?", ("Ping pong test", "ses_a"))
        conn.commit()
    finally:
        conn.close()

    second = opencode_sync.sync_opencode_sessions()
    assert second.updated == 1

    meta = read_metadata("ses_a", AgentType.OPENCODE)
    assert meta is not None
    assert meta.name == "Ping pong test"
    # 标题刷新 NEVER 重复追加步骤。
    assert len(read_steps("ses_a", AgentType.OPENCODE)) == 2


# ── 库不存在 ────────────────────────────────────────────────────────
def test_missing_database_returns_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户没装 opencode：空结果，NEVER 抛。"""
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "absent.db"))
    monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("FRAGO_PROJECTS_DIR", str(tmp_path / "projects"))

    result = opencode_sync.sync_opencode_sessions()

    assert (result.synced, result.updated, result.skipped) == (0, 0, 0)
    assert result.errors == []
    assert not (tmp_path / "sessions").exists()


def test_corrupt_database_returns_empty_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken.db"
    broken.write_text("not a sqlite file at all", encoding="utf-8")
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(broken))
    monkeypatch.setenv("FRAGO_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("FRAGO_PROJECTS_DIR", str(tmp_path / "projects"))

    result = opencode_sync.sync_opencode_sessions()

    assert (result.synced, result.updated) == (0, 0)
    assert result.errors == []


# ── 全部会话都归档，不只是 frago 驱动过的 ──────────────────────────
def test_all_sessions_are_archived(env: Path) -> None:
    _simple_turn(env)
    _add_session(env, "ses_b", directory="/other", title="User's own session")
    _add_message(env, "m_ub", _T0 + 10, "user", session_id="ses_b")
    _add_part(
        env, "p_ub", "m_ub", _T0 + 11, {"type": "text", "text": "hi"}, session_id="ses_b"
    )
    _add_message(
        env, "m_ab", _T0 + 20, "assistant", session_id="ses_b", parent="m_ub", finish="stop"
    )
    _add_part(
        env, "p_ab", "m_ab", _T0 + 21, {"type": "text", "text": "hello"}, session_id="ses_b"
    )

    result = opencode_sync.sync_opencode_sessions()

    assert result.synced == 2
    assert read_metadata("ses_b", AgentType.OPENCODE) is not None
