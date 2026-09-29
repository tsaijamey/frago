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


def _isolate_home(monkeypatch, tmp_path) -> None:
    """把家目录重定向到 tmp_path，Windows 与 POSIX 都算。

    只设 ``HOME`` 在 Windows 上不生效：那边 ``Path.home()`` / ``expanduser`` 认的是
    ``USERPROFILE``，于是用例会落到真人的 ``~/.frago`` 上，读到真机上已有的配方与配置、
    断言随机器而变（本机实测：这两条在 Windows 上因此必红）。两个变量一起设，用例才
    与跑在谁的机器上无关。
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


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


def test_tmux_target_is_handed_to_the_worker(captured) -> None:
    """--tmux-target 原样透传：worker 借住在那个会话里跑（桌面终端就是这么用的）。"""
    recipe_commands._run_frago_agent("hi", tmux_target="frago-stage")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tmux-target") + 1] == "frago-stage"


def test_no_tmux_target_by_default(captured) -> None:
    recipe_commands._run_frago_agent("hi")
    assert "--tmux-target" not in captured["cmd"]


def test_one_step_create_reaches_the_code_worker(tmp_path, monkeypatch) -> None:
    """一步式 create（--prompt）在规格与模板落盘之后必须真的派写码那一轮。

    从前这条路在拼写码提示词时引用了一个只在两步式里赋值的变量，Python 当场炸掉：
    规格写好了、模板生成了、写码的 worker 却从没起过，人看到的只是「create 失败」。
    """
    from click.testing import CliRunner

    _isolate_home(monkeypatch, tmp_path)
    prompts: list[str] = []

    def fake_plan(name, prompt_text, spec_path, **_kw):
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(
            "# spec\n```yaml\ntype: atomic\nruntime: python\nmodes:\n  now:\n"
            "default_mode: now\nimports: {}\npage: false\n```\n",
            encoding="utf-8",
        )

    def fake_agent(prompt, **_kw):
        prompts.append(prompt)
        return 0

    monkeypatch.setattr(recipe_commands, "_plan_into", fake_plan)
    monkeypatch.setattr(recipe_commands, "_run_frago_agent", fake_agent)

    result = runner_result = CliRunner().invoke(
        recipe_commands.create_recipe, ["demo_one_step", "--prompt", "打印当前时间"]
    )
    assert "NameError" not in (runner_result.output or "")
    assert not isinstance(result.exception, NameError), result.exception
    # 写码那一轮确实派了，而且提示词里写着规格在哪。
    assert len(prompts) == 1
    assert "spec.md" in prompts[0]
    assert "demo_one_step" in prompts[0]


def test_plan_and_create_tell_the_caller_to_go_background() -> None:
    """不知情的 agent 在 --help 里就该读到「后台跑」，而不是第 10 分钟被砍才猜。"""
    for cmd in (recipe_commands.plan_recipe, recipe_commands.create_recipe):
        assert "run_in_background" in cmd.help
        assert "background" in cmd.help


def test_plan_forwards_its_cap_to_the_worker(tmp_path, monkeypatch) -> None:
    """CLI 的 --timeout 一路传到 _run_frago_agent，缺省则是 0（不设上限）。"""
    from click.testing import CliRunner

    _isolate_home(monkeypatch, tmp_path)
    seen: dict[str, int] = {}

    def fake_agent(_prompt, *, agent_type="claude", timeout=0, tmux_target=None):
        seen["timeout"] = timeout
        seen["tmux_target"] = tmux_target
        return 0

    monkeypatch.setattr(recipe_commands, "_run_frago_agent", fake_agent)
    runner = CliRunner()

    result = runner.invoke(recipe_commands.plan_recipe, ["demo", "--prompt", "x"])
    assert result.exit_code == 0, result.output
    assert seen["timeout"] == 0
    assert seen["tmux_target"] is None

    result = runner.invoke(
        recipe_commands.plan_recipe, ["demo", "--prompt", "x", "--force", "--timeout", "45"]
    )
    assert result.exit_code == 0, result.output
    assert seen["timeout"] == 45

    result = runner.invoke(
        recipe_commands.plan_recipe,
        ["demo", "--prompt", "x", "--force", "--tmux-target", "frago-stage"],
    )
    assert result.exit_code == 0, result.output
    assert seen["tmux_target"] == "frago-stage"


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
