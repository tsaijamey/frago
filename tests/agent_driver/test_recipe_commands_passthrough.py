"""Phase 4 单测：recipe plan/create 的 _run_frago_agent 透传 --agent-type。

默认 claude；显式指定时透传 agent_type。Phase 5 起 tmux 是唯一后端，
_run_frago_agent 不再有 driver 参数，故一并断言命令行不含已退场的 --driver / --yes。

另一半是墙钟：这条路曾经用 subprocess.run(timeout=600) 从外面给 `frago agent`
硬扣 600 秒，到点 SIGKILL 掉它，于是 SessionLauncher 的 finally 收不到，泄漏一条
孤儿 tmux 会话。现在缺省不设上限，显式上限交给被调方执行——下面几条钉的就是
「本进程 NEVER 自己拿墙钟杀人」。
"""

from __future__ import annotations

import pytest

from frago.agent_driver import load_driver
from frago.cli import recipe_commands


class _Result:
    returncode = 0


@pytest.fixture()
def captured(monkeypatch):
    calls: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(recipe_commands.subprocess, "run", fake_run)
    return calls


def test_default_agent_type_is_claude(captured) -> None:
    rc = recipe_commands._run_frago_agent("hello")
    assert rc == 0
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-type") + 1] == "claude"


def test_agent_type_passed_through(captured) -> None:
    recipe_commands._run_frago_agent("hi", agent_type="opencode")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--agent-type") + 1] == "opencode"


def test_retired_flags_are_not_spliced(captured) -> None:
    """--driver 已从 CLI 删除：再拼上去会让 agent 以 usage error 直接退出。"""
    recipe_commands._run_frago_agent("hi")
    cmd = captured["cmd"]
    assert "--driver" not in cmd
    assert "--yes" not in cmd


# ── 墙钟：缺省不设上限，显式上限交给被调方 ──────────────────────────
def test_no_wall_clock_by_default(captured) -> None:
    """缺省这一轮不设墙钟：既不给 subprocess 设 timeout，也不给被调方拼 --timeout。"""
    recipe_commands._run_frago_agent("hi")
    assert captured["kwargs"].get("timeout") is None
    assert "--timeout" not in captured["cmd"]


def test_explicit_cap_is_handed_to_the_callee(captured) -> None:
    """显式上限走 `frago agent --timeout N`——它到点自己收尾，不留孤儿 tmux。

    NEVER 退回 subprocess.run(timeout=...)：那条路是 SIGKILL，
    SessionLauncher.run 的 `finally: session.close()` 收不到。
    """
    recipe_commands._run_frago_agent("hi", timeout=30)
    cmd = captured["cmd"]
    assert cmd[cmd.index("--timeout") + 1] == "30"
    assert captured["kwargs"].get("timeout") is None


def test_plan_and_create_tell_the_caller_to_go_background() -> None:
    """不知情的 agent 在 --help 里就该读到「后台跑」，而不是第 10 分钟被砍才猜。"""
    for cmd in (recipe_commands.plan_recipe, recipe_commands.create_recipe):
        assert "run_in_background" in cmd.help
        assert "background" in cmd.help


def test_plan_forwards_its_cap_to_the_worker(tmp_path, monkeypatch) -> None:
    """CLI 的 --timeout 一路传到 _run_frago_agent，缺省则是 0（不设上限）。"""
    from click.testing import CliRunner

    monkeypatch.setenv("HOME", str(tmp_path))
    seen: dict[str, int] = {}

    def fake_agent(_prompt, *, agent_type="claude", timeout=0):
        seen["timeout"] = timeout
        return 0

    monkeypatch.setattr(recipe_commands, "_run_frago_agent", fake_agent)
    runner = CliRunner()

    result = runner.invoke(recipe_commands.plan_recipe, ["demo", "--prompt", "x"])
    assert result.exit_code == 0, result.output
    assert seen["timeout"] == 0

    result = runner.invoke(
        recipe_commands.plan_recipe, ["demo", "--prompt", "x", "--force", "--timeout", "45"]
    )
    assert result.exit_code == 0, result.output
    assert seen["timeout"] == 45


# ── opencode driver 端到端契约(Phase 0 实测坑全部进 driver) ──────────
def test_opencode_driver_encodes_all_three_quirks() -> None:
    driver = load_driver("opencode")
    # 1) 启动 Update 模态 → Esc 异常处理器。
    assert any(h.name == "dismiss-update-modal" for h in driver.exception_handlers)
    # 2) ▣ Build 完成页脚作 done_signal。
    assert driver.done_signal.matches("▣ Build · m · 2.1s")
    # 3) 单 Enter 提交（1.17.10 / 1.18.0 实测；旧版双 Enter 结论已推翻）。
    from frago.agent_driver.tmux_session import TmuxAgentSession
    from tests.agent_driver.test_tmux_session import FakeTmux

    fake = FakeTmux(["box has text"])
    sess = TmuxAgentSession("e2e", driver, cwd="/tmp", runner=fake)
    driver.submit(sess, "box has text")
    enters = sum(
        1 for c in fake.commands if c[1:2] == ["send-keys"] and c[-1] == "Enter"
    )
    assert enters == 1
