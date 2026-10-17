"""中继那台记着谁在线，以及它办完一次之后怎么喊对面。

通知是「快一点」，不是「送达」——送不出去不算错，对面下一趟轮询照样取得到。这里
要守住的就是这条分界：喊错了对象是白喊，喊失败却当成了错误会把一次正常请求弄挂。
"""

from __future__ import annotations

import asyncio

import pytest

from frago.server import security
from frago.server.routes import teaming
from frago.server.services.team_presence import TeamPresence


@pytest.fixture(autouse=True)
def _clean_presence():
    TeamPresence.reset_instance()
    yield
    TeamPresence.reset_instance()


def _collector(box: list):
    """一条假连接：收到的都扔进 ``box``。"""

    async def send(payload: dict) -> None:
        box.append(payload)

    return send


# ── 在线表 ──────────────────────────────────────────────────────────────


def test_通知送到点名的那一侧():
    presence = TeamPresence.get_instance()
    a, b = [], []
    presence.attach("CODE", "A", _collector(a))
    presence.attach("CODE", "B", _collector(b))

    assert asyncio.run(presence.notify("CODE", "B", {"n": 1})) is True
    assert b == [{"n": 1}]
    assert a == []


def test_没人在线不算失败():
    presence = TeamPresence.get_instance()
    assert asyncio.run(presence.notify("CODE", "A", {})) is False


def test_同侧重连时后到的顶掉先到的():
    """一台机器重启之后，旧的连接在服务端这边往往还要过一会儿才会被察觉。新连接
    必须立刻生效，否则通知会继续投给那个没人读的旧口子上——看起来就是「连上了
    还是慢」。"""
    presence = TeamPresence.get_instance()
    old, new = [], []
    presence.attach("CODE", "A", _collector(old))
    presence.attach("CODE", "A", _collector(new))

    asyncio.run(presence.notify("CODE", "A", {"n": 1}))
    assert new == [{"n": 1}]
    assert old == []


def test_旧连接断开不会摘掉顶替它的新连接():
    presence = TeamPresence.get_instance()
    old_sink, new_sink = _collector([]), _collector([])
    presence.attach("CODE", "A", old_sink)
    presence.attach("CODE", "A", new_sink)

    presence.detach("CODE", "A", old_sink)
    assert presence.online_sides("CODE") == ["A"]

    presence.detach("CODE", "A", new_sink)
    assert presence.online_sides("CODE") == []


def test_一条发不出去不影响在线表():
    presence = TeamPresence.get_instance()

    async def broken(payload: dict) -> None:
        raise RuntimeError("connection closed")

    presence.attach("CODE", "A", broken)
    assert asyncio.run(presence.notify("CODE", "A", {})) is False
    assert presence.online_sides("CODE") == ["A"]


def test_两侧各自独立():
    presence = TeamPresence.get_instance()
    presence.attach("CODE1", "A", _collector([]))
    presence.attach("CODE2", "B", _collector([]))
    assert presence.online_sides("CODE1") == ["A"]
    assert presence.online_sides("CODE2") == ["B"]


# ── 办完一次之后喊谁 ────────────────────────────────────────────────────


def test_push_喊的是对面那一侧():
    """push 回的 side 是发起那一侧，要喊的是它对面。"""
    box: list = []
    TeamPresence.get_instance().attach("CODE", "B", _collector(box))

    asyncio.run(teaming._nudge_peer("CODE", "push", {"side": "A", "stored": 3}))
    assert box == [{"type": "peer_activity", "action": "push"}]


def test_send_喊的是收件那一侧():
    """send 回的 delivered_to 是消息进了谁的信箱，那正是要喊醒的那一侧——不用再翻。"""
    box: list = []
    TeamPresence.get_instance().attach("CODE", "B", _collector(box))

    asyncio.run(teaming._nudge_peer("CODE", "send", {"delivered_to": "B"}))
    assert box == [{"type": "peer_activity", "action": "send"}]


@pytest.mark.parametrize(
    ("action", "data"),
    [
        ("status", {"side": "A"}),
        ("pull", {"messages": []}),
        ("peer", {"records": []}),
        ("open", {"side": "A"}),
    ],
)
def test_别的动作不喊人(action, data):
    """读的动作不改变任何东西，喊了只是让对面白跑一轮。"""
    box: list = []
    TeamPresence.get_instance().attach("CODE", "B", _collector(box))
    asyncio.run(teaming._nudge_peer("CODE", action, data))
    assert box == []


@pytest.mark.parametrize("data", [{}, {"total": 3}, {"side": None}, {"side": "C"}])
def test_返回里看不出该喊哪一侧就不喊(data):
    box: list = []
    TeamPresence.get_instance().attach("CODE", "B", _collector(box))
    asyncio.run(teaming._nudge_peer("CODE", "push", data))
    assert box == []


# ── 那扇门 ──────────────────────────────────────────────────────────────


def test_长连接那扇门的路径三处写得一样():
    """中继的路由、本机挂出去的客户端、安全层那张匿名白名单各写了一份字面量。

    拼错了不会报错：安全层会拦下这次握手，本机那侧看见的只是「连不上」，然后悄悄
    退回十五秒轮询——慢得像没改过。所以这条断言是这三份字面量唯一的对账处。
    """
    from frago.team.live import LIVE_DOOR

    assert teaming.LIVE_PATH == LIVE_DOOR
    assert frozenset({teaming.LIVE_PATH}) == security._ANON_WS


def test_匿名可以挂的长连接逐条登记():
    assert security._anon_ws_allowed({"type": "websocket", "path": "/api/teaming/ws"})
    # 别人家的 WebSocket 不跟着混进来
    assert not security._anon_ws_allowed({"type": "websocket", "path": "/ws"})
    # HTTP 那条道不认 WebSocket 的白名单，反之亦然
    assert not security._anon_ws_allowed({"type": "http", "path": "/api/teaming/ws"})
    assert not security._anon_post_allowed({"type": "websocket", "path": "/api/teaming/ws"})


def test_路径里带点段的照样拒():
    assert not security._anon_ws_allowed(
        {"type": "websocket", "path": "/api/teaming/../teaming/ws"}
    )
