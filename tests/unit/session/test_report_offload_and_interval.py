"""Top-4 (Option 4A) unit tests: 5-kernel task-interval extraction, managed read-only
report offload + 14-day TTL cleanup, async_dispatch compatibility, and lossless
paginated reading via ``record_reader``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from frago.session import agy_store, async_dispatch
from frago.session.report_offload import (
    DEFAULT_REPORT_OFFLOAD_CHARS,
    DEFAULT_REPORT_TTL_DAYS,
    SessionReadAmbiguous,
    SessionReadNotFound,
    cleanup_expired_reports,
    current_next_seq,
    extract_task_interval_report,
    read_session_messages,
    reports_dir,
    resolve_session_id,
    write_managed_report,
)

_OPENCODE_SCHEMA = """
CREATE TABLE session (
    id text PRIMARY KEY,
    directory text NOT NULL,
    title text NOT NULL DEFAULT '',
    parent_id text,
    time_created integer NOT NULL,
    time_updated integer NOT NULL DEFAULT 0
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
    time_updated integer NOT NULL DEFAULT 0,
    data text NOT NULL
);
CREATE TABLE session_message (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    type text NOT NULL,
    seq integer NOT NULL,
    time_created integer NOT NULL,
    data text NOT NULL
);
"""


def _encode_cwd(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _seed_claude_or_coreagent(
    base_sessions_dir: Path,
    sid: str,
    *,
    prior_turn: bool = True,
    mid_text: str = "Phase 1 findings: inspected auth & storage modules.",
    final_text: str = "Final conclusion: all checks passed.",
) -> Path:
    proj = base_sessions_dir / _encode_cwd("/repo/demo")
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"

    def _row(uid: str, rtype: str, ts: str, **extra: Any) -> dict[str, Any]:
        return {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": uid,
            "type": rtype,
            "timestamp": ts,
            "cwd": "/repo/demo",
            "sessionId": sid,
            **extra,
        }

    rows: list[dict[str, Any]] = []
    if prior_turn:
        rows.extend(
            [
                _row(
                    "u0",
                    "user",
                    "2026-08-26T09:00:00.000Z",
                    message={"role": "user", "content": "Old question"},
                ),
                _row(
                    "a0",
                    "assistant",
                    "2026-08-26T09:00:05.000Z",
                    message={
                        "id": "msg_0",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "OLD_TURN_OUTPUT"}],
                    },
                ),
            ]
        )

    rows.extend(
        [
            _row(
                "u1",
                "user",
                "2026-08-26T10:00:00.000Z",
                message={"role": "user", "content": "Run full audit"},
            ),
            _row(
                "a1",
                "assistant",
                "2026-08-26T10:00:05.000Z",
                message={
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "HIDDEN_THINKING_STEP"},
                        {"type": "text", "text": mid_text},
                        {
                            "type": "tool_use",
                            "id": "tu_1",
                            "name": "Bash",
                            "input": {"command": "pytest -q"},
                        },
                    ],
                },
            ),
            _row(
                "u2",
                "user",
                "2026-08-26T10:00:10.000Z",
                message={
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": "20 passed"}
                    ],
                },
            ),
            _row(
                "a2",
                "assistant",
                "2026-08-26T10:00:15.000Z",
                message={
                    "id": "msg_2",
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_text}],
                },
            ),
        ]
    )
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _seed_codex(
    codex_home: Path,
    sid: str,
    *,
    mid_text: str,
    final_text: str,
) -> Path:
    day = codex_home / "sessions" / "2026" / "08" / "26"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-26T10-00-00-{sid}.jsonl"
    rows = [
        {
            "timestamp": "2026-08-26T09:00:00.000Z",
            "type": "session_meta",
            "payload": {"session_id": sid, "id": sid, "cwd": "/repo/demo"},
        },
        {
            "timestamp": "2026-08-26T09:00:01.000Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "Old turn"},
        },
        {
            "timestamp": "2026-08-26T09:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "cx_old_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "OLD_TURN_OUTPUT"}],
            },
        },
        {
            "timestamp": "2026-08-26T10:00:00.000Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "Run full audit"},
        },
        {
            "timestamp": "2026-08-26T10:00:02.000Z",
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "HIDDEN_THINKING_STEP"}],
            },
        },
        {
            "timestamp": "2026-08-26T10:00:03.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "cx_mid_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": mid_text}],
            },
        },
        {
            "timestamp": "2026-08-26T10:00:04.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": '{"command":"pytest -q"}',
                "call_id": "call_1",
            },
        },
        {
            "timestamp": "2026-08-26T10:00:05.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "20 passed",
            },
        },
        {
            "timestamp": "2026-08-26T10:00:06.000Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "cx_final_1",
                "role": "assistant",
                "content": [{"type": "output_text", "text": final_text}],
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _seed_opencode(
    db_path: Path,
    sid: str,
    *,
    mid_text: str,
    final_text: str,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(_OPENCODE_SCHEMA)
    ts = 1_785_000_000_000
    conn.execute(
        "INSERT INTO session (id, directory, title, parent_id, time_created, time_updated) VALUES (?, '/repo/demo', 'Demo', NULL, ?, ?)",
        (sid, ts, ts + 100),
    )

    def _add_msg(mid: str, role: str, m_ts: int) -> None:
        conn.execute(
            "INSERT INTO message (id, session_id, time_created, data) VALUES (?, ?, ?, ?)",
            (mid, sid, m_ts, json.dumps({"role": role})),
        )

    def _add_part(pid: str, mid: str, p_ts: int, payload: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, mid, sid, p_ts, p_ts, json.dumps(payload)),
        )

    # Prior turn
    _add_msg("m0", "user", ts + 1)
    _add_part("p0", "m0", ts + 1, {"type": "text", "text": "Old turn"})
    _add_msg("m1", "assistant", ts + 2)
    _add_part("p1", "m1", ts + 2, {"type": "text", "text": "OLD_TURN_OUTPUT"})

    # Current multi-turn interval
    _add_msg("m2", "user", ts + 10)
    _add_part("p2", "m2", ts + 10, {"type": "text", "text": "Run full audit"})
    _add_msg("m3", "assistant", ts + 11)
    _add_part("p3", "m3", ts + 11, {"type": "reasoning", "text": "HIDDEN_THINKING_STEP"})
    _add_part("p4", "m3", ts + 12, {"type": "text", "text": mid_text})
    _add_part(
        "p5",
        "m3",
        ts + 13,
        {
            "type": "tool",
            "tool": "bash",
            "callID": "call_1",
            "state": {"status": "completed", "input": {"command": "pytest"}, "output": "20 passed"},
        },
    )
    _add_msg("m4", "assistant", ts + 14)
    _add_part("p6", "m4", ts + 14, {"type": "text", "text": final_text})
    conn.commit()
    conn.close()


def _seed_agy(
    sid: str,
    *,
    mid_text: str,
    final_text: str,
) -> Path:
    path = agy_store.transcript_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "step_index": 0,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-08-26T09:00:00Z",
            "content": "<USER_REQUEST>\nOld turn\n</USER_REQUEST>",
        },
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-08-26T09:00:05Z",
            "content": "OLD_TURN_OUTPUT",
        },
        {
            "step_index": 2,
            "source": "USER_EXPLICIT",
            "type": "USER_INPUT",
            "status": "DONE",
            "created_at": "2026-08-26T10:00:00Z",
            "content": "<USER_REQUEST>\nRun full audit\n</USER_REQUEST>",
        },
        {
            "step_index": 3,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-08-26T10:00:05Z",
            "thinking": "HIDDEN_THINKING_STEP",
            "content": mid_text,
            "tool_calls": [{"id": "tc_1", "name": "run_command", "arguments_json": "{}"}],
        },
        {
            "step_index": 4,
            "source": "TOOL",
            "type": "TOOL_RESULT",
            "status": "DONE",
            "created_at": "2026-08-26T10:00:07Z",
            "content": "20 passed",
        },
        {
            "step_index": 5,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": "2026-08-26T10:00:10Z",
            "content": final_text,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def isolated_five_kernels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from frago.session import claude_sessions, session_index, session_origin, transcript_completion

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRAGO_HOME", str(home / ".frago"))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setenv("FRAGO_OPENCODE_DB", str(tmp_path / "opencode.db"))
    monkeypatch.setenv("FRAGO_AGY_APP_DIR", str(tmp_path / "agy-app"))

    claude_projects = home / ".claude" / "projects"
    monkeypatch.setattr(claude_sessions, "CLAUDE_PROJECTS_DIR", claude_projects)
    monkeypatch.setattr(session_index, "CLAUDE_PROJECTS_DIR", claude_projects)
    monkeypatch.setattr(session_origin, "CLAUDE_PROJECTS_DIR", claude_projects)
    monkeypatch.setattr(transcript_completion, "CLAUDE_PROJECTS_DIR", claude_projects)
    monkeypatch.setattr(session_index, "CACHE_FILE", home / ".frago" / "cache-cc.json")
    monkeypatch.setattr(session_index, "COREAGENT_CACHE_FILE", home / ".frago" / "cache-core.json")

    mid_text = "Section A — multi-turn root-cause findings: " + ("A" * 380)
    final_text = "Section B — final verification summary: " + ("B" * 380)

    cc_sid = "11111111-1111-4111-8111-111111111111"
    _seed_claude_or_coreagent(
        home / ".claude" / "projects", cc_sid, mid_text=mid_text, final_text=final_text
    )

    core_sid = "core_222222222222"
    _seed_claude_or_coreagent(
        home / ".frago" / "coreagent" / "sessions",
        core_sid,
        mid_text=mid_text,
        final_text=final_text,
    )

    codex_sid = "33333333-3333-7333-8333-333333333333"
    _seed_codex(home / ".codex", codex_sid, mid_text=mid_text, final_text=final_text)

    oc_sid = "ses_444444444444"
    _seed_opencode(tmp_path / "opencode.db", oc_sid, mid_text=mid_text, final_text=final_text)

    agy_sid = "55555555-5555-4555-8555-555555555555"
    _seed_agy(agy_sid, mid_text=mid_text, final_text=final_text)

    return {
        "home": home,
        "frago_home": home / ".frago",
        "mid_text": mid_text,
        "final_text": final_text,
        "sessions": {
            "claude-code": cc_sid,
            "coreagent": core_sid,
            "codex": codex_sid,
            "opencode": oc_sid,
            "agy": agy_sid,
        },
    }


@pytest.mark.parametrize("family", ["claude-code", "coreagent", "codex", "opencode", "agy"])
def test_extract_task_interval_report_consistent_across_five_kernels(
    isolated_five_kernels: dict[str, Any],
    family: str,
) -> None:
    """All 5 kernels extract every substantive assistant block in the current task interval,
    excluding prior-turn text and hidden thinking, and offload full text to a 0o444 file.
    """
    sid = isolated_five_kernels["sessions"][family]
    mid_text = isolated_five_kernels["mid_text"]
    final_text = isolated_five_kernels["final_text"]

    report = extract_task_interval_report(
        sid,
        fallback_text=final_text,
        threshold=DEFAULT_REPORT_OFFLOAD_CHARS,
        offload=True,
    )

    assert report.family == family
    assert report.block_count == 2
    assert mid_text in report.full_text
    assert final_text in report.full_text
    assert "OLD_TURN_OUTPUT" not in report.full_text
    assert "HIDDEN_THINKING_STEP" not in report.full_text
    assert report.total_chars == len(report.full_text)
    assert report.truncated is True
    assert report.offloaded is True
    assert report.report_file is not None

    report_path = Path(report.report_file)
    assert report_path.is_file()
    assert report_path.parent == isolated_five_kernels["frago_home"] / "dispatches" / "reports"
    assert stat.S_IMODE(report_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o444
    assert report_path.read_text(encoding="utf-8").rstrip("\n") == report.full_text


def test_baseline_seq_prevents_leaking_previous_turns(
    isolated_five_kernels: dict[str, Any],
) -> None:
    """Capturing ``current_next_seq`` before a new turn isolates that turn's blocks only."""
    home = isolated_five_kernels["home"]
    sid = "core_baseline_test"
    path = _seed_claude_or_coreagent(
        home / ".frago" / "coreagent" / "sessions",
        sid,
        prior_turn=True,
        mid_text="Turn 2 first segment",
        final_text="Turn 2 second segment",
    )
    baseline = current_next_seq(sid)
    assert baseline is not None and baseline > 0

    # Append a new Turn 3 to the transcript
    extra_rows = [
        {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": "u3",
            "type": "user",
            "timestamp": "2026-08-26T11:00:00.000Z",
            "cwd": "/repo/demo",
            "sessionId": sid,
            "message": {"role": "user", "content": "Turn 3"},
        },
        {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": "a3",
            "type": "assistant",
            "timestamp": "2026-08-26T11:00:05.000Z",
            "cwd": "/repo/demo",
            "sessionId": sid,
            "message": {
                "id": "msg_3",
                "role": "assistant",
                "content": [{"type": "text", "text": "Turn 3 part A"}],
            },
        },
        {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": "a4",
            "type": "assistant",
            "timestamp": "2026-08-26T11:00:10.000Z",
            "cwd": "/repo/demo",
            "sessionId": sid,
            "message": {
                "id": "msg_4",
                "role": "assistant",
                "content": [{"type": "text", "text": "Turn 3 part B"}],
            },
        },
    ]
    with path.open("a", encoding="utf-8") as fh:
        for row in extra_rows:
            fh.write(json.dumps(row) + "\n")

    report = extract_task_interval_report(sid, baseline_seq=baseline, offload=True)
    assert report.full_text == "Turn 3 part A\n\nTurn 3 part B"
    assert "Turn 2" not in report.full_text
    assert "OLD_TURN_OUTPUT" not in report.full_text
    # Multiple blocks (< 600 chars) still offload full report without truncating summary
    assert report.truncated is False
    assert report.offloaded is True
    assert report.report_file is not None


