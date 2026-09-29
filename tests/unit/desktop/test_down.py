"""desktop down 收走演员浏览器：broker 先停、演员后收，先核对再报。"""

from __future__ import annotations

import types

import pytest

from frago.desktop import aos, registry


@pytest.fixture
def down_env(monkeypatch):
    """隔离 down 的全部外部动作：broker HTTP、kill、注册表、frago 子进程。"""
    order: list[str] = []
    monkeypatch.setattr(aos, "post", lambda *a, **k: {})
    monkeypatch.setattr(aos, "get_status",
                        lambda rec, **k: {"pid": 4242,
                                          "cdp_ports": {"stage": 9222, "record": 9223}})
    monkeypatch.setattr(aos.os, "kill", lambda pid, sig: order.append("kill-broker"))
    monkeypatch.setattr(registry, "set_desired", lambda *a: None)
    monkeypatch.setattr(registry, "_port_alive", lambda port: False)
    monkeypatch.setattr(registry, "mark_stopped", lambda *a: None)
    monkeypatch.setattr(registry, "read_instance", lambda *a: {"status": "stopped"})
    monkeypatch.setattr(aos.time, "sleep", lambda s: None)
    return order


REC = {"id": "default", "pid": 4242, "port": 8093}


def test_down_stops_actor_after_broker(down_env, monkeypatch):
    alive = {"v": True}
    monkeypatch.setattr(aos, "_cdp_answering", lambda port: alive["v"])

    def fake_run(cmd, **kw):
        down_env.append(("stop", tuple(cmd[1:])))
        alive["v"] = False
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(aos.subprocess, "run", fake_run)
    out = aos.cmd_down(REC)
    assert down_env[0] == "kill-broker"
    assert down_env[1] == ("stop", ("browser", "-b", "cdp", "stop", "--port", "9222"))
    assert out["actor_browser"] == {"port": 9222, "stopped": True}


def test_down_admits_nothing_to_stop(down_env, monkeypatch):
    monkeypatch.setattr(aos, "_cdp_answering", lambda port: False)
    monkeypatch.setattr(aos.subprocess, "run",
                        lambda *a, **k: pytest.fail("端口没人应答不该去 stop"))
    out = aos.cmd_down(REC)
    assert out["ok"] is True
    assert out["actor_browser"]["stopped"] is False


def test_down_reports_actor_that_survived_stop(down_env, monkeypatch):
    monkeypatch.setattr(aos, "_cdp_answering", lambda port: True)
    monkeypatch.setattr(aos.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="",
                                                              stderr="boom"))
    clock = iter(range(0, 1000, 5))
    monkeypatch.setattr(aos.time, "time", lambda: next(clock))
    out = aos.cmd_down(REC)
    assert out["ok"] is True
    assert out["actor_browser"]["stopped"] is False
    assert out["actor_browser"]["detail"] == "boom"


def test_down_falls_back_to_9222_when_broker_silent(down_env, monkeypatch):
    def silent(rec, **k):
        raise aos.die("读不到")
    monkeypatch.setattr(aos, "get_status", silent)
    seen = []
    monkeypatch.setattr(aos, "_stop_actor_browser", lambda port: seen.append(port) or {})
    aos.cmd_down(REC)
    assert seen == [9222]
