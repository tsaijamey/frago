"""Phase 1 单测：driver.run 产品化入口、codex needs_input、CLI 助手参数化。

仍不依赖真实 tmux / 真实 agent 二进制。
"""

from __future__ import annotations

from frago.agent_driver import SessionLauncher, load_driver
from tests.agent_driver.test_tmux_session import FakeTmux, _no_sleep


def test_codex_driver_registered_with_auth_wall() -> None:
    driver = load_driver("codex")
    assert driver.agent_type == "codex"
    assert driver.needs_input_signal is not None
    assert driver.needs_input_signal.matches("401 Unauthorized")
    assert driver.needs_input_signal.matches("Please login to continue")
    assert not driver.needs_input_signal.matches("all good, here is the answer")


def test_driver_run_codex_returns_needs_input_when_not_logged_in() -> None:
    # open() 等就绪 → send() 投喂 → 轮询撞认证墙 → needs_input。
    panes = [
        "codex >",  # open: ready poll
        "codex >",  # send: pre-snapshot
        "401 Unauthorized\nplease login",  # send: done/needs poll → auth wall
        "401 Unauthorized\nplease login",  # send: full scrollback
    ]
    fake = FakeTmux(panes)
    launcher = SessionLauncher(runner=fake)
    # launcher 内部 TmuxAgentSession 用默认 time.sleep；用极短超时避免真睡。
    # 但 needs_input 会在第一轮轮询即命中，不会进入 sleep 分支。
    result = launcher.run(
        "hello",
        agent_type="codex",
        session_id="cx1",
        cwd="/tmp",
        timeout_s=5,
    )
    assert result.status == "needs_input"


def test_driver_run_keep_alive_does_not_close() -> None:
    panes = [
        "Ask anything",  # open ready
        "Ask anything",  # pre-snapshot
        "▣ Build · m · 1.0s\nhello there",  # done footer
        "▣ Build · m · 1.0s\nhello there",  # scrollback
    ]
    fake = FakeTmux(panes)
    launcher = SessionLauncher(runner=fake)
    result = launcher.run(
        "hi",
        agent_type="opencode",
        session_id="oc1",
        cwd="/tmp",
        keep_alive=True,
        timeout_s=5,
    )
    assert result.status == "ok"
    # keep_alive=True 时不应发 kill-session。
    assert not any(c[1:2] == ["kill-session"] for c in fake.commands)


def test_driver_run_closes_by_default() -> None:
    panes = [
        "Ask anything",
        "Ask anything",
        "▣ Build · m · 1.0s\nbye",
        "▣ Build · m · 1.0s\nbye",
    ]
    fake = FakeTmux(panes)
    launcher = SessionLauncher(runner=fake)
    launcher.run("hi", agent_type="opencode", session_id="oc2", cwd="/tmp", timeout_s=5)
    assert any(c[1:2] == ["kill-session"] for c in fake.commands)


# ── 生产侧助手参数化 ────────────────────────────────────────────────
def test_get_agent_command_non_claude_returns_bare_binary() -> None:
    from frago.server.services.subprocess_utils import get_agent_command, get_claude_command

    assert get_agent_command("opencode") == ["opencode"]
    assert get_agent_command("codex") == ["codex"]
    # 向后兼容包装仍可用。
    assert get_claude_command() == get_agent_command("claude")


def test_find_agent_cli_unknown_agent_returns_none(monkeypatch) -> None:
    import frago.compat as compat

    monkeypatch.setattr(compat.shutil, "which", lambda _name: None)
    monkeypatch.setattr(compat.os.path, "isfile", lambda _p: False)
    assert compat.find_agent_cli("definitely-not-an-agent") is None


def test_no_sleep_helper_importable() -> None:
    # 守护：复用 test_tmux_session 的 _no_sleep，避免重复定义。
    _no_sleep(0.0)
