"""那条常驻循环的契约。

它自己不做业务，所以这里钉的是**编排**：没配中继就别碰网络、一个 team 崩了不许把
别的 team 带停、投递走「空闲才送、送完看记录」那条路，既不等一整轮、也不在会话忙时
往输入框里打字。用会等整轮结束的那个函数，循环会被一场跑四十分钟的会话卡住，另一个
team 跟着一起停，而这件事在日志里看不出来。
"""

from __future__ import annotations

import pytest

from frago.server.services import team_sync_service as svc
from frago.team.state import Relay, TeamBinding, TeamState


@pytest.fixture
def configured(monkeypatch):
    state = TeamState(
        member="m", relay=Relay(url="https://relay.example")
    )
    state.teams["AAA234"] = TeamBinding(code="AAA234", session_id="sess-a", side="A")
    state.teams["BBB234"] = TeamBinding(code="BBB234", session_id="sess-b", side="B")
    monkeypatch.setattr("frago.team.state.load_state", lambda: state)
    return state


def test_没配中继就不碰网络(monkeypatch):
    state = TeamState(member="m")
    monkeypatch.setattr("frago.team.state.load_state", lambda: state)

    def explode(*_a, **_k):
        raise AssertionError("中继没配好却去敲了它")

    monkeypatch.setattr("frago.team.sync.sync_once", explode)

    assert svc.TeamSyncService._round() >= 30


def test_一个team崩了不影响另一个(monkeypatch, configured):
    tried: list[str] = []

    def flaky(_state, binding, _deliver):
        tried.append(binding.code)
        if binding.code == "AAA234":
            raise RuntimeError("中继连不上")
        from frago.team.sync import SyncOutcome

        return SyncOutcome(code=binding.code)

    monkeypatch.setattr("frago.team.sync.sync_once", flaky)

    svc.TeamSyncService._round()

    assert tried == ["AAA234", "BBB234"], "第一个 team 出错把第二个带停了"


def test_投递走空闲才送那条路不等整轮也不走排队(monkeypatch):
    """排队那条路不管会话忙不忙都往输入框里打字，回车被吞了没人知道（2026-09-29）。"""
    calls: list[tuple[str, str]] = []

    def when_idle(sid, prompt, *, landed):
        calls.append((sid, prompt))
        return "landed"

    monkeypatch.setattr(
        "frago.server.services.session_send.send_when_idle", when_idle
    )
    # 会等一整轮的那个函数被碰一下就当场失败：循环里用它，另一个 team 会被拖停。
    monkeypatch.setattr(
        "frago.server.services.session_send.send",
        lambda *a, **k: pytest.fail("用了会等一整轮的 send，循环会被卡住"),
    )
    monkeypatch.setattr(
        "frago.server.services.session_send.send_queued",
        lambda *a, **k: pytest.fail("用了不看会话忙不忙的 send_queued"),
    )

    deliver = svc.deliver_to("sess-a")

    assert deliver("队友说：跑一遍测试", lambda: False) == "landed"
    assert calls == [("sess-a", "队友说：跑一遍测试")]
