"""Unit tests for the Claude Code session scanner service.

断言契约本身：文本扁平化、块解析、human/agent 分类、recap 处理、时间窗解析、
JSONL 扫描与详情读取。所有文件 IO 走 tmp_path，NEVER 碰真实 ~/.claude/projects、
NEVER 起进程。直接调函数（模块级纯函数），不走任何单例。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from frago.session import claude_sessions as cs


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------
class TestExtractText:
    def test_plain_string_passthrough(self):
        assert cs._extract_text("hello") == "hello"

    def test_list_keeps_only_text_blocks_joined_by_space(self):
        content = [
            {"type": "text", "text": "a"},
            {"type": "thinking", "thinking": "ignored"},
            {"type": "text", "text": "b"},
            {"type": "tool_use", "name": "X"},
        ]
        assert cs._extract_text(content) == "a b"

    def test_unknown_type_returns_empty(self):
        assert cs._extract_text(42) == ""
        assert cs._extract_text(None) == ""

    def test_text_block_missing_text_defaults_empty(self):
        assert cs._extract_text([{"type": "text"}]) == ""


# ---------------------------------------------------------------------------
# _stringify_tool_result
# ---------------------------------------------------------------------------
class TestStringifyToolResult:
    def test_string_passthrough(self):
        assert cs._stringify_tool_result("out") == "out"

    def test_none_is_empty(self):
        assert cs._stringify_tool_result(None) == ""

    def test_list_joins_text_and_image_marker_with_newlines(self):
        content = [
            "raw",
            {"type": "text", "text": "t"},
            {"type": "image", "source": {}},
            {"type": "other"},
        ]
        assert cs._stringify_tool_result(content) == "raw\nt\n[image]"

    def test_non_str_non_list_stringified(self):
        assert cs._stringify_tool_result(123) == "123"


# ---------------------------------------------------------------------------
# _extract_blocks
# ---------------------------------------------------------------------------
class TestExtractBlocks:
    def test_string_content_becomes_single_text_block(self):
        assert cs._extract_blocks("hi") == [{"type": "text", "text": "hi"}]

    def test_blank_string_yields_no_blocks(self):
        assert cs._extract_blocks("   ") == []

    def test_non_list_non_str_returns_empty(self):
        assert cs._extract_blocks(7) == []

    def test_all_block_types_preserved(self):
        content = [
            "  ",  # blank raw string skipped
            "raw",
            {"type": "text", "text": "T"},
            {"type": "text", "text": ""},  # empty text dropped
            {"type": "thinking", "thinking": "TH"},
            {"type": "tool_use", "name": "Bash", "input": {"cmd": "ls"}, "id": "tid"},
            {"type": "tool_result", "content": "ok", "is_error": True, "tool_use_id": "tid"},
            {"type": "image"},
            {"type": "unknown"},  # ignored
            "skip-me-not-dict-still-counts-as-str",
        ]
        blocks = cs._extract_blocks(content)
        assert {"type": "text", "text": "raw"} in blocks
        assert {"type": "text", "text": "T"} in blocks
        assert {"type": "thinking", "text": "TH"} in blocks
        assert {
            "type": "tool_use",
            "name": "Bash",
            "tool_input": {"cmd": "ls"},
            "tool_id": "tid",
        } in blocks
        assert {
            "type": "tool_result",
            "content": "ok",
            "is_error": True,
            "tool_id": "tid",
        } in blocks
        assert {"type": "image"} in blocks
        # empty-text block must not appear
        assert {"type": "text", "text": ""} not in blocks


# ---------------------------------------------------------------------------
# _classify_human
# ---------------------------------------------------------------------------
class TestClassifyHuman:
    def test_slug_means_human(self):
        klass, reason = cs._classify_human("my-slug", "anything")
        assert klass == "human"
        assert "slug" in reason

    def test_no_user_message_is_agent(self):
        klass, reason = cs._classify_human(None, None)
        assert klass == "agent"
        assert "no user message" in reason

    @pytest.mark.parametrize(
        "text",
        [
            "你是 一个助手",
            "[Reflection Tick] something",
            "--- 待处理消息",
            "<command-name>/foo",
            "你的上一条输出格式错误",
        ],
    )
    def test_agent_templates_detected(self, text):
        klass, reason = cs._classify_human(None, text)
        assert klass == "agent"
        assert "agent template" in reason

    def test_unrecognized_first_message_is_maybe(self):
        klass, reason = cs._classify_human(None, "please refactor this code")
        assert klass == "maybe"

    def test_pattern_only_matched_within_first_200_chars(self):
        # Agent marker pushed past the 200-char window must NOT match.
        text = "x" * 201 + "你是 helper"
        klass, _ = cs._classify_human(None, text)
        assert klass == "maybe"


# ---------------------------------------------------------------------------
# _strip_recap_trailer
# ---------------------------------------------------------------------------
class TestStripRecapTrailer:
    def test_none_and_empty_passthrough(self):
        assert cs._strip_recap_trailer(None) is None
        assert cs._strip_recap_trailer("") == ""

    def test_trailer_removed_and_trimmed(self):
        text = "summary text\n\n(disable recaps in /config)"
        assert cs._strip_recap_trailer(text) == "summary text"

    def test_without_trailer_only_rstripped(self):
        assert cs._strip_recap_trailer("just text  ") == "just text"


# ---------------------------------------------------------------------------
# _iso_local
# ---------------------------------------------------------------------------
class TestIsoLocal:
    def test_none(self):
        assert cs._iso_local(None) is None

    def test_roundtrips_to_seconds_precision(self):
        ts = datetime(2026, 1, 2, 3, 4, 5).timestamp()
        out = cs._iso_local(ts)
        assert out is not None
        # parseable and points back to the same instant
        assert datetime.fromisoformat(out).timestamp() == pytest.approx(ts)


# ---------------------------------------------------------------------------
# _resolve_range
# ---------------------------------------------------------------------------
class TestResolveRange:
    def test_default_days_window(self):
        since, until = cs._resolve_range(None, None, None)
        assert until - since == pytest.approx(cs.DEFAULT_DAYS * 86400, abs=2)

    def test_explicit_days(self):
        since, until = cs._resolve_range(3, None, None)
        assert until - since == pytest.approx(3 * 86400, abs=2)

    def test_since_overrides_days(self):
        since, until = cs._resolve_range(99, "2026-01-01", "2026-01-02")
        assert since == datetime.fromisoformat("2026-01-01").timestamp()
        assert until == datetime.fromisoformat("2026-01-02").timestamp()


# ---------------------------------------------------------------------------
# helpers for file-level tests
# ---------------------------------------------------------------------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def _user(text: str, **extra) -> dict:
    return {"type": "user", "message": {"content": text}, **extra}


def _assistant(text: str, **extra) -> dict:
    return {"type": "assistant", "message": {"content": text}, **extra}


# ---------------------------------------------------------------------------
# _scan_file
# ---------------------------------------------------------------------------
class TestScanFile:
    def test_missing_file_returns_none(self, tmp_path):
        assert cs._scan_file(tmp_path / "nope.jsonl") is None

    def test_invalid_json_lines_skipped(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text("not json\n" + json.dumps(_user("hello")), encoding="utf-8")
        data = cs._scan_file(p)
        assert data is not None
        assert data["first_user"] == "hello"
        assert data["n_user"] == 1

    def test_full_field_extraction(self, tmp_path):
        p = tmp_path / "s.jsonl"
        records = [
            {"type": "custom-title", "customTitle": "My Title"},
            {"slug": "the-slug", "type": "user",
             "message": {"content": "real first prompt"}, "timestamp": "2026-01-01T00:00:00Z",
             "cwd": "/work", "gitBranch": "main"},
            {"type": "ai-title", "aiTitle": "first ai"},
            {"type": "ai-title", "aiTitle": "second ai"},  # last-write-wins
            {"type": "last-prompt", "lastPrompt": "last p"},
            {"type": "system", "subtype": "away_summary",
             "content": "recap body\n(disable recaps in /config)"},
            _assistant("assistant reply one"),
            _assistant("assistant reply two"),
        ]
        _write_jsonl(p, records)
        data = cs._scan_file(p)
        assert data["slug"] == "the-slug"
        assert data["custom_title"] == "My Title"
        assert data["ai_title"] == "second ai"
        assert data["last_prompt"] == "last p"
        assert data["recap"] == "recap body"
        assert data["first_user"] == "real first prompt"
        assert data["last_assistant"] == "assistant reply two"
        assert data["first_ts"] == "2026-01-01T00:00:00Z"
        assert data["cwd"] == "/work"
        assert data["branch"] == "main"
        assert data["n_user"] == 1
        assert data["n_assistant"] == 2

    def test_command_echo_skipped_for_first_user(self, tmp_path):
        p = tmp_path / "s.jsonl"
        _write_jsonl(p, [
            _user("<command-name>/clear"),
            _user("the real human prompt"),
        ])
        data = cs._scan_file(p)
        # both counted, but first_user picks the real prompt
        assert data["n_user"] == 2
        assert data["first_user"] == "the real human prompt"

    def test_meta_user_messages_not_counted(self, tmp_path):
        p = tmp_path / "s.jsonl"
        _write_jsonl(p, [
            _user("meta one", isMeta=True),
            _user("genuine"),
        ])
        data = cs._scan_file(p)
        assert data["n_user"] == 1
        assert data["first_user"] == "genuine"


# ---------------------------------------------------------------------------
# _load_sessions_index
# ---------------------------------------------------------------------------
class TestLoadSessionsIndex:
    def test_missing_file(self, tmp_path):
        assert cs._load_sessions_index(tmp_path) == {}

    def test_malformed_json(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text("{bad", encoding="utf-8")
        assert cs._load_sessions_index(tmp_path) == {}

    def test_indexes_by_session_id_skipping_missing_ids(self, tmp_path):
        (tmp_path / "sessions-index.json").write_text(
            json.dumps({"entries": [
                {"sessionId": "a", "summary": "sa"},
                {"summary": "no-id"},
                {"sessionId": "b", "firstPrompt": "fp"},
            ]}),
            encoding="utf-8",
        )
        idx = cs._load_sessions_index(tmp_path)
        assert set(idx) == {"a", "b"}
        assert idx["a"]["summary"] == "sa"


# ---------------------------------------------------------------------------
# scan_sessions
# ---------------------------------------------------------------------------
class TestScanSessions:
    def test_nonexistent_root_returns_empty_envelope(self, tmp_path):
        env = cs.scan_sessions(projects_root=tmp_path / "missing")
        assert env["sessions"] == []
        assert env["matched_sessions"] == 0
        assert env["scanned_files"] == 0

    def test_files_outside_window_skipped(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        old = proj / "old.jsonl"
        _write_jsonl(old, [_user("hi")])
        # set mtime far in the past (30 days)
        past = time.time() - 30 * 86400
        import os
        os.utime(old, (past, past))

        env = cs.scan_sessions(days=7, projects_root=tmp_path)
        assert env["scanned_files"] == 1
        assert env["matched_sessions"] == 0

    def test_classification_and_index_merge(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        # human session (has slug)
        _write_jsonl(proj / "human1.jsonl", [
            {"slug": "s", "type": "user", "message": {"content": "hello"},
             "timestamp": "2026-06-01T00:00:00Z"},
            _assistant("hi back"),
        ])
        # agent session (no slug, agent template)
        _write_jsonl(proj / "agent1.jsonl", [
            {"type": "user", "message": {"content": "你是 一个 agent"},
             "timestamp": "2026-06-02T00:00:00Z"},
        ])
        # index supplies recap fallback for the agent session
        (proj / "sessions-index.json").write_text(
            json.dumps({"entries": [
                {"sessionId": "agent1", "summary": "idx recap", "firstPrompt": "idx fp"},
            ]}),
            encoding="utf-8",
        )

        env = cs.scan_sessions(since="2026-01-01", until="2026-12-31", projects_root=tmp_path)
        assert env["matched_sessions"] == 2
        by_sid = {s["sid"]: s for s in env["sessions"]}

        h = by_sid["human1"]
        assert h["human"] == "human"
        assert h["name"] == "s"
        assert h["resume_command"] == "claude --resume human1"
        assert h["first_user_preview"] == "hello"
        assert h["project"] == "proj"

        a = by_sid["agent1"]
        assert a["human"] == "agent"
        assert a["recap"] == "idx recap"  # index fallback used
        assert a["last_prompt"] == "idx fp"

        # newest-first by first_interaction_ts (agent1 started later)
        assert env["sessions"][0]["sid"] == "agent1"


# ---------------------------------------------------------------------------
# _find_session_file
# ---------------------------------------------------------------------------
class TestFindSessionFile:
    def test_missing_root(self, tmp_path):
        assert cs._find_session_file("x", projects_root=tmp_path / "none") is None

    def test_found_across_project_dirs(self, tmp_path):
        proj = tmp_path / "p"
        proj.mkdir()
        target = proj / "sid123.jsonl"
        target.write_text("{}", encoding="utf-8")
        assert cs._find_session_file("sid123", projects_root=tmp_path) == target

    def test_not_found(self, tmp_path):
        (tmp_path / "p").mkdir()
        assert cs._find_session_file("nope", projects_root=tmp_path) is None


# ---------------------------------------------------------------------------
# read_session_messages
# ---------------------------------------------------------------------------
class TestReadSessionMessages:
    def test_unknown_session_returns_none(self, tmp_path):
        assert cs.read_session_messages("missing", projects_root=tmp_path) is None

    def test_streams_user_and_assistant_skipping_noise(self, tmp_path):
        proj = tmp_path / "p"
        proj.mkdir()
        _write_jsonl(proj / "sid.jsonl", [
            _user("first user", timestamp="t1"),
            {"type": "summary"},  # non message type skipped
            _assistant("an answer", timestamp="t2"),
            _user("meta", isMeta=True),  # meta skipped
            _user("   ", timestamp="t3"),  # blank -> no blocks -> skipped
        ])
        out = cs.read_session_messages("sid", projects_root=tmp_path)
        assert out is not None
        assert out["sid"] == "sid"
        assert out["total_messages"] == 2
        assert out["returned_messages"] == 2
        assert out["truncated"] is False
        assert [m["role"] for m in out["messages"]] == ["user", "assistant"]
        assert out["messages"][0]["text"] == "first user"
        assert out["resume_command"] == "claude --resume sid"

    def test_limit_keeps_most_recent_tail(self, tmp_path):
        proj = tmp_path / "p"
        proj.mkdir()
        records = [_user(f"m{i}") for i in range(5)]
        _write_jsonl(proj / "sid.jsonl", records)
        out = cs.read_session_messages("sid", limit=2, projects_root=tmp_path)
        assert out["total_messages"] == 5
        assert out["returned_messages"] == 2
        assert out["truncated"] is True
        assert [m["text"] for m in out["messages"]] == ["m3", "m4"]
