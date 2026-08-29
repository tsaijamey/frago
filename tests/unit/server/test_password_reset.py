"""主人重置了某人的密码之后，那个人还能做什么。

答案是：只能改密码。这一条不是界面上的约定，是网关的判定——重置过的账号手里
握着一段主人给的临时口令，而那段口令主人自己也知道，所以在它被换掉之前，这个
会话不该能打开任何一张页面，也不该能读出「这台机器上有哪些页面」。

前一版没有这层：`frago user passwd` 换完口令就结束了，主人给出去的那段字符串
从此就是一个完整可用的密码，没人被要求换掉它。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

PORTAL = "frago_login_portal"
MINE = "per_person_page"

VISITOR = ("93.184.216.34", 41234)
OWNER = ("127.0.0.1", 41234)
HTML = {"Accept": "text/html,application/xhtml+xml"}
EMAIL = "a@x.com"
FIRST_PASSWORD = "correct-horse-battery-staple"
CHOSEN_PASSWORD = "a-password-of-my-very-own"


@pytest.fixture
def site(tmp_path, monkeypatch):
    """一张要登录的页面、一张公开的门口，外加一份空的账号表。"""
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "users")
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    security.ensure_token()
    ident.reset_rate_limits()

    recipes = tmp_path / "recipes"
    for name in (PORTAL, MINE):
        assets = recipes / name / "assets"
        assets.mkdir(parents=True)
        (assets / "index.html").write_text(f"<h1>{name}</h1>", encoding="utf-8")

    class _Recipe:
        def __init__(self, name):
            self.base_dir = recipes / name
            self.script_path = recipes / name / "recipe.py"
            self.metadata = type("M", (), {"ui_from": None, "description": name})()

    class _Registry:
        def find(self, name):
            if name not in (PORTAL, MINE):
                raise RecipeNotFoundError(name)
            return _Recipe(name)

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    pub.publish(PORTAL, mode=pub.MODE_PUBLIC)
    pub.publish(MINE, mode=pub.MODE_IDENTITY)

    from frago.server.app import create_app

    yield create_app()
    ident.reset_rate_limits()


def _sign_in(client, password):
    return client.post("/api/auth/login", json={"email": EMAIL, "password": password})


@pytest.fixture
def reset(site):
    """一个用过这台机器的人，密码刚被主人重置。返回 (客户端, 临时口令)。"""
    client = TestClient(site, client=VISITOR, follow_redirects=False)
    _sign_in(client, FIRST_PASSWORD)
    account = ident.find_user_by_email(EMAIL)
    temporary = ident.issue_temporary_password(account.id)
    client.cookies.clear()          # 重置把会话全断了，浏览器手里那张也一样
    _sign_in(client, temporary)
    return client, temporary


class TestTheResetItself:
    def test_the_password_the_owner_replaced_stops_working(self, site):
        client = TestClient(site, client=VISITOR)
        _sign_in(client, FIRST_PASSWORD)
        ident.issue_temporary_password(ident.find_user_by_email(EMAIL).id)
        client.cookies.clear()
        assert _sign_in(client, FIRST_PASSWORD).status_code == 401

    def test_the_sessions_made_with_it_die_too(self, site):
        """重置的用途就是「那把钥匙该失效了」。只换口令、不断会话，
        等于偷了 cookie 的人照样在里面。"""
        client = TestClient(site, client=VISITOR)
        _sign_in(client, FIRST_PASSWORD)
        assert client.get("/api/auth/me").status_code == 200
        ident.issue_temporary_password(ident.find_user_by_email(EMAIL).id)
        assert client.get("/api/auth/me").status_code == 401

    def test_the_temporary_password_signs_in(self, reset):
        client, _ = reset
        assert client.get("/api/auth/me").status_code == 200

    def test_the_answer_says_a_change_is_owed(self, reset):
        """页面靠这一个字段决定给人看哪张脸，登录和 /me 两条路都要说。"""
        client, _ = reset
        assert client.get("/api/auth/me").json()["mustChangePassword"] is True


class TestWhatAResetAccountCannotReach:
    def test_the_page_list_is_withheld(self, reset):
        """名单本身也是要保护的东西：手里拿着一段主人给的口令的人，
        在换掉它之前连「这台机器上开了哪些页面」都不该读到。

        401 而不是 403：网关对「你不能到这儿」只有一种说法，和名单外的人、
        和根本没发布的页面，收到的是同一句话。"""
        client, _ = reset
        assert client.get("/api/auth/pages").status_code == 401

    def test_a_page_this_account_is_allowed_on_is_still_shut(self, reset):
        client, _ = reset
        assert client.get(f"/app/{MINE}/").status_code in (302, 401)

    def test_a_browser_is_sent_to_the_door_rather_than_refused(self, reset):
        """被挡住之后要有下一步。门口那张页面会告诉他欠一次改密。"""
        client, _ = reset
        response = client.get(f"/app/{MINE}/", headers=HTML)
        assert response.status_code == 302
        assert response.headers["location"] == f"/app/{PORTAL}/?next={MINE}"

    def test_the_lock_holds_for_a_caller_that_is_not_a_browser(self, site, reset):
        """页面上那张「必须改密码」的界面挡不住 curl——会话是真的，cookie 也是真的。
        所以这里拿着同一张 cookie 另起一个客户端，断言网关照样不放行。"""
        client, _ = reset
        cookie = client.cookies.get(ident.COOKIE_NAME)
        assert cookie
        bare = TestClient(site, client=VISITOR)
        bare.cookies.set(ident.COOKIE_NAME, cookie)
        assert bare.get("/api/auth/pages").status_code == 401
        assert bare.get(f"/app/{MINE}/").status_code == 401

    def test_signing_out_still_works(self, reset):
        """把人锁在一个连退出都点不动的界面里，是另一种死锁。"""
        client, _ = reset
        assert client.post("/api/auth/logout", json={}).status_code == 200


class TestChangingItLiftsTheLock:
    def _change(self, client, current, new):
        return client.post(
            "/api/auth/password", json={"current_password": current, "new_password": new}
        )

    def test_the_change_itself_is_allowed(self, reset):
        client, temporary = reset
        assert self._change(client, temporary, CHOSEN_PASSWORD).status_code == 200

    def test_retyping_the_temporary_one_is_not_a_change(self, reset):
        """不拦这条，「必须换掉」就等于「必须把主人给的那段再敲一遍」。"""
        client, temporary = reset
        response = self._change(client, temporary, temporary)
        assert response.status_code == 400
        assert response.json()["error"] == "same_password"

    def test_the_pages_come_back(self, reset):
        client, temporary = reset
        self._change(client, temporary, CHOSEN_PASSWORD)
        assert client.get("/api/auth/pages").status_code == 200
        assert client.get(f"/app/{MINE}/").status_code == 200

    def test_me_stops_asking_for_a_change(self, reset):
        client, temporary = reset
        self._change(client, temporary, CHOSEN_PASSWORD)
        assert client.get("/api/auth/me").json()["mustChangePassword"] is False

    def test_the_temporary_password_no_longer_signs_anyone_in(self, reset):
        client, temporary = reset
        self._change(client, temporary, CHOSEN_PASSWORD)
        client.post("/api/auth/logout", json={})
        client.cookies.clear()
        assert _sign_in(client, temporary).status_code == 401
        assert _sign_in(client, CHOSEN_PASSWORD).status_code == 200


class TestTheRouteSaysItAgainForTheOwnersOwnBrowser:
    """本机那条路根本不走网关的身份分支——它是 local 区，一路放行。

    所以「重置过的账号读不到页面清单」在路由里还得再写一遍。少了那一遍，主人
    自己浏览器里躺着的那张 cookie 就能把这份清单读出来。
    """

    def test_the_route_refuses_and_says_why(self, site):
        visitor = TestClient(site, client=VISITOR)
        _sign_in(visitor, FIRST_PASSWORD)
        temporary = ident.issue_temporary_password(ident.find_user_by_email(EMAIL).id)

        # 从本机登进来，手里就是一张被锁账号的活会话——这条请求走 local 区。
        owner = TestClient(site, client=OWNER)
        _sign_in(owner, temporary)

        response = owner.get("/api/auth/pages")
        assert response.status_code == 403
        assert response.json()["error"] == "password_reset_required"


class TestTheOwnerIsNotLockedOut:
    def test_the_owners_own_machine_still_reaches_the_server(self, site):
        """锁的是那个访客账号，不是这台机器。主人的浏览器里可能正好躺着
        那个账号的 cookie——不能因此把主人自己关在外面。"""
        client = TestClient(site, client=VISITOR)
        _sign_in(client, FIRST_PASSWORD)
        ident.issue_temporary_password(ident.find_user_by_email(EMAIL).id)
        owner = TestClient(site, client=OWNER)
        assert owner.get("/api/status").status_code == 200
