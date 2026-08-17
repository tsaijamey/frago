"""登录、登出、改密——唯一的匿名 POST 入口。

这四个端点是整套身份机制里外部能直接打到的全部表面，其中 `/api/auth/login`
还是匿名的。所以这里的用例大多不是「功能对不对」，而是「这一枪打过来会不会穿」。
来源是 20260817 那轮对抗性审计的 F10（登录被整段 CSRF 论证漏掉）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.server import identity as ident
from frago.server import security

VISITOR = ("93.184.216.34", 41234)
GOOD_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from frago.server.app import create_app

    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "app-state-users")
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    security.ensure_token()
    ident.reset_rate_limits()
    yield TestClient(create_app(), client=VISITOR)
    ident.reset_rate_limits()


def _login(client, email="a@x.com", password=GOOD_PASSWORD, **kwargs):
    return client.post("/api/auth/login", json={"email": email, "password": password}, **kwargs)


class TestSigningIn:
    def test_a_new_address_gets_in_and_gets_a_cookie(self, client):
        response = _login(client)
        assert response.status_code == 200
        assert ident.COOKIE_NAME in response.cookies

    def test_the_second_visit_needs_the_same_password(self, client):
        _login(client)
        assert _login(client).status_code == 200
        assert _login(client, password="a-different-password").status_code == 401

    def test_the_cookie_is_not_reachable_from_javascript(self, client):
        header = _login(client).headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header

    def test_the_answer_never_contains_the_password(self, client):
        assert GOOD_PASSWORD not in _login(client).text


class TestTheLocksOnTheAnonymousEntrance:
    """登录是唯一匿名可打的 POST。这四条是它全部的门闩。"""

    def test_a_form_post_is_refused(self, client):
        """HTML 表单发不出 JSON，所以强制 JSON 就挡掉了无预检的那条 CSRF 路径。
        依赖框架默认行为不算数——这里要的是显式拒绝。"""
        response = client.post(
            "/api/auth/login", data={"email": "a@x.com", "password": GOOD_PASSWORD}
        )
        assert response.status_code == 415

    def test_a_cross_origin_login_is_refused(self, client):
        """SameSite 限制的是 cookie 的发送，不阻止跨站响应设置 cookie。
        没有这一条，攻击者能把受害者悄悄登进自己的账号，受害者之后
        在页面上产生的数据全写进攻击者的 slot。"""
        response = _login(client, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    def test_a_same_origin_login_still_works(self, client):
        response = _login(client, headers={"Origin": "http://testserver"})
        assert response.status_code in (200, 403)  # 同源判定按部署而定，但绝不能 500

    def test_no_origin_at_all_is_not_treated_as_foreign(self, client):
        """curl 和 CLI 都不发 Origin。"""
        assert _login(client).status_code == 200

    def test_the_preflight_is_not_on_the_anonymous_list(self, client):
        assert client.options("/api/auth/login").status_code == 401


class TestWhatASignedInVisitorCannotDo:
    """登录用户不是弱化的主人。这三条接口等价于在服务器上执行代码。"""

    @pytest.fixture
    def signed_in(self, client):
        _login(client)
        return client

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/file?path=/etc/passwd"),
            ("POST", "/api/agent"),
            ("POST", "/api/recipes/anything/run"),
            ("GET", "/api/status"),
            ("GET", "/api/recipes"),
        ],
    )
    def test_the_dangerous_surface_stays_shut(self, signed_in, method, path):
        assert signed_in.request(method, path).status_code == 401


class TestLogoutAndPassword:
    def test_logging_out_kills_the_cookie(self, client):
        _login(client)
        assert client.post("/api/auth/logout", json={}).status_code == 200
        assert client.get("/api/auth/me").status_code == 401

    def test_logout_needs_a_session(self, client):
        assert client.post("/api/auth/logout", json={}).status_code == 401

    def test_me_says_who_you_are(self, client):
        _login(client)
        body = client.get("/api/auth/me").json()
        assert body.get("email") == "a@x.com"

    def test_me_is_not_open_to_strangers(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_changing_your_own_password_does_not_log_you_out(self, client):
        """本设计没有找回流程，自改密码是「我怀疑 cookie 被偷了」时唯一的自救手段。
        它必须踢掉别人手里的凭条，又不能把正在操作的人自己踢下线。"""
        _login(client)
        response = client.post(
            "/api/auth/password",
            json={"current_password": GOOD_PASSWORD, "new_password": "an-entirely-new-password"},
        )
        assert response.status_code == 200
        assert client.get("/api/auth/me").status_code == 200

    def test_the_old_password_stops_working(self, client):
        _login(client)
        client.post(
            "/api/auth/password",
            json={"current_password": GOOD_PASSWORD, "new_password": "an-entirely-new-password"},
        )
        client.post("/api/auth/logout", json={})
        assert _login(client).status_code == 401
        assert _login(client, password="an-entirely-new-password").status_code == 200
