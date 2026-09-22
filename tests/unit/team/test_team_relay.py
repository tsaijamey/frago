"""朝中继那扇门发请求这一层的契约。

只钉两件事，都是「不这么做就会悄悄坏掉」的那种：被限流要退一下再来，以及中继说
「这个码不可用」时本机不许替它猜是哪一种不可用。
"""

from __future__ import annotations

import pytest

from frago.team import relay as relay_mod
from frago.team.relay import RelayClient, RelayError
from frago.team.state import Relay


class FakeReply:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("没有 JSON")
        return self._payload


def _client(monkeypatch, replies):
    client = RelayClient(Relay(url="https://relay.example"))
    queue = list(replies)
    sent: list[dict] = []

    def post(url, json=None, timeout=None):  # noqa: A002
        sent.append(json or {})
        return queue.pop(0)

    monkeypatch.setattr(client._http, "post", post)
    monkeypatch.setattr(relay_mod.time, "sleep", lambda _s: None)
    return client, sent


def test_被限流挡住要退一下再来(monkeypatch):
    client, sent = _client(monkeypatch, [FakeReply(429), FakeReply(200, {"side": "A"})])

    got = client.call("status", code="ABCD234567")

    assert got == {"side": "A"}
    assert len(sent) == 2


def test_一直被限流要说清楚是被限流(monkeypatch):
    client, _ = _client(
        monkeypatch, [FakeReply(429)] * (relay_mod.BUSY_RETRIES + 1)
    )

    with pytest.raises(RelayError, match="限流"):
        client.call("status", code="ABCD234567")


def test_码不可用时不替中继猜是哪一种(monkeypatch):
    """中继对「码不对」和「你是第三台机器」回的是同一个答案。

    本机这边要是替它分开说，等于把它藏起来的那盏指示灯自己点上——猜码的人正是靠
    这个分辨哪个码是活的。
    """
    client, _ = _client(monkeypatch, [FakeReply(404, {"error": "no_such_team"})])

    with pytest.raises(RelayError) as err:
        client.call("join", code="ZZZZZZZZZZ")

    said = str(err.value)
    assert "不可用" in said
    assert "不区分" in said or "免得" in said


def test_动作发出去时带的就是调用方给的那些(monkeypatch):
    client, sent = _client(monkeypatch, [FakeReply(200, {})])

    client.call("push", code="ABCD234567", fingerprint="fp", secret="k", records=[])

    assert sent[0] == {
        "action": "push", "code": "ABCD234567",
        "fingerprint": "fp", "secret": "k", "records": [],
    }
