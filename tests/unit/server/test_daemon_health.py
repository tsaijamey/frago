"""启动健康检查在「服务器带门」的部署下的判定。

部署指南要求服务器设 FRAGO_BEHIND_PROXY=1，那之后从回环发起、不带令牌的探测
本来就该被门挡回 401。若健康检查只认 200，`frago server start/restart`
会在一台其实起得好好的服务器上报 unhealthy。
"""

import http.client
from unittest.mock import patch

import pytest

from frago.server.daemon import _wait_for_healthy


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status


def _poll_seeing(status: int, timeout: int = 2):
    class _Conn:
        def __init__(self, *args, **kwargs) -> None: ...
        def request(self, *args, **kwargs) -> None: ...
        def getresponse(self) -> _Resp:
            return _Resp(status)
        def close(self) -> None: ...

    with patch.object(http.client, "HTTPConnection", _Conn):
        return _wait_for_healthy(timeout=timeout)


def test_a_plain_ok_is_healthy():
    healthy, _ = _poll_seeing(200)
    assert healthy


def test_the_gate_turning_the_poll_away_is_also_healthy():
    """401 证明进程起来了、而且中间件装上了——比裸 200 是更强的证据。"""
    healthy, detail = _poll_seeing(401)
    assert healthy
    assert "gated" in detail


@pytest.mark.parametrize("status", [500, 502, 404])
def test_a_broken_server_is_still_reported_broken(status):
    healthy, detail = _poll_seeing(status, timeout=1)
    assert not healthy
    assert str(status) in detail
