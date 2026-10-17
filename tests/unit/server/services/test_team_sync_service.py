"""那条常驻循环的契约。

它自己不做业务，所以这里钉的是**编排**：没配中继就别碰网络、一个 team 崩了不许把
别的 team 带停、投递走「空闲才送、送完看记录」那条路，既不等一整轮、也不在会话忙时
往输入框里打字。用会等整轮结束的那个函数，循环会被一场跑四十分钟的会话卡住，另一个
team 跟着一起停，而这件事在日志里看不出来。
"""

from __future__ import annotations

import asyncio

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


# ── 长连接 ──────────────────────────────────────────────────────────────
#
# 长连接是「快一点」那条路，定时轮询仍旧是底。所以这里钉的不是「连上了就万事大吉」，
# 而是两条边界：本机参加的每个 team 恰好各挂一条（不多挂、退出就摘），以及对面连着
# 喊的时候不排队——排队等于把一串通知变成一串同步。


class _FakeLink:
    """替掉真的长连接：只记下谁被挂上、谁被摘掉。"""

    made: list[_FakeLink] = []

    def __init__(self, base, code, fingerprint, secret, on_activity):
        self.base = base
        self.code = code
        self.fingerprint = fingerprint
        self.secret = secret
        self.on_activity = on_activity
        self.started = False
        self.stopped = False
        _FakeLink.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_links(monkeypatch):
    _FakeLink.made = []
    monkeypatch.setattr("frago.team.live.TeamLiveLink", _FakeLink)
    return _FakeLink


def test_每个_team_各挂一条长连接(configured, fake_links):
    service = svc.TeamSyncService()
    asyncio.run(service._refresh_links())

    assert sorted(link.code for link in fake_links.made) == ["AAA234", "BBB234"]
    assert all(link.started for link in fake_links.made)
    assert all(link.fingerprint == "m" for link in fake_links.made)
    assert all(link.base == "https://relay.example" for link in fake_links.made)


def test_退出之后长连接摘掉(configured, fake_links):
    service = svc.TeamSyncService()
    asyncio.run(service._refresh_links())
    first = {link.code: link for link in fake_links.made}

    configured.teams["AAA234"].active = False
    asyncio.run(service._refresh_links())

    assert first["AAA234"].stopped is True
    assert first["BBB234"].stopped is False


def test_再跑一趟不会重复挂(configured, fake_links):
    """这一趟每十五秒跑一次，挂重了就是每十五秒多一条连向中继的长连接。"""
    service = svc.TeamSyncService()
    asyncio.run(service._refresh_links())
    asyncio.run(service._refresh_links())

    assert len(fake_links.made) == 2


def test_没配中继一条都不挂(monkeypatch, fake_links):
    state = TeamState(member="m")
    monkeypatch.setattr("frago.team.state.load_state", lambda: state)

    service = svc.TeamSyncService()
    asyncio.run(service._refresh_links())

    assert fake_links.made == []


def test_同一个_team_上的通知不排队(monkeypatch):
    """对面连着推几条记录会连喊好几声，而我们跑一轮就把它们都取回来了。

    排队的话，一次会话活跃能叫出十几轮同步，每一轮都是一串 HTTP。
    """
    ran: list[str] = []
    monkeypatch.setattr(
        svc.TeamSyncService, "_round_one", staticmethod(lambda code: ran.append(code))
    )

    async def go():
        service = svc.TeamSyncService()
        await asyncio.gather(
            service._sync_now("AAA234"),
            service._sync_now("AAA234"),
            service._sync_now("AAA234"),
        )

    asyncio.run(go())

    assert ran == ["AAA234"]


def test_不同_team_的通知各跑各的(monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(
        svc.TeamSyncService, "_round_one", staticmethod(lambda code: ran.append(code))
    )

    async def go():
        service = svc.TeamSyncService()
        await asyncio.gather(
            service._sync_now("AAA234"),
            service._sync_now("BBB234"),
        )

    asyncio.run(go())

    assert sorted(ran) == ["AAA234", "BBB234"]


def test_喊醒的那一轮只碰点名的_team(monkeypatch, configured):
    """对面动了，不该顺手把本机另一个 team 也同步一遍。"""
    tried: list[str] = []

    def spy(_state, binding, _deliver):
        from frago.team.sync import SyncOutcome

        tried.append(binding.code)
        return SyncOutcome(code=binding.code)

    monkeypatch.setattr("frago.team.sync.sync_once", spy)

    svc.TeamSyncService._round_one("BBB234")

    assert tried == ["BBB234"]


def test_已经退出的_team_被喊醒也不跑(monkeypatch, configured):
    tried: list[str] = []
    monkeypatch.setattr(
        "frago.team.sync.sync_once",
        lambda _s, binding, _d: tried.append(binding.code),
    )

    configured.teams["AAA234"].active = False
    svc.TeamSyncService._round_one("AAA234")

    assert tried == []
