"""Phase 5 单测：`frago agent` 的 --json 停机摘要 + 退出码契约 + 选项退场。

调用方 Agent 靠 (exit_code, JSON) 判断下一步，不解析人类文案，故这里把四态映射、
JSON 字段、stdout/stderr 分流全部钉死。

拦截 SessionLauncher 直接喂 TurnResult，不拉真实 tmux。全部用例带 --no-monitor：
落盘归一化不是本组的被测面，且会写进真实 ~/.frago。
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

import frago.agent_driver as agent_driver_mod
from frago.agent_driver.tmux_session import TurnResult
from frago.cli.agent_command import agent

SID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def run_agent(monkeypatch):
    """跑一轮 `frago agent`，SessionLauncher.run 的行为由 outcome 决定。

    outcome 是 TurnResult 时原样返回；是 Exception 时抛出。
    """

    def _install(outcome):
        class _FakeLauncher:
            def run(self, _prompt, **_kwargs):
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)

    def _run(outcome, *args: str):
        _install(outcome)
        return CliRunner().invoke(
            agent, ["--session-id", SID, "--no-monitor", *args, "ping"]
        )

    return _run


def _turn(status: str, text: str = "answer body") -> TurnResult:
    return TurnResult(text=text, raw_delta=text, status=status, duration_ms=1234)


# ── 四态：status → exit code + JSON 结构 ────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "exit_code"),
    [("ok", 0), ("timeout", 1), ("needs_input", 2)],
)
def test_json_status_maps_to_exit_code(run_agent, status, exit_code) -> None:
    res = run_agent(_turn(status), "--json")
    assert res.exit_code == exit_code, res.stderr
    payload = json.loads(res.stdout)
    assert payload["status"] == status
    assert payload["exit_code"] == exit_code
    assert payload["session_id"] == SID
    assert payload["tmux_name"] == f"frago-agent-{SID}"
    assert payload["text"] == "answer body"
    assert payload["duration_ms"] == 1234


def test_json_error_status_is_exit_3(run_agent) -> None:
    """driver/tmux 层失败 → error=3。send() 自身从不返回 error，只有这条路能到。"""
    res = run_agent(RuntimeError("tmux session never became ready"), "--json")
    assert res.exit_code == 3, res.stderr
    payload = json.loads(res.stdout)
    assert payload["status"] == "error"
    assert payload["exit_code"] == 3
    assert payload["text"] == ""
    assert payload["session_id"] == SID


def test_unknown_agent_type_is_error_3(run_agent) -> None:
    res = run_agent(KeyError("nope"), "--json", "--agent-type", "nope")
    assert res.exit_code == 3, res.stderr
    assert json.loads(res.stdout)["status"] == "error"
    assert "no driver registered" in res.stderr


def test_missing_tmux_is_error_3(run_agent) -> None:
    res = run_agent(FileNotFoundError("tmux"), "--json")
    assert res.exit_code == 3, res.stderr
    assert json.loads(res.stdout)["status"] == "error"
    assert "tmux not found" in res.stderr


# ── stdout 只有 JSON：人类文案一律走 stderr ────────────────────────────────


def test_json_stdout_is_exactly_one_object(run_agent) -> None:
    """调用方直接 json.loads(stdout)，故 stdout 不得混入答案原文或进度文案。"""
    res = run_agent(_turn("ok"), "--json")
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout)["text"] == "answer body"
    # 非 --quiet 时的 "[OK] tmux driver: ..." 属人类文案，必须在 stderr。
    assert "tmux driver" in res.stderr
    assert "tmux driver" not in res.stdout


def test_json_and_quiet_coexist(run_agent) -> None:
    res = run_agent(_turn("ok"), "--json", "--quiet")
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout)["status"] == "ok"
    assert res.stderr == ""


def test_json_timeout_note_goes_to_stderr(run_agent) -> None:
    res = run_agent(_turn("timeout", text="partial"), "--json", "--quiet")
    assert res.exit_code == 1
    assert json.loads(res.stdout)["text"] == "partial"
    assert "timed out" in res.stderr


# ── 无 --json 时：答案走 stdout，退出码不变 ────────────────────────────────


def test_without_json_answer_is_plain_stdout(run_agent) -> None:
    res = run_agent(_turn("ok"), "--quiet")
    assert res.exit_code == 0, res.stderr
    assert res.stdout.strip() == "answer body"


def test_without_json_exit_codes_still_hold(run_agent) -> None:
    assert run_agent(_turn("needs_input"), "--quiet").exit_code == 2
    assert run_agent(_turn("timeout"), "--quiet").exit_code == 1


# ── 选项退场：--driver / --ask / --passthrough 已不存在 ────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["--driver", "tmux"],
        ["--ask"],
        ["--passthrough"],
    ],
)
def test_retired_options_are_rejected(argv) -> None:
    res = CliRunner().invoke(agent, [*argv, "ping"])
    assert res.exit_code != 0
    assert "no such option" in res.stderr.lower()


# ── --yes 保留为隐藏 no-op（历史调用方大量带着它）───────────────────────────


def test_yes_is_accepted_and_inert(run_agent) -> None:
    """--yes 收到即忽略：与不带它跑出的结果逐字节相同。"""
    with_yes = run_agent(_turn("ok"), "--json", "--quiet", "--yes")
    without = run_agent(_turn("ok"), "--json", "--quiet")
    assert with_yes.exit_code == without.exit_code == 0
    assert with_yes.stdout == without.stdout


def test_short_y_is_accepted(run_agent) -> None:
    res = run_agent(_turn("ok"), "--json", "--quiet", "-y")
    assert res.exit_code == 0, res.stderr
    assert json.loads(res.stdout)["status"] == "ok"


def test_yes_is_hidden_from_help() -> None:
    """已废弃 → 不该再教给新调用方，但仍须被接受。"""
    res = CliRunner().invoke(agent, ["__run__", "--help"])
    assert res.exit_code == 0, res.output
    assert "--yes" not in res.output
    assert "--json" in res.output
