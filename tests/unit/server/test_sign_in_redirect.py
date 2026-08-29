"""What a signed-out person sees when they open a page that needs a sign-in.

Before this, they got the gate's JSON refusal — ``{"error": "unauthorized",
"detail": "this endpoint is not public"}`` — rendered raw in the browser. It is
written for a machine: it names a bearer token and a CLI command, neither of
which a visitor has or should have. The person's actual next step is to sign in,
and the server knows where the door is, so it now takes them there.

The cases below are the ways that redirect could do harm rather than good: by
answering a data call with a login page, by claiming a sign-in would help when
it would not, or by bouncing between two addresses that both refuse.
"""

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import security

PORTAL = "frago_login_portal"
MINE = "per_person_page"
OPEN = "open_page"

VISITOR = ("93.184.216.34", 41234)
HTML = {"Accept": "text/html,application/xhtml+xml"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A portal open to anyone, a page that needs a sign-in, and one that does not."""
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    security.ensure_token()

    recipes = tmp_path / "recipes"
    for name in (PORTAL, MINE, OPEN):
        assets = recipes / name / "assets"
        assets.mkdir(parents=True)
        (assets / "index.html").write_text(f"<h1>{name}</h1>", encoding="utf-8")

    class _Recipe:
        def __init__(self, name):
            self.base_dir = recipes / name
            self.script_path = recipes / name / "recipe.py"
            self.metadata = type("M", (), {"ui_from": None})()

    class _Registry:
        def find(self, name):
            if name not in (PORTAL, MINE, OPEN):
                raise RecipeNotFoundError(name)
            return _Recipe(name)

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    pub.publish(PORTAL, mode=pub.MODE_PUBLIC)
    pub.publish(MINE, mode=pub.MODE_IDENTITY)
    pub.publish(OPEN, mode=pub.MODE_PUBLIC)

    from frago.server.app import create_app

    client = TestClient(create_app(), client=VISITOR, follow_redirects=False)
    return client


class TestThePersonIsTakenToTheDoor:
    def test_a_browser_asking_for_a_sign_in_page_is_sent_to_the_portal(self, site):
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.status_code == 302
        assert r.headers["location"] == f"/app/{PORTAL}/?next={MINE}"

    def test_the_redirect_is_not_cached(self, site):
        # Whether this address refuses depends on who is asking. A cached
        # redirect would keep sending someone to the login page after they
        # had already signed in.
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.headers["cache-control"] == "no-store"

    def test_a_file_under_the_page_is_sent_too(self, site):
        # Someone who bookmarked a deep link is still a person at a locked door.
        r = site.get(f"/app/{MINE}/style.css", headers=HTML)
        assert r.status_code == 302


class TestWhatMustStillBeRefusedOutright:
    def test_a_data_call_gets_json_not_a_login_page(self, site):
        # The page's own fetch() asks for JSON. Handing it a login page would
        # surface as a parse error somewhere unrelated to the real cause.
        r = site.get(f"/app/{MINE}/config.json", headers={"Accept": "application/json"})
        assert r.status_code == 401
        assert r.json()["error"] == "unauthorized"

    def test_a_caller_that_states_no_preference_gets_json(self, site):
        r = site.get(f"/app/{MINE}/", headers={"Accept": "*/*"})
        assert r.status_code == 401

    def test_the_api_is_never_redirected(self, site):
        r = site.get("/api/recipes", headers=HTML)
        assert r.status_code == 401

    def test_an_unpublished_page_is_not_dressed_up_as_a_sign_in(self, site):
        # Signing in would not open this: saying otherwise sends the person
        # through a login for nothing and tells them the page exists.
        r = site.get("/app/nosuchapp/", headers=HTML)
        assert r.status_code == 401

    def test_a_write_is_refused_rather_than_moved(self, site):
        r = site.post(f"/app/{MINE}/run", headers=HTML, json={})
        assert r.status_code == 401


class TestNoLoop:
    def test_the_portal_never_redirects_to_itself(self, site):
        # It is public, so it is served; the point is that it is never a target
        # of its own redirect even when something else refuses.
        assert site.get(f"/app/{PORTAL}/", headers=HTML).status_code == 200

    def test_without_a_portal_the_refusal_is_plain(self, site, monkeypatch):
        monkeypatch.setenv("FRAGO_LOGIN_PORTAL", "")
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.status_code == 401

    def test_a_portal_that_is_not_open_is_not_a_destination(self, site, monkeypatch):
        # Sending a signed-out visitor to a door that also refuses them would
        # be a 401 with extra steps.
        pub.publish(PORTAL, mode=pub.MODE_IDENTITY)
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.status_code == 401

    def test_a_named_portal_that_was_never_published_is_not_a_destination(
        self, site, monkeypatch
    ):
        monkeypatch.setenv("FRAGO_LOGIN_PORTAL", "ghost_door")
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.status_code == 401


class TestWhichPageIsTheDoor:
    """The door is a registered decision, not a name compiled into the gate.

    It used to be `DEFAULT_LOGIN_PORTAL` in security.py with an environment
    override. Three things were wrong with that and all three were silent:
    `frago recipe exposed` could not show it, renaming the page broke every
    redirect with no error anywhere, and the access layer — which is supposed to
    know about zones — knew a recipe's name by heart.
    """

    def test_a_page_registered_as_the_portal_becomes_the_destination(self, site):
        pub.publish(OPEN, mode=pub.MODE_PUBLIC, portal=True)
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.headers["location"] == f"/app/{OPEN}/?next={MINE}"

    def test_the_registry_is_visible_where_every_other_decision_is(self, site):
        pub.publish(OPEN, mode=pub.MODE_PUBLIC, portal=True)
        assert pub.portal_name() == OPEN
        assert pub.published_entry(OPEN)["portal"] is True

    def test_two_doors_are_refused_rather_than_resolved(self, site):
        """A coin flip the gate would have to make on every refused request, and
        the wrong side of it is a redirect loop for everyone signed out."""
        pub.publish(OPEN, mode=pub.MODE_PUBLIC, portal=True)
        with pytest.raises(ValueError, match=OPEN):
            pub.publish(PORTAL, mode=pub.MODE_PUBLIC, portal=True)

    def test_an_operator_variable_still_outranks_the_registry(self, site, monkeypatch):
        pub.publish(OPEN, mode=pub.MODE_PUBLIC, portal=True)
        monkeypatch.setenv("FRAGO_LOGIN_PORTAL", PORTAL)
        r = site.get(f"/app/{MINE}/", headers=HTML)
        assert r.headers["location"] == f"/app/{PORTAL}/?next={MINE}"

    def test_registering_nothing_keeps_the_historical_name(self, site):
        """Deployments that never registered a portal keep what they have."""
        assert security.login_portal() == PORTAL


class TestTheRedirectCannotLeaveThisSite:
    def test_the_destination_is_always_a_local_path(self, site):
        r = site.get(f"/app/{MINE}/", headers=HTML)
        target = r.headers["location"]
        assert target.startswith("/app/")
        assert "//" not in target and ":" not in target

    def test_a_public_page_is_served_rather_than_redirected(self, site):
        assert site.get(f"/app/{OPEN}/", headers=HTML).status_code == 200
