"""`frago browser -b cdp start` 失败时必须报失败。

缺陷的形态：这条命令的每一条失败分支都是 `click.echo("Error: ...", err=True)`
之后 `return`，而 click 把正常返回当成成功——命令在 stderr 上说自己失败了，
对 shell 说的却是成功。

它咬到过谁：agent_os 的 broker 用
`subprocess.run(["frago","browser","-b","cdp","start",...])` 起录制机位，闸门是
`if proc.returncode != 0: raise`。返回码恒为 0，这道闸从不触发，于是浏览器
根本没起来这件事一路走到 30 秒之后，报出一句"浏览器起完了但端口上没有 CDP
应答"——把"根本没起来"说成"起来了但没应答"。2026-09-02 排查那条缺陷的时间，
一多半花在这句措辞上。

同一个函数里 `--void` 那条分支 `raise SystemExit(2)` 一直是对的，所以这不是
一条"当时没有这个约定"的旧代码，是漏了。
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import frago.cli.browser_commands  # noqa: F401  —— import 时就地包上后端分发
from frago.cli.commands import browser_start


def run(*args):
    # obj 里的 BACKEND 是 `-b cdp` 那个开关。不给的话默认走 extension 后端，
    # 验到的就不是这条命令了——browser_commands 在 import 时就把 browser_start
    # 的 callback 原地换成了分发包装。
    #
    # standalone_mode 走默认：要验的正是退出码，关掉它 click 就不退出了。
    return CliRunner().invoke(browser_start, list(args), obj={"BACKEND": "cdp"})


def test_mutually_exclusive_modes_exit_nonzero():
    r = run("--headless", "--app", "--app-url", "http://127.0.0.1:1")
    assert "mutually exclusive" in r.output
    assert r.exit_code != 0


def test_app_mode_without_url_exits_nonzero():
    r = run("--app")
    assert "requires --app-url" in r.output
    assert r.exit_code != 0


def test_browser_not_found_exits_nonzero(monkeypatch):
    """点名一个装不到的浏览器：命令什么也没做成，退出码不许是 0。"""
    import frago.browser.cdp.launcher as launcher_mod

    class NoBrowser:
        browser_path = None

        def __init__(self, **kw):
            pass

    monkeypatch.setattr(launcher_mod, "ChromeLauncher", NoBrowser)
    r = run("--browser", "chromium")
    assert "not found" in r.output
    assert r.exit_code != 0


def test_launch_failure_exits_nonzero(monkeypatch):
    """这一条是真正咬到 broker 的那条分支：浏览器起了，CDP 没上来。

    原来它只打一行 `[X] Failed to launch browser` 就返回 0。
    """
    import frago.browser.cdp.launcher as launcher_mod

    class FailsToLaunch:
        browser_path = "/Applications/Nowhere.app/Contents/MacOS/Nowhere"
        browser_type = type("B", (), {"value": "edge"})()
        profile_dir = "/tmp/does-not-matter"

        def __init__(self, **kw):
            pass

        def launch(self, kill_existing=True):
            return False

    monkeypatch.setattr(launcher_mod, "ChromeLauncher", FailsToLaunch)
    r = run("--headless")
    assert "Failed to launch browser" in r.output
    assert r.exit_code != 0


def test_a_successful_launch_still_exits_zero(monkeypatch):
    """反向守一条：别为了让失败报错，把成功也变成了失败。"""
    import frago.browser.cdp.launcher as launcher_mod

    class Launches:
        browser_path = "/Applications/Whatever.app/Contents/MacOS/Whatever"
        browser_type = type("B", (), {"value": "edge"})()
        profile_dir = "/tmp/does-not-matter"

        def __init__(self, **kw):
            pass

        def launch(self, kill_existing=True):
            return True

        def get_status(self):
            return {"running": True, "browser": "Edg/138"}

    monkeypatch.setattr(launcher_mod, "ChromeLauncher", Launches)
    r = run("--headless")
    assert "[OK] Browser launched" in r.output
    assert r.exit_code == 0


@pytest.mark.parametrize("args", [
    ("--headless", "--app", "--app-url", "http://127.0.0.1:1"),
    ("--app",),
])
def test_the_error_still_says_what_went_wrong(args):
    """退出码之外，措辞一个字都不许丢——退出码告诉脚本，措辞告诉人。"""
    r = run(*args)
    assert r.output.startswith("[Usage]") or "Error:" in r.output
    assert "Error:" in r.output
