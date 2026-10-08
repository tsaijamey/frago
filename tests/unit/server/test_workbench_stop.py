"""「结束运行」这条通道：按下去之后到底动了谁。

盯的是三件会让人白按或者误伤的事：

1. 这一场根本没在跑时，如实说没在跑——**NEVER 报成已结束**，人会以为内存腾出来了；
2. 屏上还在干活时第一按不许动它，等人带 ``force`` 再按一次；
3. 关的时候只点这一场的名字，命令行里一个 ``kill-server`` 都不许出现。

不碰真 tmux：找会话与关会话两步都换成替身。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.server.services import tmux_sessions_service as svc

SID = "00a02979-7eb4-5c70-94ae-867c8281e3f6"
NAME = f"frago-agent-{SID}"


@pytest.fixture
def client():
    from frago.server.app import create_app

    return TestClient(create_app(), client=("127.0.0.1", 50000))


def _link(*, busy: bool) -> svc.TmuxSessionLink:
    return svc.TmuxSessionLink(name=NAME, label=SID, busy=busy, managed=False, memory_mb=310)


def test_a_session_that_is_not_running_is_reported_as_such(client, monkeypatch):
    closed: list[list[str]] = []
    monkeypatch.setattr(svc, "find_for_session", lambda sid: None)
    monkeypatch.setattr(svc, "close_sessions", lambda names: closed.append(names) or [])

    body = client.post(f"/api/workbench/sessions/{SID}/stop", json={}).json()

    assert body["alive"] is False
    assert body["stopped"] is False
    # 什么都没找到就什么都不该关——照着一个猜出来的名字去关，关掉的是别人。
    assert closed == []


def test_a_busy_session_survives_the_first_press(client, monkeypatch):
    closed: list[list[str]] = []
    monkeypatch.setattr(svc, "find_for_session", lambda sid: _link(busy=True))
    monkeypatch.setattr(svc, "close_sessions", lambda names: closed.append(names) or [])

    body = client.post(f"/api/workbench/sessions/{SID}/stop", json={}).json()

    assert body["busy"] is True
    assert body["stopped"] is False
    assert closed == []


def test_the_second_press_carries_force_and_closes_it(client, monkeypatch):
    closed: list[list[str]] = []

    def close(names):
        closed.append(names)
        return [{"name": names[0], "ok": True, "via": "tmux", "error": None}]

    monkeypatch.setattr(svc, "find_for_session", lambda sid: _link(busy=True))
    monkeypatch.setattr(svc, "close_sessions", close)

    body = client.post(f"/api/workbench/sessions/{SID}/stop", json={"force": True}).json()

    assert body["stopped"] is True
    assert body["via"] == "tmux"
    # 只点这一场的名字。
    assert closed == [[NAME]]


def test_a_refusal_from_tmux_is_passed_through_verbatim(client, monkeypatch):
    # 关不掉的理由必须原样送到人眼前：是没找到会话，还是 tmux 拒了，处置完全不同。
    monkeypatch.setattr(svc, "find_for_session", lambda sid: _link(busy=False))
    monkeypatch.setattr(
        svc,
        "close_sessions",
        lambda names: [
            {"name": names[0], "ok": False, "via": "tmux", "error": "can't find session"}
        ],
    )

    body = client.post(f"/api/workbench/sessions/{SID}/stop", json={}).json()

    assert body["stopped"] is False
    assert body["error"] == "can't find session"


# ── CoreAgent 那一场：它不跑在 tmux 里 ──────────────────────────────────────
#
# 从前的判据只有 tmux：对一场正在跑的 CoreAgent 会话，按下这个按钮服务端回一句「这一场
# 此刻没有在跑的会话」，而它其实还在跑，跑多久也没人停得下来。下面几条盯的是按下去
# 真的停到它，而且不用人按第二下。

CORE_SID = "core_18dbe0cfd02cb8a00000865f0000"


def _core_stop(monkeypatch, outcome):
    from frago.server.services import coreagent_runner

    monkeypatch.setattr(coreagent_runner, "stop", lambda sid, by="": outcome)


def test_a_running_coreagent_session_is_stopped_without_asking_tmux(client, monkeypatch):
    asked: list[str] = []
    monkeypatch.setattr(svc, "find_for_session", lambda sid: asked.append(sid) or None)
    _core_stop(monkeypatch, {"running": True, "stopped": True, "busy": True, "dropped": 0})

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={}).json()

    assert body["stopped"] is True
    assert body["alive"] is True
    assert body["busy"] is True
    assert body["via"] == "coreagent"
    assert asked == [], "CoreAgent 不跑在 tmux 里，不该去问 tmux"


def test_a_coreagent_session_that_is_not_running_is_reported_as_such(client, monkeypatch):
    _core_stop(monkeypatch, {"running": False, "stopped": False, "busy": False, "dropped": 0})

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={}).json()

    assert body["alive"] is False
    assert body["stopped"] is False
    assert body["via"] is None


def test_a_coreagent_stop_does_not_need_a_second_press(client, monkeypatch):
    """tmux 那条路要人按两次（屏上还在干活时先问一次）。CoreAgent 一次就停——人按这个
    按钮正是因为等不下去了，再问一次只是让他多按一下，而那一轮还在跑。"""
    _core_stop(monkeypatch, {"running": True, "stopped": True, "busy": True, "dropped": 3})

    body = client.post(f"/api/workbench/sessions/{CORE_SID}/stop", json={"force": False}).json()

    assert body["stopped"] is True
