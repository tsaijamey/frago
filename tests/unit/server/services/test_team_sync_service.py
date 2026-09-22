"""那条常驻循环的契约。

它自己不做业务，所以这里钉的是**编排**：没配中继就别碰网络、一个 team 崩了不许把
别的 team 带停、投递走的是排队那条路而不是等一整轮的那条。最后一条尤其要钉——用
会等整轮结束的那个函数，循环会被一场跑四十分钟的会话卡住，另一个 team 跟着一起停，
而这件事在日志里看不出来。
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


def test_投递走排队那条路不等整轮(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "frago.server.services.session_send.send_queued",
        lambda sid, prompt: calls.append((sid, prompt)) or "thread",
    )
    # 会等一整轮的那个函数被碰一下就当场失败：循环里用它，另一个 team 会被拖停。
    monkeypatch.setattr(
        "frago.server.services.session_send.send",
        lambda *a, **k: pytest.fail("用了会等一整轮的 send，循环会被卡住"),
    )

    deliver = svc._deliver_to("sess-a")
    deliver("队友说：跑一遍测试")

    assert calls == [("sess-a", "队友说：跑一遍测试")]
