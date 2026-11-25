"""CLI tests for Top-4 (Option 4A): ``frago agent --json`` report offload fields
and ``frago session read <sid>`` deterministic lossless paginated reading.
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import frago.agent_driver as agent_driver_mod
from frago.agent_driver import kernel_backend
from frago.agent_driver.tmux_session import TurnResult
from frago.cli.agent_command import agent
from frago.cli.session_commands import session_group


def _encode_cwd(cwd: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", cwd)


def _seed_coreagent_session(home: Path, sid: str, blocks: list[str]) -> Path:
    proj = home / ".frago" / "coreagent" / "sessions" / _encode_cwd("/repo/demo")
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    rows: list[dict[str, Any]] = [
        {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": "u0",
            "type": "user",
            "timestamp": "2026-08-26T09:00:00.000Z",
            "cwd": "/repo/demo",
            "sessionId": sid,
            "message": {"role": "user", "content": "Prior prompt"},
        },
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
                "content": [{"type": "text", "text": "PRIOR_TURN_TEXT"}],
            },
        },
        {
            "parentUuid": None,
            "isSidechain": False,
            "uuid": "u1",
            "type": "user",
            "timestamp": "2026-08-26T10:00:00.000Z",
            "cwd": "/repo/demo",
            "sessionId": sid,
            "message": {"role": "user", "content": "Current prompt"},
        },
    ]
    for idx, text in enumerate(blocks, start=1):
        rows.append(
            {
                "parentUuid": None,
                "isSidechain": False,
                "uuid": f"a{idx}",
                "type": "assistant",
                "timestamp": f"2026-08-26T10:00:{10 + idx:02d}.000Z",
                "cwd": "/repo/demo",
                "sessionId": sid,
                "message": {
                    "id": f"msg_{idx}",
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
        )
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_agent_json_short_answer_has_backward_compatible_offload_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRAGO_HOME", str(home / ".frago"))

    class _FakeLauncher:
        def run(self, _prompt: str, **_kw: Any) -> TurnResult:
            return TurnResult(text="short ok", raw_delta="short ok", status="ok", duration_ms=101)

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)

    res = CliRunner().invoke(
        agent,
        [
            "--agent-type",
            "claude",
            "--session-id",
            "11111111-2222-3333-4444-555555555555",
            "--no-monitor",
            "--json",
            "--quiet",
            "ping",
        ],
    )
    assert res.exit_code == 0, res.stderr
    assert res.stderr == ""
    payload = json.loads(res.stdout)
    assert payload["status"] == "ok"
    assert payload["exit_code"] == 0
    assert payload["text"] == "short ok"
    assert payload["duration_ms"] == 101
    assert payload["total_chars"] == len("short ok")
    assert payload["truncated"] is False
    assert payload["report_file"] is None


def test_agent_json_long_output_offloads_readonly_report_tmux_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRAGO_HOME", str(home / ".frago"))

    long_body = "```python\n" + ("print('hello world')\n" * 45).rstrip("\n")
    assert len(long_body) > 600

    class _FakeLauncher:
        def run(self, _prompt: str, **_kw: Any) -> TurnResult:
            return TurnResult(text=long_body, raw_delta=long_body, status="ok", duration_ms=250)

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)

    res = CliRunner().invoke(
        agent,
        [
            "--agent-type",
            "claude",
            "--session-id",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "--no-monitor",
            "--json",
            "--quiet",
            "generate code",
        ],
    )
    assert res.exit_code == 0, res.stderr
    payload = json.loads(res.stdout)
    assert payload["status"] == "ok"
    assert payload["truncated"] is True
    assert payload["total_chars"] == len(long_body)
    assert payload["report_file"] is not None
    # Dangling code fence closed cleanly in bounded summary
    assert payload["text"].endswith("```")
    assert len(payload["text"]) <= 430

    report_path = Path(payload["report_file"])
    assert report_path.is_file()
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o444
    assert report_path.read_text(encoding="utf-8").rstrip("\n") == long_body


def test_agent_kernel_backend_extracts_multi_turn_interval_and_offloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRAGO_HOME", str(home / ".frago"))

    sid = "core_kernel_multi_01"
    part1 = "First investigation block: " + ("X" * 350)
    part2 = "Final conclusion block: " + ("Y" * 350)

    # Pre-seed an older turn on disk so baseline_seq isolates the resumed turn
    proj = home / ".frago" / "coreagent" / "sessions" / _encode_cwd("/repo/demo")
    proj.mkdir(parents=True, exist_ok=True)
    (proj / f"{sid}.jsonl").write_text(
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
                        "message": {"role": "user", "content": "Prior prompt"},
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
                            "content": [{"type": "text", "text": "PRIOR_TURN_TEXT"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_run_turn(prompt: str, **kwargs: Any) -> kernel_backend.KernelTurn:
        _seed_coreagent_session(home, kwargs["session_id"], [part1, part2])
        return kernel_backend.KernelTurn(
            text=part2,
            status="ok",
            duration_ms=333,
        )

    monkeypatch.setattr(kernel_backend, "run_turn", _fake_run_turn)

    res = CliRunner().invoke(
        agent,
        [
            "--agent-type",
            "coreagent",
            "--session-id",
            sid,
            "--json",
            "--quiet",
            "audit",
        ],
    )
    assert res.exit_code == 0, res.stderr
    payload = json.loads(res.stdout)
    expected_full = f"{part1}\n\n{part2}"
    assert payload["status"] == "ok"
    assert payload["session_id"] == sid
    assert payload["tmux_name"] is None
    assert payload["truncated"] is True
    assert payload["total_chars"] == len(expected_full)
    assert payload["report_file"] is not None

    report_text = Path(payload["report_file"]).read_text(encoding="utf-8").rstrip("\n")
    assert report_text == expected_full
    assert "PRIOR_TURN_TEXT" not in report_text


def test_session_read_cli_lossless_pagination_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FRAGO_HOME", str(home / ".frago"))

    sid = "core_read_cli_999"
    long_block = "LOSSY_CHECK_START_" + ("Z" * 1200) + "_LOSSY_CHECK_END"
    _seed_coreagent_session(home, sid, [long_block, "Second turn reply"])

    runner = CliRunner()

    # 1. Plain text lossless read via unique prefix (no 200-char truncation)
    res_plain = runner.invoke(session_group, ["read", "core_read_cli", "--latest-turn"])
    assert res_plain.exit_code == 0, res_plain.output
    assert "LOSSY_CHECK_START_" in res_plain.output
    assert "LOSSY_CHECK_END" in res_plain.output
    assert "Second turn reply" in res_plain.output
    assert "PRIOR_TURN_TEXT" not in res_plain.output

    # 2. JSON pagination across char offsets
    res_p1 = runner.invoke(
        session_group,
        ["read", sid, "--latest-turn", "--char-offset", "0", "--max-chars", "500", "--json"],
    )
    assert res_p1.exit_code == 0, res_p1.output
    d1 = json.loads(res_p1.output)
    assert d1["session_id"] == sid
    assert d1["family"] == "coreagent"
    assert d1["char_has_more"] is True
    assert d1["next_char_offset"] == 500
    assert len(d1["text"]) == 500

    # 3. Role conversation includes user prompt
    res_conv = runner.invoke(
        session_group,
        ["read", sid, "--role", "conversation", "--latest-turn", "--json"],
    )
    assert res_conv.exit_code == 0, res_conv.output
    d_conv = json.loads(res_conv.output)
    assert "Current prompt" in d_conv["text"]
    assert "PRIOR_TURN_TEXT" not in d_conv["text"]

    # 4. Zero-prior-setup error feedback for missing session
    res_missing = runner.invoke(session_group, ["read", "does-not-exist-sid"])
    assert res_missing.exit_code != 0
    assert "frago session list" in (res_missing.output + res_missing.stderr)
