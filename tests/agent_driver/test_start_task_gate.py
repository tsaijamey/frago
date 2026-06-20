"""Phase 3b 单测：start_task 的 tmux 后端 gated 路由。

默认(无 FRAGO_AGENT_DRIVER)走 claude -p，不加 --driver；置 tmux 时追加
--driver tmux。用 monkeypatch 拦截 run_subprocess_background，捕获命令行。
"""

from __future__ import annotations

import pytest

from frago.server.services.agent_service import AgentService


class _FakeProc:
    pid = 4242


@pytest.fixture()
def captured_cmd(monkeypatch, tmp_path):
    calls: dict[str, list[str]] = {}

    def fake_bg(cmd, **_kwargs):
        calls["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(
        "frago.server.services.agent_service.run_subprocess_background", fake_bg
    )
    # 隔离日志/prompt 文件到 tmp。
    monkeypatch.setattr(
        "frago.server.services.agent_service.Path.home", lambda: tmp_path
    )
    return calls


def test_default_does_not_add_driver_flag(captured_cmd, monkeypatch) -> None:
    monkeypatch.delenv("FRAGO_AGENT_DRIVER", raising=False)
    result = AgentService.start_task("do a thing")
    assert result["status"] == "ok"
    assert "--driver" not in captured_cmd["cmd"]
    assert result["agent_type"] == "claude"


def test_gate_adds_tmux_driver_flag(captured_cmd, monkeypatch) -> None:
    monkeypatch.setenv("FRAGO_AGENT_DRIVER", "tmux")
    AgentService.start_task("do a thing")
    cmd = captured_cmd["cmd"]
    assert "--driver" in cmd
    assert cmd[cmd.index("--driver") + 1] == "tmux"


def test_gate_passes_agent_type_through(captured_cmd, monkeypatch) -> None:
    monkeypatch.setenv("FRAGO_AGENT_DRIVER", "tmux")
    result = AgentService.start_task("x", agent_type="opencode")
    cmd = captured_cmd["cmd"]
    assert cmd[cmd.index("--agent-type") + 1] == "opencode"
    assert result["agent_type"] == "opencode"


def test_gate_case_insensitive_and_trimmed(captured_cmd, monkeypatch) -> None:
    monkeypatch.setenv("FRAGO_AGENT_DRIVER", "  TMUX ")
    AgentService.start_task("x")
    assert "--driver" in captured_cmd["cmd"]
