"""Tests for Chrome extension CORS allowance and AccessZoneMiddleware boundaries."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from frago.server import security
from frago.server.app import create_app

EXT_ORIGIN = "chrome-extension://eajjhcepifleiifebabkjmhampcephfp"
LOCAL_PEER = ("127.0.0.1", 51234)
REMOTE_PEER = ("93.184.216.34", 51234)


@pytest.fixture
def server_token(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    return security.ensure_token()


@pytest.fixture
def app():
    return create_app(version="0.0.0-test")


def test_extension_preflight_options_allowed_on_local(app, server_token):
    client = TestClient(app, client=LOCAL_PEER)
    resp = client.options(
        "/api/workbench/sessions",
        headers={
            "Origin": EXT_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == EXT_ORIGIN
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_extension_get_and_post_allowed_on_local(app, server_token):
    client = TestClient(app, client=LOCAL_PEER)

    get_resp = client.get("/api/info", headers={"Origin": EXT_ORIGIN})
    assert get_resp.status_code == 200
    assert get_resp.headers.get("access-control-allow-origin") == EXT_ORIGIN

    post_resp = client.post(
        "/api/workbench/sessions/not-a-real-session-id/send",
        headers={"Origin": EXT_ORIGIN, "Content-Type": "application/json"},
        json={"text": "", "wait": False},
    )
    # Reaches route validation (not blocked by CORS or AccessZoneMiddleware).
    assert post_resp.status_code == 400
    assert post_resp.headers.get("access-control-allow-origin") == EXT_ORIGIN

    queue_resp = client.post(
        "/api/workbench/sessions/not-a-real-session-id/queue",
        headers={"Origin": EXT_ORIGIN, "Content-Type": "application/json"},
        json={"text": "hello"},
    )
    assert queue_resp.status_code == 404
    assert queue_resp.headers.get("access-control-allow-origin") == EXT_ORIGIN

    records_resp = client.get(
        "/api/workbench/sessions/not-a-real-session-id/records?limit=20&tail=true",
        headers={"Origin": EXT_ORIGIN},
    )
    assert records_resp.status_code == 404
    assert records_resp.headers.get("access-control-allow-origin") == EXT_ORIGIN

    queue_get_resp = client.get(
        "/api/workbench/sessions/not-a-real-session-id/queue",
        headers={"Origin": EXT_ORIGIN},
    )
    assert queue_get_resp.status_code == 404
    assert queue_get_resp.headers.get("access-control-allow-origin") == EXT_ORIGIN


def test_extension_origin_blocked_without_token_from_remote(app, server_token):
    remote_client = TestClient(app, client=REMOTE_PEER)

    opt_resp = remote_client.options(
        "/api/workbench/sessions",
        headers={
            "Origin": EXT_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert opt_resp.status_code == 401

    get_resp = remote_client.get("/api/info", headers={"Origin": EXT_ORIGIN})
    assert get_resp.status_code == 401

    post_resp = remote_client.post(
        "/api/workbench/sessions/not-a-real-session-id/send",
        headers={"Origin": EXT_ORIGIN, "Content-Type": "application/json"},
        json={"text": "hello", "wait": False},
    )
    assert post_resp.status_code == 401


def test_extension_origin_allowed_from_remote_with_valid_token(app, server_token):
    remote_client = TestClient(app, client=REMOTE_PEER)
    resp = remote_client.get(
        "/api/info",
        headers={
            "Origin": EXT_ORIGIN,
            "Authorization": f"Bearer {server_token}",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == EXT_ORIGIN


def test_malformed_extension_or_untrusted_origin_rejected_by_cors(app, server_token):
    client = TestClient(app, client=LOCAL_PEER)
    for bad_origin in (
        "chrome-extension://short",
        "chrome-extension://UPPERCASEIDAAAAAAAAAAAAAAAAAAAAA",
        "https://evil.example.com",
    ):
        resp = client.options(
            "/api/workbench/sessions",
            headers={
                "Origin": bad_origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 400
        assert "access-control-allow-origin" not in resp.headers


def _receive_until_pong(ws) -> list[dict]:
    seen: list[dict] = []
    for _ in range(10):
        msg = ws.receive_json()
        seen.append(msg)
        if msg.get("type") == "pong":
            return seen
    raise AssertionError(f"did not receive pong; got {seen!r}")


def test_extension_websocket_allowed_on_local(app, server_token):
    client = TestClient(app, client=LOCAL_PEER)
    with client.websocket_connect("/ws", headers={"Origin": EXT_ORIGIN}) as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "connected"
        ws.send_json({"type": "ping"})
        _receive_until_pong(ws)


def test_extension_websocket_remote_requires_token(app, server_token):
    from starlette.websockets import WebSocketDisconnect

    remote_client = TestClient(app, client=REMOTE_PEER)
    with pytest.raises(WebSocketDisconnect):
        with remote_client.websocket_connect("/ws", headers={"Origin": EXT_ORIGIN}):
            pass

    with remote_client.websocket_connect(
        f"/ws?token={server_token}", headers={"Origin": EXT_ORIGIN}
    ) as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "connected"
        ws.send_json({"type": "ping"})
        _receive_until_pong(ws)
