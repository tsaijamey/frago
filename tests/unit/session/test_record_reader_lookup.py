"""O(1) 单场工作目录定位与实时变更指纹单元测试（Top-5 · 方案 5A）。"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from frago.session import agy_store, opencode_store, record_reader


def _no_list_sessions(*_a, **_kw):
    raise AssertionError("list_sessions() must never be called during O(1) lookup")


def test_get_session_directory_prefers_ontology_cwd(monkeypatch):
    """本体唯一真源 cwd 非空时优先返回，不触发家族扫盘与 list_sessions()。"""
    fake_service = SimpleNamespace(
        get_session=lambda sid: SimpleNamespace(cwd="/onto/proj") if sid == "ses_123" else None
    )
    monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: fake_service)
    monkeypatch.setattr(record_reader, "list_sessions", _no_list_sessions)
    monkeypatch.setattr(
        record_reader,
        "detect_family",
        lambda _sid: (_ for _ in ()).throw(AssertionError("should not detect_family when ontology has cwd")),
    )

    assert record_reader.get_session_directory("ses_123") == "/onto/proj"


def test_get_session_directory_falls_back_per_family_without_list_sessions(tmp_path, monkeypatch):
    """本体无记录或 cwd 为空时，按家族走单场 O(1) 定位，绝不调用 list_sessions()。"""
    fake_service = SimpleNamespace(get_session=lambda _sid: None)
    monkeypatch.setattr("frago.session.service.get_default_session_service", lambda: fake_service)
    monkeypatch.setattr(record_reader, "list_sessions", _no_list_sessions)

    # 1. claude-code JSONL 头部 cwd
    cc_sid = "11111111-1111-1111-1111-111111111111"
    cc_file = tmp_path / f"{cc_sid}.jsonl"
    cc_file.write_text(json.dumps({"type": "user", "cwd": "/cc/proj"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude-code")
    monkeypatch.setattr(record_reader.claude_code_records, "find_session_file", lambda _sid: cc_file)
    assert record_reader.get_session_directory(cc_sid) == "/cc/proj"

    # 2. coreagent JSONL 头部 cwd
    core_file = tmp_path / "core.jsonl"
    core_file.write_text(json.dumps({"cwd": "/core/proj"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "coreagent")
    monkeypatch.setattr(record_reader.coreagent_store, "find_session_file", lambda _sid: core_file)
    assert record_reader.get_session_directory("core_abc") == "/core/proj"

    # 3. codex session_meta / bound_directory
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "codex")
    monkeypatch.setattr(
        record_reader.codex_store,
        "session_meta",
        lambda _sid: SimpleNamespace(cwd="/codex/proj"),
    )
    assert record_reader.get_session_directory("codex_abc") == "/codex/proj"

    # 4. opencode session_directory
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "opencode")
    monkeypatch.setattr(opencode_store, "session_directory", lambda _sid: "/oc/proj")
    assert record_reader.get_session_directory("ses_abc") == "/oc/proj"

    # 5. agy session_directory
    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "agy")
    monkeypatch.setattr(agy_store, "session_directory", lambda _sid: "/agy/proj")
    assert record_reader.get_session_directory("agy_abc") == "/agy/proj"

    # 6. 未知家族返回 None
    def _unknown(_sid):
        raise record_reader.UnknownSessionFamily("unknown")

    monkeypatch.setattr(record_reader, "detect_family", _unknown)
    assert record_reader.get_session_directory("nope") is None


def test_agy_session_directory_queries_single_row_without_list_conversations(tmp_path, monkeypatch):
    """agy_store.session_directory 直接按主键查 conversation_summaries，不扫全量 list_conversations()。"""
    app_dir = tmp_path / "agy-app"
    app_dir.mkdir()
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(app_dir))
    monkeypatch.setattr(agy_store, "BINDINGS_PATH", tmp_path / "agy-sessions.json")
    monkeypatch.setattr(
        agy_store,
        "list_conversations",
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("list_conversations must not be called")),
    )

    db_path = app_dir / "conversation_summaries.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE conversation_summaries "
            "(conversation_id text PRIMARY KEY, workspace_uris text)"
        )
        conn.execute(
            "INSERT INTO conversation_summaries (conversation_id, workspace_uris) VALUES (?, ?)",
            ("conv-1", json.dumps(["file:///agy/ws"])),
        )
        conn.execute(
            "INSERT INTO conversation_summaries (conversation_id, workspace_uris) VALUES (?, ?)",
            ("conv-empty", "[]"),
        )
        conn.commit()
    finally:
        conn.close()

    assert agy_store.session_directory("conv-1") == "/agy/ws"

    # 摘要库无工作区时回退认领账本 bound_directory
    (tmp_path / "agy-sessions.json").write_text(
        json.dumps({"frago-1": {"agy_conversation_id": "conv-empty", "directory": "/bound/ws"}}),
        encoding="utf-8",
    )
    assert agy_store.session_directory("conv-empty") == "/bound/ws"
    assert agy_store.session_directory("conv-missing") is None


def test_opencode_session_fingerprint_detects_v2_and_legacy_updates(tmp_path, monkeypatch):
    """opencode_store.session_fingerprint 在 v2 与 legacy 两套表上均能实时感知变更。"""
    db_path = tmp_path / "opencode.db"
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE session_v2 (
                id text PRIMARY KEY, directory text NOT NULL,
                title text NOT NULL DEFAULT '', time_created integer NOT NULL, time_updated integer NOT NULL
            );
            CREATE TABLE session_message (
                id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL,
                seq integer NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
            );
            CREATE TABLE session (
                id text PRIMARY KEY, directory text NOT NULL,
                title text NOT NULL DEFAULT '', time_created integer NOT NULL, time_updated integer NOT NULL
            );
            CREATE TABLE message (
                id text PRIMARY KEY, session_id text NOT NULL, time_created integer NOT NULL, data text NOT NULL
            );
            CREATE TABLE part (
                id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL,
                time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO session_v2 VALUES ('ses_v2', '/p', '', 100, 100)"
        )
        conn.execute(
            "INSERT INTO session_message VALUES ('m1', 'ses_v2', 'assistant', 1, 100, 100, '{}')"
        )
        conn.execute(
            "INSERT INTO session VALUES ('ses_leg', '/p', '', 100, 100)"
        )
        conn.execute(
            "INSERT INTO part VALUES ('p1', 'm_leg', 'ses_leg', 100, 100, '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    fp_v2_1 = opencode_store.session_fingerprint("ses_v2")
    fp_leg_1 = opencode_store.session_fingerprint("ses_leg")
    assert fp_v2_1 is not None
    assert fp_leg_1 is not None
    assert opencode_store.session_fingerprint("ses_none") is None

    # 更新消息/片段后指纹必须立刻变化
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE session_message SET time_updated = 200 WHERE id = 'm1'")
        conn.execute("INSERT INTO part VALUES ('p2', 'm_leg', 'ses_leg', 200, 200, '{}')")
        conn.commit()
    finally:
        conn.close()

    fp_v2_2 = opencode_store.session_fingerprint("ses_v2")
    fp_leg_2 = opencode_store.session_fingerprint("ses_leg")
    assert fp_v2_2 != fp_v2_1
    assert fp_leg_2 != fp_leg_1


def test_transcript_fingerprint_tracks_disk_changes(tmp_path, monkeypatch):
    """transcript_fingerprint 实时反映落盘转录的变更（写追加后指纹立即不同）。"""
    cc_file = tmp_path / "cc.jsonl"
    cc_file.write_text('{"seq": 1}\n', encoding="utf-8")

    monkeypatch.setattr(record_reader, "detect_family", lambda _sid: "claude-code")
    monkeypatch.setattr(record_reader.claude_code_records, "find_session_file", lambda _sid: cc_file)

    fp1 = record_reader.transcript_fingerprint("11111111-1111-1111-1111-111111111111")
    assert fp1 is not None

    with cc_file.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2}\n')

    fp2 = record_reader.transcript_fingerprint("11111111-1111-1111-1111-111111111111")
    assert fp2 is not None
    assert fp2 != fp1
