"""CDP transport primitives: proxy-bypassed HTTP/WebSocket for local CDP endpoints.

CDP endpoints live on localhost. If HTTP_PROXY / HTTPS_PROXY is set (common
with v2rayA / clash / ssh -D setups), Python's requests and websocket-client
route even localhost through the proxy and fail with opaque 404/502/handshake
errors. Every CDP caller MUST go through this module so the proxy-bypass
policy lives in one place.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any

import requests
import websocket

# trust_env=False skips HTTP_PROXY / HTTPS_PROXY / NO_PROXY entirely,
# so a shared Session is safe regardless of the user's shell env.
_session = requests.Session()
_session.trust_env = False

# websocket-client ≤1.9 reads HTTP_PROXY/HTTPS_PROXY from env unconditionally:
# http_no_proxy=["*"] and http_proxy_host=None at the parameter level do NOT
# override it. The only reliable bypass is to remove those env vars for the
# duration of the handshake. _WS_ENV_LOCK keeps concurrent callers from
# racing on os.environ mutation.
_WS_ENV_LOCK = threading.Lock()
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "WS_PROXY", "ws_proxy",
)


@contextmanager
def _scrub_proxy_env():
    with _WS_ENV_LOCK:
        saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
        try:
            yield
        finally:
            os.environ.update(saved)


def cdp_get(url: str, *, timeout: float = 5.0, **kwargs: Any) -> requests.Response:
    """GET a CDP HTTP endpoint. Proxy env vars are always bypassed."""
    return _session.get(url, timeout=timeout, **kwargs)


def cdp_ws_connect(ws_url: str, *, timeout: float = 5.0, **options: Any) -> websocket.WebSocket:
    """Open a CDP WebSocket. Proxy env vars are always bypassed."""
    options.setdefault("timeout", timeout)
    with _scrub_proxy_env():
        return websocket.create_connection(ws_url, **options)
