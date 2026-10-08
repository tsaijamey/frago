"""opencode 2.0 的常驻服务端：每场 frago 会话 MUST 跑在自己的配置上。

opencode 2.0 把服务端从 TUI 里拆出来做成一个**常驻**进程（``opencode serve
--service``），客户端经全局状态目录里的描述符找到它；而那个进程只在启动那一刻读一次
配置。不隔离的话，后起的会话带着自己的 profile 也改不动它——2026-10-09 实测：一个用
``--use-profile 火山-GLM5.3`` 起的会话，页脚里显示的仍是上一场的 ``deepseek-flash``，
屏幕上没有任何东西提示这件事。

修法是启动时加 ``--standalone``：这场会话用自己的私有服务端（stdio 管道、随机端口，
随 TUI 一起生灭），注入的配置当场生效，机器上也不留常驻进程。它是 2.0 才有的开关，
1.x 没有这层服务、也就不认这个参数，故加之前先问一句这份二进制支不支持。
"""

from __future__ import annotations

import subprocess

import pytest

from frago.agent_driver.driver import LaunchCtx, load_driver
from frago.agent_driver.drivers import opencode as opencode_driver
from frago.session import opencode_store

_HELP_WITH_FLAG = b"FLAGS\n  --standalone   Run with a private server\n"
_HELP_WITHOUT_FLAG = b"FLAGS\n  --continue, -c  Continue the last session\n"


def _ctx(session_id: str = "conv-1", **kwargs) -> LaunchCtx:
    return LaunchCtx(cwd="/w", session_id=session_id, **kwargs)


@pytest.fixture(autouse=True)
def _fresh_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例都从空缓存开始，并把"装没装 opencode"钉死。

    探测结果按可执行文件路径缓存（见 ``_standalone_flag``），跨用例留着会让后一个
    用例看到前一个的结论、而它自己根本没探测过。
    """
    monkeypatch.setattr(opencode_driver, "_STANDALONE_SUPPORT", {})
    monkeypatch.setattr(opencode_driver, "find_agent_cli", lambda _agent: "/opt/opencode")


def _help_returns(stdout: bytes, seen: dict | None = None):
    def _run(argv, **kwargs):
        if seen is not None:
            seen["argv"] = list(argv)
            seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    return _run


# ── 支不支持这个开关 ────────────────────────────────────────────────
def test_flag_is_used_when_the_binary_advertises_it(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(opencode_driver.subprocess, "run", _help_returns(_HELP_WITH_FLAG, seen))

    assert opencode_driver._standalone_flag() == "--standalone"
    assert seen["argv"] == ["/opt/opencode", "--help"]
    assert seen["timeout"] == opencode_driver._STANDALONE_PROBE_TIMEOUT_S


def test_flag_is_skipped_when_the_binary_does_not_know_it(monkeypatch) -> None:
    """1.x 没有这层服务，也就不认这个参数——加进去等于把会话拦在启动前。"""
    monkeypatch.setattr(opencode_driver.subprocess, "run", _help_returns(_HELP_WITHOUT_FLAG))

    assert opencode_driver._standalone_flag() == ""


def test_flag_is_skipped_when_the_probe_fails(monkeypatch) -> None:
    """探测本身超时 / 起不来：当不支持，退回裸启动，NEVER 把异常逸出去。"""

    def _boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10.0)

    monkeypatch.setattr(opencode_driver.subprocess, "run", _boom)

    assert opencode_driver._standalone_flag() == ""


def test_no_probe_at_all_when_opencode_is_not_installed(monkeypatch) -> None:
    monkeypatch.setattr(opencode_driver, "find_agent_cli", lambda _agent: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        opencode_driver.subprocess, "run", lambda argv, **kwargs: calls.append(list(argv))
    )

    assert opencode_driver._standalone_flag() == ""
    assert calls == []


def test_probe_runs_once_for_repeated_sessions(monkeypatch) -> None:
    """版本不会在一次进程的生命周期里变；每场会话都起子进程问一遍纯属浪费。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        opencode_driver.subprocess,
        "run",
        lambda argv, **kwargs: (
            calls.append(list(argv)),
            subprocess.CompletedProcess(argv, 0, _HELP_WITH_FLAG, b""),
        )[1],
    )

    assert opencode_driver._standalone_flag() == "--standalone"
    assert opencode_driver._standalone_flag() == "--standalone"
    assert len(calls) == 1


# ── 启动命令里的落点 ────────────────────────────────────────────────
def test_launch_carries_the_flag_in_every_shape(monkeypatch) -> None:
    monkeypatch.setattr(opencode_driver, "_standalone_flag", lambda: "--standalone")
    driver = load_driver("opencode")

    assert driver.launch_command(_ctx("fresh")) == "opencode --standalone"
    assert (
        driver.launch_command(_ctx("ses_native", native_session_id=True))
        == "opencode --standalone -s ses_native"
    )

    opencode_store.put_binding("known", "ses_abc", "/w")
    assert driver.launch_command(_ctx("known")) == "opencode --standalone -s ses_abc"


def test_launch_stays_bare_when_the_flag_is_unsupported(monkeypatch) -> None:
    """探测说不支持时命令一个字都不变，1.x 上跑出来的还是原来那条。"""
    monkeypatch.setattr(opencode_driver, "_standalone_flag", lambda: "")
    driver = load_driver("opencode")

    assert driver.launch_command(_ctx("fresh")) == "opencode"
    assert (
        driver.launch_command(_ctx("ses_native", native_session_id=True))
        == "opencode -s ses_native"
    )
