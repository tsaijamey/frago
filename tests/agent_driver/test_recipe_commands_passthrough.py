"""Phase 4 单测：recipe plan/create 的 _run_frago_agent 透传 --agent-type。

默认 claude、不加 --driver(行为不变)；显式指定时透传 agent_type 与 driver。
"""

from __future__ import annotations

import pytest

from frago.agent_driver import load_recipe
from frago.cli import recipe_commands


class _Result:
    returncode = 0


@pytest.fixture()
def captured(monkeypatch):
    calls: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        calls["cmd"] = cmd
        return _Result()

    monkeypatch.setattr(recipe_commands.subprocess, "run", fake_run)
    return calls


def test_default_agent_type_is_claude_no_driver(captured) -> None:
    rc = recipe_commands._run_frago_agent("hello")
    assert rc == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-type") + 1] == "claude"
    assert "--driver" not in cmd


def test_passthrough_agent_type_and_driver(captured) -> None:
    recipe_commands._run_frago_agent("hi", agent_type="opencode", driver="tmux")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-type") + 1] == "opencode"
    assert cmd[cmd.index("--driver") + 1] == "tmux"


# ── opencode recipe 端到端契约(Phase 0 实测坑全部进 recipe) ──────────
def test_opencode_recipe_encodes_all_three_quirks() -> None:
    recipe = load_recipe("opencode")
    # 1) 启动 Update 模态 → Esc 异常处理器。
    assert any(h.name == "dismiss-update-modal" for h in recipe.exception_handlers)
    # 2) ▣ Build 完成页脚作 done_signal。
    assert recipe.done_signal.matches("▣ Build · m · 2.1s")
    # 3) 双 Enter 提交：用 FakeTmux 数 Enter 次数。
    from frago.agent_driver.tmux_session import TmuxAgentSession
    from tests.agent_driver.test_tmux_session import FakeTmux

    fake = FakeTmux(["box has text"])
    sess = TmuxAgentSession("e2e", recipe, cwd="/tmp", runner=fake)
    recipe.submit(sess, "box has text")
    enters = sum(
        1 for c in fake.commands if c[1:2] == ["send-keys"] and c[-1] == "Enter"
    )
    assert enters == 2
