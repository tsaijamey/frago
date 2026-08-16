"""opencode 会话归档同步的单测（spec 20260725 Phase 3）。

临时会话库（``FRAGO_OPENCODE_DB``）+ 临时会话存储目录（``FRAGO_SESSION_DIR`` /
``FRAGO_PROJECTS_DIR``）。NEVER 触碰用户真实的 ``~/.local/share/opencode/opencode.db``
与 ``~/.frago/sessions/``。

覆盖面止于 ``raw.jsonl``：同步现在是**纯备份**，一个会话目录下只写这一个文件，
不再产出 ``metadata.json``。原先盯标题（``meta.name``）与会话状态
（running/completed、``ended_at``、``step_count``）的四条用例已删除——
备份不解读内容，这些概念在新契约里不再存在，换个断言也救不回来：

- ``test_title_comes_from_the_session_database``
- ``test_finished_and_idle_session_is_completed``
- ``test_session_without_stop_is_running``
- ``test_placeholder_title_is_refreshed_on_resync``

留下的用例只问三件事：备份行数是否等于库里的片段数、每行是否是库里那个原始
``part`` 字典、重复同步会不会把行数翻倍。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from frago.session import opencode_sync

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

# 造数据用的时间基准（毫秒）。备份不看时刻，取个固定值即可。
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


def _raw(session_id: str = "ses_a") -> list[dict[str, Any]]:
    """备份文件里的原始片段，一行一个。没备过就是空。"""
    path = opencode_sync.raw_backup_path(session_id)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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

    # 备份是原始片段的逐行副本，NEVER 解读成步骤。
    assert _raw() == [
        {"type": "text", "text": "ping"},
        {"type": "text", "text": "pong"},
    ]


def test_backup_directory_holds_only_the_raw_file(env: Path) -> None:
    """纯备份：会话目录下只有 raw.jsonl，NEVER 再产出 metadata.json。"""
    _simple_turn(env)

    opencode_sync.sync_opencode_sessions()

    session_dir = opencode_sync.raw_backup_path("ses_a").parent
    assert sorted(p.name for p in session_dir.iterdir()) == ["raw.jsonl"]


# ── 幂等与增量 ──────────────────────────────────────────────────────
def test_second_sync_without_changes_is_skipped(env: Path) -> None:
    _simple_turn(env)
    assert opencode_sync.sync_opencode_sessions().synced == 1

    again = opencode_sync.sync_opencode_sessions()
    assert again.synced == 0
    assert again.updated == 0
    assert again.skipped == 1

    # 片段没有被重复追加——行数不翻倍。
    assert len(_raw()) == 2


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

    # 只追加新片段，旧的原样留在前面。
    assert [p["text"] for p in _raw()] == [
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
def test_tool_turn_is_backed_up_as_one_part(env: Path) -> None:
    """一次工具轮次：备份不拆调用/结果，工具片段就是库里那一条原始记录。"""
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

    parts = _raw()
    assert [p["type"] for p in parts] == ["text", "reasoning", "tool", "text"]
    # 工具片段是一条，state 原封不动——NEVER 拆成 call + result 两条。
    assert parts[2] == {
        "type": "tool",
        "tool": "bash",
        "callID": "call_1",
        "state": {"status": "completed", "input": {"command": "ls"}, "output": "a\nb"},
    }
    # 备份要库里本来的样子，reasoning 同样留着。
    assert parts[1] == {"type": "reasoning", "text": "think"}


# 注：synthetic 片段的丢弃与 frago-hook 注入的剥离是 ``opencode_store.part_payloads``
# 的行为，备份不再经过那一层（备份要库里本来的样子）。那套覆盖搬到了
# ``test_opencode_store.py``。


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
    # 两场各自落一份副本，用户自己敲起来的那场同样备到。
    assert _raw("ses_a") == [
        {"type": "text", "text": "ping"},
        {"type": "text", "text": "pong"},
    ]
    assert _raw("ses_b") == [
        {"type": "text", "text": "hi"},
        {"type": "text", "text": "hello"},
    ]


def test_resync_skips_every_session_and_keeps_line_counts(env: Path) -> None:
    """新逻辑的核心：备份文件在不在就是账本，第二遍全员 skipped、行数不变。"""
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

    first = opencode_sync.sync_opencode_sessions()
    assert (first.synced, first.updated, first.skipped) == (2, 0, 0)
    before = {sid: _raw(sid) for sid in ("ses_a", "ses_b")}

    # 库里一个字都没动：第二遍不该有任何一场落进 synced/updated。
    second = opencode_sync.sync_opencode_sessions()
    assert (second.synced, second.updated, second.skipped) == (0, 0, 2)
    assert second.errors == []
    assert {sid: _raw(sid) for sid in ("ses_a", "ses_b")} == before
