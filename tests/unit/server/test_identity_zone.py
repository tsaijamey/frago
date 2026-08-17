"""第四区能到哪，不能到哪——这张白名单是个闭集。

`Risk` 表把「身份区被误开成弱化的主人」这个 high 风险，整个托付给了
「可达路径用白名单而非黑名单」这一条机制。白名单只有被逐行断言过，
才算真的是白名单；否则它只是一份写在注释里的意图。

新增端点默认落私有区。要进这张表必须先改 spec，然后这里加一行——
如果有人加了端点却没动这个文件，`test_the_list_has_not_quietly_grown`
会把它拦下来。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.server import identity as ident
from frago.server import security

VISITOR = ("93.184.216.34", 41234)
OWNER = ("127.0.0.1", 41234)
GOOD_PASSWORD = "correct-horse-battery-staple"

# spec「四区：各自的 slot 从哪来、能看多少」那张表的机器可读版本。
IDENTITY_MAY_REACH = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/password"),
    ("GET", "/api/auth/me"),
}

# 身份区绝不能碰的，每一条都等价于在这台机器上执行代码。
AMOUNTS_TO_CODE_EXECUTION = [
    ("GET", "/api/file?path=/etc/passwd"),
    ("POST", "/api/file?path=/tmp/x"),
    ("POST", "/api/agent"),
    ("POST", "/api/agent/attached"),
    ("POST", "/api/recipes/anything/run"),
    ("POST", "/api/recipes/anything/run-async"),
    ("POST", "/api/pa/chat"),
]


@pytest.fixture
def app(tmp_path, monkeypatch):
    from frago.server.app import create_app

    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "app-state-users")
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    security.ensure_token()
    ident.reset_rate_limits()
    yield create_app()
    ident.reset_rate_limits()


@pytest.fixture
def visitor(app):
    client = TestClient(app, client=VISITOR)
    client.post("/api/auth/login", json={"email": "a@x.com", "password": GOOD_PASSWORD})
    return client


class TestTheClosedList:
    def test_the_list_has_not_quietly_grown(self):
        """加端点很容易，加进匿名区或身份区应该很难。

        这条不测行为，测的是「有没有人在没改 spec 的情况下动了这张表」。
        改动是合法的，但必须是被看见的改动。
        """
        assert security._IDENTITY_ENDPOINTS >= IDENTITY_MAY_REACH
        extra = {
            (method, path)
            for method, path in security._IDENTITY_ENDPOINTS
            if (method, path) not in IDENTITY_MAY_REACH and method != "HEAD"
        }
        assert not extra, f"身份区白名单多了没在 spec 里的条目：{extra}"

    def test_the_anonymous_list_holds_exactly_one_door(self):
        """攻击面按「匿名能触发的动作」数。多一个就要重新论证一次。"""
        assert set(security._ANON_POST) == {("POST", "/api/auth/login")}

    def test_the_anonymous_list_does_not_contain_a_preflight(self):
        assert not any(method == "OPTIONS" for method, _ in security._ANON_POST)


class TestASignedInVisitorIsNotAWeakenedOwner:
    @pytest.mark.parametrize(("method", "path"), AMOUNTS_TO_CODE_EXECUTION)
    def test_code_execution_stays_behind_the_token(self, visitor, method, path):
        assert visitor.request(method, path).status_code == 401

    @pytest.mark.parametrize(
        "path", ["/api/status", "/api/recipes", "/api/settings", "/viewer/", "/browser/", "/"]
    )
    def test_the_rest_of_the_server_is_not_thrown_in(self, visitor, path):
        assert visitor.get(path).status_code == 401

    def test_the_websocket_is_not_part_of_the_bargain(self, visitor):
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect), visitor.websocket_connect("/ws"):
            pass


class TestWhatTheZoneDoesGive:
    def test_the_endpoints_on_the_list_answer(self, visitor):
        assert visitor.get("/api/auth/me").status_code == 200

    def test_signing_out_is_reachable_while_signed_in(self, visitor):
        assert visitor.post("/api/auth/logout", json={}).status_code == 200


class TestTheOwnerIsUnaffected:
    def test_loopback_still_reaches_everything(self, app):
        owner = TestClient(app, client=OWNER)
        assert owner.get("/api/status").status_code == 200
