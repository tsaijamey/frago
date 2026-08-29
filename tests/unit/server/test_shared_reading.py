"""A few named people, one body of the owner's data, no run permission at all.

This is the rung of visibility that did not exist. `identity` meant two things
at once — sign in first, and read a slot named after yourself — so the most
ordinary request in the system had no spelling: *these four people should see
the numbers I computed*. What people did instead was reach for machine-level
shared data, which is a data-layer mechanism for a different problem, or give up
and make the page public.

The tests here are the whole of what that rung has to be true for:

* the page is served, and out of the **owner's** slot rather than the reader's
  own empty one — including its files and its exported modes;
* it is still not another **account's** anything;
* and it opens nothing else. A shared reading has no directory of this person's,
  so it accepts no runs however the recipe declared itself.
"""

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

PAGE = "dma_plan"
PASSWORD = "correct-horse-battery-staple"
VISITOR = ("93.184.216.34", 41234)


@pytest.fixture
def site(tmp_path, monkeypatch):
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

    base = tmp_path / "recipes" / PAGE
    (base / "assets").mkdir(parents=True)
    (base / "assets" / "index.html").write_text("<h1>plan</h1>", encoding="utf-8")

    class _Meta:
        name = PAGE
        ui_from = None
        description = "The plan"
        inputs: dict = {}
        # Declared, so that "a shared page has no buttons" is tested against a
        # recipe that would otherwise have some.
        page_actions = ["refresh"]

    class _Recipe:
        base_dir = base
        script_path = base / "recipe.py"
        metadata = _Meta()

    class _Registry:
        def find(self, name, source=None):
            if name != PAGE:
                raise RecipeNotFoundError(name, [])
            return _Recipe()

        def needs_rescan(self):
            return False

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
    monkeypatch.setattr("frago.recipes.registry.invalidate_registry", lambda: None)

    # What the owner computed, published to their own slot in the ordinary way.
    owner_data = tmp_path / "owner-data"
    owner_data.mkdir()
    (owner_data / "plan.json").write_text('{"picks": 7245}', encoding="utf-8")
    app_state.publish(PAGE, {
        "dataDir": str(owner_data),
        "secretKey": "never-leaves-the-machine",
        "public": {"asOf": "2026-08-29", "picks": 7245},
    })

    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}

    yield {"people": people, "root": tmp_path, "owner_data": owner_data}
    ident.reset_rate_limits()


def _client(cookie=None):
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    if cookie:
        client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


def _share_with(site, *who):
    pub.publish(PAGE, mode=pub.MODE_IDENTITY, reads=pub.READS_OWNER,
                allow=[site["people"][one]["id"] for one in who])


class TestTheyReadTheOwnersCopy:
    def test_the_page_config_comes_from_the_owners_slot(self, site):
        _share_with(site, "zhang")
        body = _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json").json()
        assert body["asOf"] == "2026-08-29"
        assert body["picks"] == 7245

    def test_it_is_still_only_the_public_block(self, site):
        """Sharing changes whose data is served, never how much of it. The rest
        of a slot is where a recipe parks absolute paths and the odd key."""
        _share_with(site, "zhang")
        body = _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json").json()
        assert "secretKey" not in body
        assert "dataDir" not in body
        assert body["apiBase"] is None
        assert body["readOnly"] is True

    def test_the_owners_files_are_served_through_the_pages_own_door(self, site):
        _share_with(site, "zhang")
        r = _client(site["people"]["zhang"]["cookie"]).get(f"/app/{PAGE}/data/plan.json")
        assert r.status_code == 200
        assert r.json() == {"picks": 7245}

    def test_two_readers_see_the_same_thing(self, site):
        """The point of the rung. Per-person reading would give both of them an
        empty page, with nothing anywhere reporting a fault."""
        _share_with(site, "zhang", "li")
        seen = [
            _client(site["people"][who]["cookie"]).get(f"/app/{PAGE}/data/plan.json").json()
            for who in ("zhang", "li")
        ]
        assert seen[0] == seen[1] == {"picks": 7245}


class TestItOpensNothingElse:
    def test_someone_off_the_list_is_refused_as_if_it_did_not_exist(self, site):
        _share_with(site, "zhang")
        assert _client(site["people"]["li"]["cookie"]).get(
            f"/app/{PAGE}/config.json").status_code == 401

    def test_anonymous_is_refused(self, site):
        _share_with(site, "zhang")
        assert _client().get(f"/app/{PAGE}/config.json").status_code == 401

    def test_it_accepts_no_runs_even_though_the_recipe_declared_one(self, site):
        _share_with(site, "zhang")
        r = _client(site["people"]["zhang"]["cookie"]).post(
            f"/app/{PAGE}/run", json={"params": {"mode": "refresh"}})
        assert r.status_code == 404

    def test_the_page_is_told_it_has_no_buttons(self, site):
        _share_with(site, "zhang")
        body = _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json").json()
        assert body["actions"] == []
        assert body["runnable"] is False

    def test_a_reader_still_cannot_name_a_slot(self, site):
        """`?key=` is the owner's control. Honouring it here would hand the
        decision back to the reader, which is the shape the gate exists to stop."""
        _share_with(site, "zhang")
        assert _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json?key=other").status_code == 401


class TestPerPersonPagesAreUnchanged:
    def test_they_still_read_their_own_empty_slot(self, site):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY,
                    allow=[site["people"]["zhang"]["id"]])
        body = _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json").json()
        assert "picks" not in body, "the owner's numbers must not leak into a per-person page"

    def test_and_their_slot_is_their_account_id(self, site):
        pub.publish(PAGE, mode=pub.MODE_IDENTITY,
                    allow=[site["people"]["zhang"]["id"]])
        body = _client(site["people"]["zhang"]["cookie"]).get(
            f"/app/{PAGE}/config.json").json()
        assert body["slot"] == site["people"]["zhang"]["id"]
