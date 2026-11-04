"""测试 ``frago session ask`` 单轮轻量模型会话内容提取。"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from frago.agent_driver.kernel_backend import KernelTurn
from frago.cli.session_commands import session_group
from frago.session.ask import (
    AskRecord,
    SessionAskAmbiguous,
    SessionAskNotFound,
    ask_session,
    clean_record_text,
    locate_session_file,
    parse_range_spec,
    redact_secrets,
    select_records_for_ask,
)


def _write_backup_session(root, sid: str, messages: list[tuple[str, str]], *, core: str = "claude"):
    path = root / core / sid / "raw.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": role,
                "timestamp": "2026-11-03T15:00:00Z",
                "message": {"role": role, "content": text},
            },
            ensure_ascii=False,
        )
        for role, text in messages
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestCleanAndRedact:
    def test_strips_employee_and_skill_and_system_reminder_blocks(self):
        raw = (
            '<frago-employee id="emp-1" title="分析师" kernel="claude">\n'
            "大段岗位注入内容\n"
            "</frago-employee>\n"
            '<must-use-skill name="demo">技能说明</must-use-skill>\n'
            "<system-reminder>系统提醒</system-reminder>\n"
            "真正的用户提问：查一下 32c0bb7a 的结论"
        )
        assert clean_record_text(raw) == "真正的用户提问：查一下 32c0bb7a 的结论"

    def test_redacts_uri_passwords_and_api_keys(self):
        raw = (
            "连接串 postgres://admin:MyS3cretPass!@db.internal:5432/prod "
            "与 key sk-abcdefghijklmnopqrstuvwxyz123456 "
            "以及 Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        )
        redacted = redact_secrets(raw)
        assert "MyS3cretPass!" not in redacted
        assert "postgres://admin:***@db.internal:5432/prod" in redacted
        assert "sk-***REDACTED***" in redacted
        assert "Bearer ***REDACTED***" in redacted


class TestLocateSession:
    def test_locates_by_exact_id_and_unique_prefix(self, tmp_path):
        sid = "32c0bb7a-51ca-43d8-a072-cc65c7dea3f4"
        expected = _write_backup_session(tmp_path, sid, [("user", "hello")])

        exact = locate_session_file(sid, root=tmp_path)
        assert exact == ("claude", sid, expected)

        prefix = locate_session_file("32c0bb7a", root=tmp_path)
        assert prefix == ("claude", sid, expected)

    def test_raises_ambiguous_when_prefix_matches_multiple_sessions(self, tmp_path):
        _write_backup_session(tmp_path, "32c0bb7a-1111-43d8-a072-cc65c7dea3f4", [("user", "a")])
        _write_backup_session(tmp_path, "32c0bb7a-2222-43d8-a072-cc65c7dea3f4", [("user", "b")])

        with pytest.raises(SessionAskAmbiguous) as exc_info:
            locate_session_file("32c0bb7a", root=tmp_path)
        assert "32c0bb7a-1111" in str(exc_info.value)
        assert "32c0bb7a-2222" in str(exc_info.value)


class TestRangeAndSelection:
    def test_parses_explicit_range_and_question_range(self):
        assert parse_range_spec("450:520") == (450, 520)
        assert parse_range_spec("520-450") == (450, 520)
        assert (
            parse_range_spec(None, "读取第 450 至 520 条记录中引用的 32c0bb7a 历史结论片段")
            == (450, 520)
        )

    def test_selects_records_by_question_range_and_grep(self):
        records = [
            AskRecord(seq=i, role="assistant", timestamp="", text=f"记录 {i} 普通内容")
            for i in range(1, 101)
        ]
        records[49] = AskRecord(
            seq=50, role="assistant", timestamp="", text="引用会话 32c0bb7a 的历史结论：通过验收"
        )

        by_q_range = select_records_for_ask(records, "第 48 至 52 条记录里说了什么")
        assert [r.seq for r in by_q_range] == [48, 49, 50, 51, 52]

        by_grep = select_records_for_ask(records, "结论是什么", grep="32c0bb7a")
        assert [r.seq for r in by_grep] == [48, 49, 50, 51, 52]


class TestAskSessionExecution:
    def test_invokes_run_chat_turn_with_lightagent_role(self, tmp_path, monkeypatch):
        sid = "32c0bb7a-51ca-43d8-a072-cc65c7dea3f4"
        _write_backup_session(
            tmp_path,
            sid,
            [
                ("user", "请排查数据库连接"),
                (
                    "assistant",
                    "最终结论：连接串 postgres://app:TopSecret99@10.0.0.1:5432/main 连接池耗尽",
                ),
            ],
        )
        captured: list[dict] = []

        def fake_chat_turn(prompt_text: str, **kwargs):
            captured.append({"prompt": prompt_text, **kwargs})
            return KernelTurn(
                text="[#2] 最终结论：postgres://app:***@10.0.0.1:5432/main 连接池耗尽",
                status="ok",
                duration_ms=420,
            )

        monkeypatch.setattr("frago.agent_driver.kernel_backend.run_chat_turn", fake_chat_turn)

        res = ask_session(
            "32c0bb7a",
            "提取最后一条结论记录（脱敏连接串）",
            tail=5,
            root=tmp_path,
        )
        assert res.answer_source == "lightagent"
        assert res.session_id == sid
        assert "连接池耗尽" in res.answer
        assert "TopSecret99" not in captured[0]["prompt"]
        assert captured[0]["role"] == "lightagent"

    def test_falls_back_to_redacted_records_when_kernel_fails(self, tmp_path, monkeypatch):
        sid = "a1d5f9f8-9959-4903-a800-f2c32966b934"
        _write_backup_session(
            tmp_path,
            sid,
            [
                ("user", "第 1 条"),
                ("assistant", "引用 32c0bb7a 的结论：密钥 sk-1234567890abcdefghij 已轮换"),
            ],
        )
        monkeypatch.setattr(
            "frago.agent_driver.kernel_backend.run_chat_turn",
            lambda prompt_text, **kw: KernelTurn(text="连接超时", status="timeout", duration_ms=100),
        )

        res = ask_session("a1d5f9f8", "32c0bb7a 的结论是什么", root=tmp_path)
        assert res.answer_source == "fallback"
        assert "轻量模型单轮提取返回 timeout" in res.note
        assert "32c0bb7a" in res.answer
        assert "sk-***REDACTED***" in res.answer

    def test_raises_not_found_for_unknown_session(self, tmp_path, monkeypatch):
        monkeypatch.setattr("frago.session.record_reader.list_sessions", lambda: [])
        with pytest.raises(SessionAskNotFound):
            ask_session("deadbeef", "随便问问", root=tmp_path)


class TestSessionAskCli:
    def test_cli_ask_json_output(self, tmp_path, monkeypatch):
        sid = "32c0bb7a-51ca-43d8-a072-cc65c7dea3f4"
        _write_backup_session(
            tmp_path,
            sid,
            [("user", "提问"), ("assistant", "结论：一切正常")],
        )
        monkeypatch.setattr("frago.session.ask.backup_root", lambda: tmp_path)
        monkeypatch.setattr(
            "frago.agent_driver.kernel_backend.run_chat_turn",
            lambda prompt_text, **kw: KernelTurn(
                text="[#2] 结论：一切正常", status="ok", duration_ms=120
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            session_group,
            ["ask", "32c0bb7a", "最后一条结论是什么", "--tail", "10", "--json"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["session_id"] == sid
        assert payload["answer_source"] == "lightagent"
        assert "一切正常" in payload["answer"]
