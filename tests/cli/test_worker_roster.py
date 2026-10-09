"""一次性 worker 也要进 sidecar 名册：跑动期间 `ls` 看得见、跑完不留死条目。

一次性那条路（`frago agent --prompt-file`）起完会话投一轮、跑完即关。它本该在名册里
留一笔，好让外壳进程被外部杀掉时留下跑飞的 tmux 会话仍能按名字 `frago agent stop`
收走。这里拦截 SessionLauncher，不拉真实 tmux；FRAGO_DRIVE_DIR 指向 tmp，不碰真实名册。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import frago.agent_driver as agent_driver_mod
from frago.agent_driver.tmux_session import TurnResult
from frago.cli import drive_command
from frago.cli.agent_command import agent

SID = "11111111-2222-3333-4444-555555555555"


def _turn() -> TurnResult:
    return TurnResult(text="answer", raw_delta="answer", status="ok", duration_ms=7)


@pytest.fixture
def drive_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("FRAGO_DRIVE_DIR", str(tmp_path))
    return tmp_path


def test_oneshot_worker_registered_during_run_then_removed(drive_dir, monkeypatch):
    seen: dict[str, object] = {}

    class _FakeLauncher:
        def run(self, _prompt, **_kwargs):
            # 会话跑动期间名册里应有这条一次性 worker，且 tmux 名与真实会话一致。
            seen["during"] = drive_command._read_entry(SID)
            return _turn()

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)
    res = CliRunner().invoke(
        agent, ["--session-id", SID, "--no-monitor", "--quiet", "ping"]
    )
    assert res.exit_code == 0, res.stderr
    during = seen["during"]
    assert during is not None
    assert during.tmux_name == f"frago-agent-{SID}"
    assert during.agent_type == "claude"
    # 跑完（会话已关）→ 名册不留死条目
    assert drive_command._read_entry(SID) is None


def test_oneshot_worker_removed_when_driver_errors(drive_dir, monkeypatch):
    class _FakeLauncher:
        def run(self, _prompt, **_kwargs):
            raise RuntimeError("tmux session never became ready")

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)
    res = CliRunner().invoke(
        agent, ["--session-id", SID, "--no-monitor", "--json", "ping"]
    )
    assert res.exit_code == 3, res.stderr
    assert drive_command._read_entry(SID) is None


def test_borrowed_tmux_target_is_not_registered(drive_dir, monkeypatch):
    class _FakeLauncher:
        def run(self, _prompt, **_kwargs):
            return _turn()

    monkeypatch.setattr(agent_driver_mod, "SessionLauncher", _FakeLauncher)
    res = CliRunner().invoke(
        agent,
        ["--session-id", SID, "--no-monitor", "--quiet", "--tmux-target", "frago-stage", "ping"],
    )
    assert res.exit_code == 0, res.stderr
    # 借住别人的会话不该进名册——那不是我们能 `stop` 的东西。
    assert drive_command._read_entry(SID) is None
