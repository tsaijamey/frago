"""本机挂出去的那条长连接：地址怎么拼、什么消息算数。

它不传数据，所以这里要验的不是「送到了没有」，而是两件更基础的事：地址拼得对不对
（拼错了连不上，而连不上只是慢回十五秒，**不会报错**，所以错了很难被发现），以及
只认中继那句「对面动了」，别的一概不当回事。
"""

from __future__ import annotations

from frago.team.live import LIVE_DOOR, TeamLiveLink


def _link(base: str = "https://www.frago.ai", seen: list | None = None) -> TeamLiveLink:
    return TeamLiveLink(
        base, "CODE123456", "fp-abc", "secret-xyz",
        (seen if seen is not None else []).append,
    )


def test_https_换成_wss():
    url = _link().url()
    assert url.startswith("wss://www.frago.ai" + LIVE_DOOR + "?")
    assert "code=CODE123456" in url
    assert "fingerprint=fp-abc" in url
    assert "secret=secret-xyz" in url


def test_http_换成_ws():
    """中继跑在本机、或者经 SSH 隧道映射到本地时是这一种。"""
    url = _link("http://127.0.0.1:8017/").url()
    assert url.startswith("ws://127.0.0.1:8017" + LIVE_DOOR + "?")


def test_只认对面动了这一句():
    seen: list = []
    link = _link(seen=seen)

    link._deliver('{"type": "peer_activity", "action": "push"}')
    assert seen == ["push"]

    # 别的消息、坏掉的 JSON、不是对象的东西，一律当没看见——这条连接没有
    # 请求-应答的语义，认错了会跑去同步一轮本来不需要同步的东西。
    link._deliver('{"type": "hello"}')
    link._deliver("not json at all")
    link._deliver("[1, 2, 3]")
    assert seen == ["push"]


def test_停掉之后不再投递():
    """stop() 只设标志位不够：线程多半正堵在一次读上，得把连接关掉叫醒它——而叫醒
    之后手上那条已经在路上的通知不能再转出去，这一侧已经退团了，转出去只会白跑
    一轮同步。

    这条是实测出来的（2026-10-16，真 uvicorn + 真客户端）：改之前停掉之后还会多
    投一条。
    """
    seen: list = []
    link = _link(seen=seen)

    link._deliver('{"type": "peer_activity", "action": "push"}')
    assert seen == ["push"]

    link.stop()
    link._deliver('{"type": "peer_activity", "action": "push"}')
    assert seen == ["push"]


def test_一次转发失败不把连接带走():
    """回调那头的异常不该让读循环退出——退出了就等于这条连接白挂，而没人会知道。"""
    calls: list = []

    def boom(action: str) -> None:
        calls.append(action)
        raise RuntimeError("调用方那边炸了")

    link = TeamLiveLink("https://www.frago.ai", "CODE", "fp", "sec", boom)
    link._deliver('{"type": "peer_activity", "action": "send"}')
    link._deliver('{"type": "peer_activity", "action": "send"}')
    assert calls == ["send", "send"]
