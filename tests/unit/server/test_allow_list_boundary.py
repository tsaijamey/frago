"""An allow list only means something if the gate reads it.

`test_publish_allow.py` proves the field parses correctly. That is the easy
half, and on its own it proves nothing: until this change the gate asked only
whether a page was published at all, so an allow list could have been written,
displayed, and had no effect on a single request.

These run the real `create_app()` from a public source address, so the answer
comes from the middleware rather than from a helper called directly.
"""

import json

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

PAGE = "board"
PASSWORD = "correct-horse-battery"
VISITOR = ("93.184.216.34", 41234)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_BEHIND_PROXY", "1")
    monkeypatch.setenv("FRAGO_TRUST_LAN", "0")
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    for leak in ("FRAGO_USERS_FILE", "FRAGO_SESSIONS_DIR", "FRAGO_SIGNUP_GATE"):
        monkeypatch.delenv(leak, raising=False)
    security.ensure_token()
    ident.reset_rate_limits()

    assets = tmp_path / "recipes" / PAGE / "assets"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("<h1>board</h1>", encoding="utf-8")

    class _Meta:
        ui_from = None

    class _Recipe:
        base_dir = tmp_path / "recipes" / PAGE
        script_path = tmp_path / "recipes" / PAGE / "recipe.py"
        metadata = _Meta()

    class _Registry:
        def find(self, name, source=None):
            if name != PAGE:
                raise RecipeNotFoundError(name, [])
            return _Recipe()

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)
        app_state.publish(PAGE, {"public": {"who": who}}, slot=user.id, identity=True)
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}

    yield people
    ident.reset_rate_limits()


def _client(cookie=None):
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    if cookie:
        client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


def _raw(entry):
    pub.published_path().write_text(json.dumps({PAGE: entry}), encoding="utf-8")
    pub._cache = None


class TestTheGateConsultsTheList:
    def test_someone_on_the_list_gets_in(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        r = _client(world["zhang"]["cookie"]).get(f"/app/{PAGE}/config.json")
        assert r.status_code == 200
        assert r.json()["who"] == "zhang"

    def test_someone_off_the_list_does_not(self, world):
        """Signed in, valid session, real account — and still refused, because
        the only question that matters here is the list."""
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        r = _client(world["li"]["cookie"]).get(f"/app/{PAGE}/config.json")
        assert r.status_code == 401

    def test_no_list_still_means_every_signed_in_visitor(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY)
        for who in ("zhang", "li"):
            assert _client(world[who]["cookie"]).get(
                f"/app/{PAGE}/config.json"
            ).status_code == 200

    def test_the_page_files_are_covered_too_not_just_the_config(self, world):
        """Refusing config.json while serving assets would leak the page and,
        through `data/`, whatever it renders."""
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        off = _client(world["li"]["cookie"])
        assert off.get(f"/app/{PAGE}/").status_code == 401
        assert off.get(f"/app/{PAGE}/index.html").status_code == 401
        assert off.get(f"/app/{PAGE}/data/rows.json").status_code == 401


class TestOffTheListLooksExactlyLikeUnpublished:
    def test_same_status_and_same_body(self, world):
        """A 403 here would confirm to an outsider that the page exists and
        that somebody, somewhere, is on its list."""
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        refused = _client(world["li"]["cookie"]).get(f"/app/{PAGE}/config.json")

        pub.unpublish(PAGE)
        unpublished = _client(world["li"]["cookie"]).get(f"/app/{PAGE}/config.json")

        assert refused.status_code == unpublished.status_code == 401
        assert refused.text == unpublished.text

    def test_and_like_a_page_that_never_existed(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        client = _client(world["li"]["cookie"])
        refused = client.get(f"/app/{PAGE}/config.json")
        never = client.get("/app/no_such_recipe_at_all/config.json")
        assert refused.status_code == never.status_code == 401


class TestDamagedEntriesShutTheDoor:
    def test_an_empty_list_lets_nobody_in(self, world):
        _raw({"slot": "default", "mode": "identity", "allow": []})
        for who in ("zhang", "li"):
            assert _client(world[who]["cookie"]).get(
                f"/app/{PAGE}/config.json"
            ).status_code == 401

    def test_an_unreadable_list_lets_nobody_in(self, world):
        _raw({"slot": "default", "mode": "identity", "allow": "zhang"})
        assert _client(world["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json"
        ).status_code == 401


class TestTheOtherBranchStillWorks:
    def test_a_public_page_is_unaffected_by_any_of_this(self, world):
        """Public pages are admitted by a different branch. This is the
        regression that a careless "add a check to the identity path" would
        cause: the list is identity-only, and public must not start consulting
        it or stop working."""
        app_state.publish(PAGE, {"public": {"who": "everyone"}})
        pub.publish(PAGE, mode=pub.MODE_PUBLIC)
        r = _client().get(f"/app/{PAGE}/config.json")
        assert r.status_code == 200
        assert r.json()["who"] == "everyone"

    def test_anonymous_still_cannot_open_an_identity_page(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY)
        assert _client().get(f"/app/{PAGE}/config.json").status_code == 401

    def test_a_visitor_on_the_list_still_cannot_name_a_slot(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        other = world["li"]["id"]
        assert _client(world["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json?key={other}"
        ).status_code == 401

    def test_running_code_is_still_out_of_reach_for_the_allowed(self, world):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        client = _client(world["zhang"]["cookie"])
        assert client.post(f"/api/recipes/{PAGE}/run", json={}).status_code == 401
        assert client.get("/api/file", params={"path": "/etc/passwd"}).status_code == 401