def test_short_single_block_does_not_offload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "clean_home"))
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path / "clean_home" / ".frago"))
    report = extract_task_interval_report(
        "nonexistent-sid",
        fallback_text="short answer",
        offload=True,
    )
    assert report.full_text == "short answer"
    assert report.summary_text == "short answer"
    assert report.total_chars == len("short answer")
    assert report.truncated is False
    assert report.offloaded is False
    assert report.report_file is None


def test_managed_report_ttl_14_day_cleanup_handles_readonly_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero-prior-setup directory creation + automatic 14-day TTL cleanup of 0o444 reports."""
    monkeypatch.setenv("HOME", str(tmp_path / "zero_home"))
    monkeypatch.setenv("FRAGO_HOME", str(tmp_path / "zero_home" / ".frago"))

    rdir = reports_dir()
    assert rdir.is_dir()
    assert stat.S_IMODE(rdir.stat().st_mode) == 0o700

    old_file = write_managed_report("expired content", session_id="sid-old", job_id="disp-1")
    fresh_file = write_managed_report("fresh content", session_id="sid-new", job_id="disp-2")

    assert stat.S_IMODE(old_file.stat().st_mode) == 0o444
    now = time.time()
    old_mtime = now - (DEFAULT_REPORT_TTL_DAYS + 1) * 86400.0
    os.utime(old_file, (old_mtime, old_mtime))

    removed = cleanup_expired_reports(ttl_days=DEFAULT_REPORT_TTL_DAYS, now_s=now)
    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()


@pytest.mark.parametrize("family", ["claude-code", "coreagent", "codex", "opencode", "agy"])
def test_read_session_messages_lossless_pagination_across_five_kernels(
    isolated_five_kernels: dict[str, Any],
    family: str,
) -> None:
    """``read_session_messages`` returns lossless original text across all 5 kernels
    with prefix matching, role filtering, latest-turn scoping, and char pagination.
    """
    full_sid = isolated_five_kernels["sessions"][family]
    prefix = full_sid[:10]
    assert resolve_session_id(prefix) == (full_sid, family)

    page_all = read_session_messages(prefix, role="assistant", offset=0, limit=10)
    assert page_all.session_id == full_sid
    assert page_all.family == family
    assert page_all.total_items == 3  # OLD_TURN_OUTPUT + mid_text + final_text
    assert "OLD_TURN_OUTPUT" in page_all.text
    assert isolated_five_kernels["mid_text"] in page_all.text
    assert isolated_five_kernels["final_text"] in page_all.text
    assert "..." not in page_all.text  # no 200-char truncation

    # Latest turn excludes prior turn
    page_turn = read_session_messages(full_sid, role="assistant", latest_turn=True)
    assert page_turn.total_items == 2
    assert "OLD_TURN_OUTPUT" not in page_turn.text
    assert isolated_five_kernels["mid_text"] in page_turn.text
    assert isolated_five_kernels["final_text"] in page_turn.text

    # Deterministic character pagination reconstructs exact full text
    p1 = read_session_messages(full_sid, role="assistant", latest_turn=True, char_offset=0, max_chars=250)
    assert p1.char_has_more is True
    assert p1.next_char_offset == 250
    chunks = [p1.text]
    cursor = p1.next_char_offset
    while cursor is not None:
        nxt = read_session_messages(
            full_sid, role="assistant", latest_turn=True, char_offset=cursor, max_chars=250
        )
        chunks.append(nxt.text)
        cursor = nxt.next_char_offset
    assert "".join(chunks) == page_turn.text


def test_resolve_session_id_errors(isolated_five_kernels: dict[str, Any]) -> None:
    with pytest.raises(SessionReadNotFound):
        resolve_session_id("nonexistent_session_xyz")

    home = isolated_five_kernels["home"]
    _seed_claude_or_coreagent(
        home / ".frago" / "coreagent" / "sessions",
        "core_ambig_111",
    )
    _seed_claude_or_coreagent(
        home / ".frago" / "coreagent" / "sessions",
        "core_ambig_222",
    )
    with pytest.raises(SessionReadAmbiguous):
        resolve_session_id("core_ambig_")


def test_async_dispatch_job_extracts_full_interval_and_preserves_callback_contract(
    isolated_five_kernels: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``execute_dispatch_job`` extracts full multi-turn assistant output, writes a
    0o444 report file, preserves legacy callback parsing markers, and passes round-trip.
    """
    home = isolated_five_kernels["home"]
    sid = "core_dispatch_multi_01"
    mid_text = isolated_five_kernels["mid_text"]
    final_text = isolated_five_kernels["final_text"]

    # Seed initial pre-existing turn before dispatch runs
    proj = home / ".frago" / "coreagent" / "sessions" / _encode_cwd("/repo/demo")
    proj.mkdir(parents=True, exist_ok=True)
    transcript_path = proj / f"{sid}.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "parentUuid": None,
                        "isSidechain": False,
                        "uuid": "u0",
                        "type": "user",
                        "timestamp": "2026-08-26T09:00:00.000Z",
                        "cwd": "/repo/demo",
                        "sessionId": sid,
                        "message": {"role": "user", "content": "Old task"},
                    }
                ),
                json.dumps(
                    {
                        "parentUuid": None,
                        "isSidechain": False,
                        "uuid": "a0",
                        "type": "assistant",
                        "timestamp": "2026-08-26T09:00:05.000Z",
                        "cwd": "/repo/demo",
                        "sessionId": sid,
                        "message": {
                            "id": "msg_0",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "PRIOR_TURN_OUTPUT"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    job = async_dispatch.AsyncDispatchJob(
        job_id="disp-top4-multi",
        kind="worker",
        mode="resume",
        caller_session_id="emp-caller-001",
        caller_employee_id="emp_main",
        caller_cwd="/repo/demo",
        target_session_id=sid,
        target_name=sid,
        employee_id=None,
        agent="coreagent",
        cwd="/repo/demo",
        prompt="Run full audit",
        task_summary="Run full audit",
        resume=sid,
        status="pending",
    )
    job_path = async_dispatch.save_dispatch_job(job)

    def _fake_execute_worker(_j: async_dispatch.AsyncDispatchJob) -> tuple[int, str, str]:
        _seed_claude_or_coreagent(
            home / ".frago" / "coreagent" / "sessions",
            sid,
            prior_turn=True,
            mid_text=mid_text,
            final_text=final_text,
        )
        return 0, final_text, ""

    monkeypatch.setattr(async_dispatch, "_execute_worker_job", _fake_execute_worker)
    monkeypatch.setattr(
        async_dispatch,
        "wait_for_pending_child_dispatches",
        lambda *_a, **_kw: None,
    )
    delivered_prompts: list[str] = []
    monkeypatch.setattr(
        async_dispatch,
        "deliver_callback_to_session",
        lambda _caller, prompt, **_kw: delivered_prompts.append(prompt) or True,
    )

    finished = async_dispatch.execute_dispatch_job(job_path)
    assert finished is not None
    assert finished.status == "completed"
    assert finished.report_file is not None
    assert finished.report_truncated is True
    assert mid_text in finished.output
    assert final_text in finished.output
    assert finished.report_total_chars == len(finished.output)

    report_path = Path(finished.report_file)
    assert report_path.is_file()
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o444
    assert report_path.read_text(encoding="utf-8").rstrip("\n") == finished.output

    # Verify serialization round-trip and callback prompt backward compatibility
    reloaded = async_dispatch.AsyncDispatchJob.from_dict(finished.to_dict())
    assert reloaded.report_file == finished.report_file
    assert reloaded.report_total_chars == finished.report_total_chars
    assert reloaded.report_truncated is True

    assert len(delivered_prompts) == 1
    prompt = delivered_prompts[0]
    # Matches asyncCallbackBlocks.ts SUMMARY_BLOCK_RE & RESULT_SECTION_RE boundaries
    assert "- 执行状态：`completed` (exit_code=0)" in prompt
    assert f"- 交付报告：`{finished.report_file}`" in prompt
    assert "### Worker 交付结果" in prompt
    assert "此处省略 " in prompt
    assert f"frago session read {sid}" in prompt
    assert f"frago session ask {sid}" in prompt
    assert "落盘的交付报告" in prompt
