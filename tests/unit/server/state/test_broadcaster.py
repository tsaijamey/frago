"""Unit tests for StateBroadcaster extracted from StateManager (Phase 3).

以单元测试为准：断言订阅管理、消息组装、以及「broadcast_raw 无论发送成败都通知订阅者」
「broadcast 不通知订阅者」这两条原 StateManager 语义。WebSocket manager 全部 mock。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from frago.server.state.broadcaster import StateBroadcaster


def _run(coro):
    return asyncio.run(coro)


def test_subscribe_unsubscribe():
    b = StateBroadcaster()
    cb = lambda t, d: None
    b.subscribe(cb)
    assert cb in b._subscribers
    b.unsubscribe(cb)
    assert cb not in b._subscribers
    # unsubscribe of unknown callback is a no-op (no raise)
    b.unsubscribe(cb)


def test_broadcast_builds_typed_message():
    b = StateBroadcaster()
    fake_mgr = MagicMock()
    fake_mgr.broadcast = AsyncMock()
    fake_mgr.connection_count = 1
    with patch("frago.server.websocket.create_message", side_effect=lambda t, d: {"type": t, **d}) as cm, \
         patch("frago.server.websocket.manager", fake_mgr):
        _run(b.broadcast("recipes", 7, [{"name": "r"}]))
        cm.assert_called_once_with("data_recipes", {"version": 7, "data": [{"name": "r"}]})
        fake_mgr.broadcast.assert_awaited_once()


def test_broadcast_does_not_notify_subscribers():
    b = StateBroadcaster()
    seen = []
    b.subscribe(lambda t, d: seen.append((t, d)))
    fake_mgr = MagicMock()
    fake_mgr.broadcast = AsyncMock()
    fake_mgr.connection_count = 0
    with patch("frago.server.websocket.create_message", side_effect=lambda t, d: {}), \
         patch("frago.server.websocket.manager", fake_mgr):
        _run(b.broadcast("skills", 1, []))
    assert seen == []  # broadcast (non-raw) never notifies local subscribers


def test_broadcast_raw_notifies_subscribers_even_on_send_failure():
    b = StateBroadcaster()
    seen = []
    b.subscribe(lambda t, d: seen.append((t, d)))
    fake_mgr = MagicMock()
    fake_mgr.broadcast = AsyncMock(side_effect=RuntimeError("ws down"))
    fake_mgr.connection_count = 0
    with patch("frago.server.websocket.create_message", side_effect=lambda t, d: {}), \
         patch("frago.server.websocket.manager", fake_mgr):
        _run(b.broadcast_raw("data_config", 3, {"k": "v"}))
    # send failed but subscriber still notified (matches original _broadcast_raw semantics)
    assert seen == [("data_config", {"k": "v"})]


def test_broadcast_raw_subscriber_exception_isolated():
    b = StateBroadcaster()
    b.subscribe(lambda t, d: (_ for _ in ()).throw(ValueError("bad")))
    ok = []
    b.subscribe(lambda t, d: ok.append(d))
    fake_mgr = MagicMock()
    fake_mgr.broadcast = AsyncMock()
    fake_mgr.connection_count = 0
    with patch("frago.server.websocket.create_message", side_effect=lambda t, d: {}), \
         patch("frago.server.websocket.manager", fake_mgr):
        _run(b.broadcast_raw("data_gh_status", 2, {"x": 1}))
    # one subscriber raised, the other still ran
    assert ok == [{"x": 1}]
