"""The door page's listing, computed for whoever is asking.

Before allow lists a listing could be a snapshot: everyone who loaded the door
saw the same cards. Once pages open to named accounts that breaks both ways —
a visitor gets a card that 401s, or the card itself announces that a page exists
and that somebody is on its list.

So the two things being pinned here are that the answer differs by caller, and
that it never contains the roster.
"""

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

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

    titles = {"ledger": "A running account book", "board": "The signals board"}

    class _Registry:
        def find(self, name, source=None):
            if name not in titles:
                raise RecipeNotFoundError(name, [])

            class _Meta:
                description = titles[name]
                ui_from = None
                # What the recipe opened to its own page. The card's `runnable`
                # is this, narrowed by how the page was exposed — never the
                # exposure entry on its own.
                page_actions = ["save"]

            class _Recipe:
                base_dir = tmp_path / "recipes" / name
                script_path = tmp_path / "recipes" / name / "recipe.py"
                metadata = _Meta()

            return _Recipe()

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}

    yield people
    ident.reset_rate_limits()


def _client(cookie=None):
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    if cookie:
        client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


def _pages(cookie):
    r = _client(cookie).get("/api/auth/pages")
    assert r.status_code == 200, r.text
    return r.json()["pages"]


class TestTheAnswerDependsOnWhoAsks:
    def test_a_page_open_to_one_person_is_listed_only_for_them(self, world):
        pub.publish("ledger", mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        assert [p["recipe"] for p in _pages(world["zhang"]["cookie"])] == ["ledger"]
        assert _pages(world["li"]["cookie"]) == []

    def test_a_page_open_to_everyone_signed_in_is_listed_for_both(self, world):
        pub.publish("board", mode=pub.MODE_IDENTITY)
        for who in ("zhang", "li"):
            assert [p["recipe"] for p in _pages(world[who]["cookie"])] == ["board"]

    def test_each_person_sees_their_own_mixture(self, world):
        pub.publish("ledger", mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        pub.publish("board", mode=pub.MODE_IDENTITY)
        assert sorted(p["recipe"] for p in _pages(world["zhang"]["cookie"])) == [
            "board", "ledger"
        ]
        assert [p["recipe"] for p in _pages(world["li"]["cookie"])] == ["board"]

    def test_a_public_page_is_not_in_this_list(self, world):
        """This answers "which pages are mine", and a public page is nobody's in
        particular — it needs no sign-in to reach and no card to unlock."""
        pub.publish("board", mode=pub.MODE_PUBLIC)
        assert _pages(world["zhang"]["cookie"]) == []


class TestWhatItRefusesToSay:
    def test_it_never_carries_the_allow_list(self, world):
        """Who else may open a page is not this visitor's business, and an
        endpoint that answered it would hand every signed-in stranger the
        roster."""
        pub.publish("ledger", mode=pub.MODE_IDENTITY, allow=[world["zhang"]["id"]])
        body = _client(world["zhang"]["cookie"]).get("/api/auth/pages").text
        assert "allow" not in body
        assert world["li"]["id"] not in body

    def test_the_fields_are_exactly_what_a_card_needs(self, world):
        pub.publish("ledger", mode=pub.MODE_IDENTITY)
        page = _pages(world["zhang"]["cookie"])[0]
        assert set(page) == {"recipe", "title", "runnable", "path"}
        assert page["title"] == "A running account book"
        assert page["runnable"] is True

    def test_a_shared_reading_is_listed_as_read_only(self, world):
        """The recipe opened an action, but nobody on this page has a directory
        of their own for it to write into."""
        pub.publish("ledger", mode=pub.MODE_IDENTITY, reads=pub.READS_RECIPE)
        assert _pages(world["zhang"]["cookie"])[0]["runnable"] is False

    def test_anonymous_is_told_nothing_at_all(self, world):
        pub.publish("ledger", mode=pub.MODE_IDENTITY)
        assert _client().get("/api/auth/pages").status_code == 401


class TestStaleAndBrokenEntries:
    def test_a_published_but_uninstalled_recipe_is_listed_by_name(self, world):
        """Better a card the owner can see is dead than a page that quietly
        vanishes from the door while still being published."""
        pub.publish("gone_away", mode=pub.MODE_IDENTITY)
        page = _pages(world["zhang"]["cookie"])[0]
        assert page["recipe"] == "gone_away"
        assert page["title"] == "gone_away"

    def test_an_entry_nobody_may_open_is_listed_for_nobody(self, world):
        import json

        pub.published_path().write_text(
            json.dumps({"ledger": {"slot": "default", "mode": "identity", "allow": []}}),
            encoding="utf-8",
        )
        pub._cache = None
        assert _pages(world["zhang"]["cookie"]) == []
