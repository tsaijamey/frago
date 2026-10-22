"""「我是谁」的解析规则（frago session self）。

盯三件事：自己报的 id 压过继承来的声明；没有声明时只肯给一个标着「推断」的结果；
连推断的依据都没有时老老实实说不知道——NEVER 编一个会话 id 出来。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from click.testing import CliRunner

from frago.cli.agent_command import agent
from frago.cli.session_commands import session_group
from frago.session.monitor import encode_project_path
from frago.session.self_id import resolve_self, resolve_self_agent


def _transcript(root: Path, cwd: str, sid: str, age_s: float = 0.0) -> Path:
    proj = root / encode_project_path(cwd)
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


def test_own_id_beats_the_inherited_declaration(tmp_path):
    """子进程会把上家的 `FRAGO_SESSION_ID` 原样带下来，那不是它自己。

    2026-10-15 实测：一场 Claude Code 会话是从 coreagent 的命令里起来的，继承了那场的
    编号，于是它派出去的 worker 全被记到了那场名下。Claude Code 给自己这个进程注入的
    `CLAUDE_CODE_SESSION_ID` 才是它自己的编号。
    """
    found = resolve_self(
        cwd="/work/repo",
        projects_root=tmp_path,
        env={"FRAGO_SESSION_ID": "inherited", "CLAUDE_CODE_SESSION_ID": "claude-one"},
    )
    assert found is not None
    assert found.session_id == "claude-one"
    assert found.source == "env:CLAUDE_CODE_SESSION_ID"
    assert found.certain is True


def test_agy_own_id_beats_the_inherited_declaration(tmp_path):
    """WebUI 新建的 agy 会话不注入 `FRAGO_SESSION_ID`（或从上家继承了旧值），
    靠 agy 自身往工具环境注入的 `ANTIGRAVITY_CONVERSATION_ID` 认出自己并压过继承值。
    """
    found = resolve_self(
        cwd="/work/repo",
        projects_root=tmp_path,
        env={"FRAGO_SESSION_ID": "inherited", "ANTIGRAVITY_CONVERSATION_ID": "agy-one"},
    )
    assert found is not None
    assert found.session_id == "agy-one"
    assert found.source == "env:ANTIGRAVITY_CONVERSATION_ID"
    assert found.certain is True


def test_claude_env_is_matched_with_its_transcript(tmp_path):
    path = _transcript(tmp_path, "/work/repo", "claude-one")
    found = resolve_self(
        cwd="/work/repo",
        projects_root=tmp_path,
        env={"CLAUDE_CODE_SESSION_ID": "claude-one"},
    )
    assert found is not None
    assert found.session_id == "claude-one"
    assert found.certain is True
    assert found.agent == "claude"
    assert found.transcript == str(path)
    assert found.resume_command == "claude --resume claude-one"


def test_declared_id_without_transcript_still_reported(tmp_path):
    found = resolve_self(cwd="/work/repo", projects_root=tmp_path, env={"FRAGO_SESSION_ID": "x"})
    assert found is not None
    assert found.session_id == "x"
    assert found.transcript is None
    assert found.agent == "unknown"
    assert found.note  # 说明记录没找到，但 id 本身仍算数


def test_fallback_picks_freshest_and_admits_it_is_a_guess(tmp_path):
    _transcript(tmp_path, "/work/repo", "older", age_s=120)
    _transcript(tmp_path, "/work/repo", "newest")
    found = resolve_self(cwd="/work/repo", projects_root=tmp_path, env={})
    assert found is not None
    assert found.session_id == "newest"
    assert found.source == "transcript-mtime"
    assert found.certain is False
    # 同一目录下还有一份同样新鲜的记录，note 必须把「可能挑错」说出来
    assert "可能挑错" in (found.note or "")


def test_stale_transcripts_are_not_this_session(tmp_path):
    _transcript(tmp_path, "/work/repo", "yesterday", age_s=86400)
    assert resolve_self(cwd="/work/repo", projects_root=tmp_path, env={}) is None


def test_no_evidence_at_all_returns_none(tmp_path):
    assert resolve_self(cwd="/work/elsewhere", projects_root=tmp_path, env={}) is None


def test_resolve_self_agent_by_env_for_each_cli_agent(tmp_path):
    cases = [
        (
            {"CLAUDE_CODE_SESSION_ID": "claude-sid"},
            "claude",
            "Claude Code",
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
            "claude-sid",
        ),
        (
            {"CODEX_THREAD_ID": "codex-tid"},
            "codex",
            "Codex CLI",
            "🤖 Generated with [Codex CLI](https://github.com/openai/codex)",
            "codex-tid",
        ),
        (
            {"OPENCODE_SESSION_ID": "ses_123"},
            "opencode",
            "opencode",
            "🤖 Generated with [opencode](https://opencode.ai)",
            "ses_123",
        ),
        (
            {"ANTIGRAVITY_CONVERSATION_ID": "agy-cid"},
            "agy",
            "Antigravity CLI",
            "🤖 Generated with [Antigravity CLI](https://antigravity.google)",
            "agy-cid",
        ),
        (
            {"FRAGO_SESSION_ID": "core_abc"},
            "coreagent",
            "CoreAgent",
            "🤖 Generated with [CoreAgent](https://frago.ai)",
            "core_abc",
        ),
    ]
    for env, expected_type, expected_name, expected_sig, expected_sid in cases:
        found = resolve_self_agent(cwd="/work/elsewhere", projects_root=tmp_path, env=env)
        assert found is not None
        assert found.agent_type == expected_type
        assert found.display_name == expected_name
        assert found.generated_with == expected_sig
        assert found.session_id == expected_sid


def test_resolve_self_agent_process_chain_beats_leaked_outer_env(tmp_path):
    """子 tmux 窗格里跑着 codex，即使环境里残留了外层 agy 的变量，也按最近祖先进程认 codex。"""
    found = resolve_self_agent(
        cwd="/work/elsewhere",
        projects_root=tmp_path,
        env={"ANTIGRAVITY_CONVERSATION_ID": "outer-agy-session", "CODEX_THREAD_ID": "inner-codex"},
        process_chain=[
            ("/bin/zsh", "/bin/zsh -c frago agent self"),
            ("/opt/homebrew/bin/codex", "codex --dangerously-bypass-approvals-and-sandbox"),
            ("/opt/homebrew/bin/tmux", "tmux new-session -d"),
            ("agy", "agy --dangerously-skip-permissions"),
        ],
    )
    assert found is not None
    assert found.agent_type == "codex"
    assert found.source == "process:codex"
    assert found.session_id == "inner-codex"
    assert found.generated_with == "🤖 Generated with [Codex CLI](https://github.com/openai/codex)"


def test_resolve_self_agent_stops_at_tmux_boundary(tmp_path):
    """越过 tmux server 的上层进程不能当成当前窗格的 CLI Agent。"""
    found = resolve_self_agent(
        cwd="/work/elsewhere",
        projects_root=tmp_path,
        env={},
        process_chain=[
            ("/bin/zsh", "-zsh"),
            ("/opt/homebrew/bin/tmux", "tmux"),
            ("agy", "agy --dangerously-skip-permissions"),
        ],
    )
    assert found is None


def test_agent_self_cli_outputs_type_signature_and_json(monkeypatch):
    monkeypatch.setenv("FRAGO_CLI_AGENT", "opencode")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_demo")
    runner = CliRunner()

    res_type = runner.invoke(agent, ["self"])
    assert res_type.exit_code == 0
    assert res_type.output.strip() == "opencode"

    res_sig = runner.invoke(agent, ["self", "--signature"])
    assert res_sig.exit_code == 0
    assert res_sig.output.strip() == "🤖 Generated with [opencode](https://opencode.ai)"

    res_name = runner.invoke(agent, ["self", "--name"])
    assert res_name.exit_code == 0
    assert res_name.output.strip() == "opencode"

    res_json = runner.invoke(agent, ["self", "--json"])
    assert res_json.exit_code == 0
    assert '"agent_type": "opencode"' in res_json.output

    res_sess = runner.invoke(session_group, ["self", "--signature"])
    assert res_sess.exit_code == 0
    assert res_sess.output.strip() == "🤖 Generated with [opencode](https://opencode.ai)"
