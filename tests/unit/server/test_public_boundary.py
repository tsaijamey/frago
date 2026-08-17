"""What an anonymous visitor can reach on a deployed frago, end to end.

`test_security.py` exercises the gate against a toy app; this one runs the real
`create_app()`, so every router, static mount and fallback the server actually
publishes is in scope. The list of cases comes from the boundary audit of
20260817 — each is a way the "only published pages are public" claim could turn
out to be false.

The app is built without entering the TestClient context manager on purpose:
that skips the lifespan, and with it the scheduler, the sync service and a
GitHub call that blocks for half an hour when rate-limited.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

PUBLISHED = "pubapp"
PRIVATE = "secretapp"

VISITOR = ("93.184.216.34", 41234)
OWNER = ("127.0.0.1", 41234)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two recipes: one published, one not, sharing a front end.

    Plus a data directory with a symlink pointing out of it, which is the
    escape a `.resolve()` that forgot about links would allow.
    """
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)
    monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    security.ensure_token()

    recipes = tmp_path / "recipes"
    for name, body in ((PUBLISHED, "<h1>public</h1>"), (PRIVATE, "<h1>internal</h1>")):
        assets = recipes / name / "assets"
        assets.mkdir(parents=True)
        (assets / "index.html").write_text(body, encoding="utf-8")
    (recipes / PRIVATE / "assets" / ".env").write_text(
        "API_KEY=sk-SECRET-FROM-BORROWED-ASSETS", encoding="utf-8"
    )

    shown = tmp_path / "shown"
    shown.mkdir()
    (shown / "rows.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    outside = tmp_path / "secretzone"
    outside.mkdir()
    (outside / "creds.txt").write_text("SECRET-OUTSIDE-DATADIR", encoding="utf-8")
    (shown / "link-out").symlink_to(outside)

    def make(name, ui_from=None):
        class _Meta:
            pass

        _Meta.ui_from = ui_from

        class _Recipe:
            pass

        _Recipe.base_dir = recipes / name
        _Recipe.script_path = recipes / name / "recipe.py"
        _Recipe.metadata = _Meta()
        return _Recipe()

    table = {PUBLISHED: make(PUBLISHED), PRIVATE: make(PRIVATE)}

    class _Registry:
        def find(self, name, source=None):
            if name not in table:
                raise RecipeNotFoundError(name, [])
            return table[name]

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    app_state.publish(
        PUBLISHED,
        {"dataDir": str(shown), "apiKey": "sk-PRIVATE-SLOT-SECRET", "public": {"title": "Q3"}},
    )
    app_state.publish(PUBLISHED, {"dataDir": str(outside)}, slot="private")
    pub.publish(PUBLISHED)

    return {"recipes": recipes, "table": table, "make": make, "outside": outside}


@pytest.fixture
def visitor(world):
    from frago.server.app import create_app

    return TestClient(create_app(), follow_redirects=False, client=VISITOR)


@pytest.fixture
def owner(world):
    from frago.server.app import create_app

    return TestClient(create_app(), follow_redirects=False, client=OWNER)


class TestPathNormalisation:
    """The gate matches `^/app/(name)(/…)?$`; everything hinges on the path it sees."""

    @pytest.mark.parametrize(
        "path",
        [
            "/app/pubapp/../../api/file?path=/etc/passwd",
            "/app/pubapp/..%2f..%2fapi/file",
            "/app/pubapp/%2e%2e/%2e%2e/api/file",
            "/app/pubapp/%252e%252e/api/file",
            "//app/pubapp/",
            "/APP/pubapp/",
            "/app//pubapp/",
            "/app/pubapp./",
            "/app/pubapp%20/",
            "/app/./pubapp/",
            "/./app/pubapp/",
        ],
    )
    def test_a_bent_path_never_reaches_the_private_side(self, visitor, path):
        response = visitor.get(path)
        assert response.status_code != 200 or "/app/" in str(response.url)
        assert "root:" not in response.text

    def test_the_api_stays_shut_however_it_is_spelled(self, visitor):
        for path in ("/api/file?path=/etc/passwd", "/API/file?path=/etc/passwd", "/api//file"):
            assert visitor.get(path).status_code in (401, 404)


class TestBorrowedFrontEnd:
    """`ui_from` lets one recipe serve another's assets. Publishing the borrower
    therefore publishes the lender's assets directory — which is the intent, but
    it must be the *stated* intent, because the lender was never published."""

    @pytest.fixture
    def borrowing(self, world, monkeypatch):
        table = world["table"]
        table[PUBLISHED] = world["make"](PUBLISHED, ui_from=PRIVATE)

        class _Registry:
            def find(self, name, source=None):
                if name not in table:
                    raise RecipeNotFoundError(name, [])
                return table[name]

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
        from frago.server.app import create_app

        return TestClient(create_app(), follow_redirects=False, client=VISITOR)

    def test_the_borrowed_page_is_served(self, borrowing):
        assert "internal" in borrowing.get(f"/app/{PUBLISHED}/").text

    def test_the_lenders_dotfiles_do_not_come_along(self, borrowing):
        """Borrowing a front end must not borrow the lender's .env with it.

        `frago recipe publish` also names the lender, so the exposure of its
        ordinary assets is at least stated up front.
        """
        response = borrowing.get(f"/app/{PUBLISHED}/.env")
        assert response.status_code == 401
        assert "sk-SECRET-FROM-BORROWED-ASSETS" not in response.text

    def test_the_lenders_own_address_stays_shut(self, borrowing):
        assert borrowing.get(f"/app/{PRIVATE}/").status_code == 401


class TestDataDirectoryEscape:
    def test_a_symlink_out_of_the_data_directory_is_refused(self, visitor):
        """The audit's fixture: a link inside dataDir pointing at a sibling."""
        response = visitor.get(f"/app/{PUBLISHED}/data/link-out/creds.txt")
        assert response.status_code in (403, 404)
        assert "SECRET-OUTSIDE-DATADIR" not in response.text

    @pytest.mark.parametrize(
        "path",
        ["../secretzone/creds.txt", "..%2fsecretzone%2fcreds.txt", "%2e%2e/secretzone/creds.txt"],
    )
    def test_climbing_out_with_dots_is_refused(self, visitor, path):
        response = visitor.get(f"/app/{PUBLISHED}/data/{path}")
        assert "SECRET-OUTSIDE-DATADIR" not in response.text

    def test_the_data_it_is_meant_to_serve_still_arrives(self, visitor):
        assert visitor.get(f"/app/{PUBLISHED}/data/rows.json").json() == [1, 2, 3]


class TestPrivateSlot:
    def test_an_unpublished_slot_is_unreachable(self, visitor):
        assert visitor.get(f"/app/{PUBLISHED}/config.json?key=private").status_code == 401
        assert visitor.get(f"/app/{PUBLISHED}/data/creds.txt?key=private").status_code == 401

    def test_the_published_slots_own_private_fields_do_not_leak(self, visitor):
        body = visitor.get(f"/app/{PUBLISHED}/config.json").text
        assert "sk-PRIVATE-SLOT-SECRET" not in body
        assert "dataDir" not in body


class TestOtherMounts:
    """Everything else the server publishes, seen from outside."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/docs",
            "/api/openapi.json",
            "/api/redoc",
            "/api/status",
            "/api/recipes",
            "/viewer/",
            "/browser/",
            "/assets/index.js",
            "/icons/icon.png",
            "/",
            "/workbench",
        ],
    )
    def test_nothing_outside_the_published_page_answers(self, visitor, path):
        assert visitor.get(path).status_code in (401, 404)

    def test_the_owner_still_gets_the_app(self, owner):
        assert owner.get("/api/status").status_code == 200


class TestRedirectAndMethods:
    def test_the_bare_name_redirect_stays_inside_the_public_zone(self, visitor):
        response = visitor.get(f"/app/{PUBLISHED}")
        assert response.status_code == 307
        assert response.headers["location"].startswith(f"/app/{PUBLISHED}/")

    def test_an_unpublished_recipe_gets_no_redirect_either(self, visitor):
        assert visitor.get(f"/app/{PRIVATE}").status_code == 401

    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
    def test_writing_methods_are_refused_on_a_published_page(self, visitor, method):
        assert visitor.request(method, f"/app/{PUBLISHED}/data/rows.json").status_code == 401

    def test_a_cors_preflight_does_not_open_the_api(self, visitor):
        response = visitor.request(
            "OPTIONS",
            "/api/file",
            headers={
                "Origin": "http://192.168.1.9:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 401


class TestUnpublishing:
    def test_taking_a_page_down_takes_effect_at_once(self, visitor):
        assert visitor.get(f"/app/{PUBLISHED}/").status_code == 200
        pub.unpublish(PUBLISHED)
        assert visitor.get(f"/app/{PUBLISHED}/").status_code == 401
        assert visitor.get(f"/app/{PUBLISHED}/data/rows.json").status_code == 401


class TestErrorShaping:
    """Client errors collapse to one shape for visitors; server errors do not.

    Hiding a 500 behind a 404 would cost the operator a real fault report and
    buy the visitor nothing — they already know the request failed.
    """

    def test_a_client_error_is_flattened(self, visitor):
        assert visitor.get(f"/app/{PUBLISHED}/data/nope.json").status_code == 404

    def test_a_server_error_is_not_disguised(self, visitor, monkeypatch):
        from fastapi import HTTPException

        def boom(*args, **kwargs):
            raise HTTPException(status_code=503, detail="upstream is down")

        monkeypatch.setattr("frago.server.routes.app_pages._slot_state", boom)
        assert visitor.get(f"/app/{PUBLISHED}/config.json").status_code == 503


PASSWORD = "correct-horse-battery"


@pytest.fixture
def accounts(world, tmp_path, monkeypatch):
    """Two people with live cookies, and a slot of data each.

    Both tables and the identity state root go to tmp_path. `FRAGO_USER_STATE_DIR`
    is set rather than the module constant patched, because two modules resolve
    that root — `app_state` writes it, `identity` reads it to tell an account
    that has data from one that never used the site — and a test that moved only
    one of them would be testing a layout that never exists in production.
    """
    monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "app-state-users"))
    for leak in ("FRAGO_USERS_FILE", "FRAGO_SESSIONS_DIR", "FRAGO_SIGNUP_GATE"):
        monkeypatch.delenv(leak, raising=False)
    ident.reset_rate_limits()

    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)
        mine = tmp_path / f"data-{who}"
        mine.mkdir()
        (mine / "rows.json").write_text(json.dumps([who]), encoding="utf-8")
        app_state.publish(
            PUBLISHED,
            {
                "dataDir": str(mine),
                "apiKey": f"sk-{who.upper()}-PRIVATE",
                "public": {"title": who},
            },
            slot=user.id,
            identity=True,
        )
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}

    yield people
    ident.reset_rate_limits()


def _signed_in(cookie: str) -> TestClient:
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


class TestIdentityIsTheSlot:
    """A page published `--require-identity`: same address, different data.

    The whole feature is one substitution — the slot a visitor reads is decided
    by who they signed in as — so these are the cases where it either happens or
    silently does not.
    """

    @pytest.fixture(autouse=True)
    def identity_mode(self, world):
        pub.publish(PUBLISHED, mode=pub.MODE_IDENTITY)

    def test_a_signed_in_visitor_reads_their_own_slot(self, accounts):
        client = _signed_in(accounts["zhang"]["cookie"])
        config = client.get(f"/app/{PUBLISHED}/config.json").json()
        assert config["slot"] == accounts["zhang"]["id"]
        assert config["title"] == "zhang"
        assert client.get(f"/app/{PUBLISHED}/data/rows.json").json() == ["zhang"]

    def test_the_other_person_reads_something_else_entirely(self, accounts):
        client = _signed_in(accounts["li"]["cookie"])
        config = client.get(f"/app/{PUBLISHED}/config.json").json()
        assert config["slot"] == accounts["li"]["id"]
        assert config["title"] == "li"
        assert client.get(f"/app/{PUBLISHED}/data/rows.json").json() == ["li"]

    def test_neither_can_ask_for_the_others_slot(self, accounts):
        """`?key=` is the owner's control. A visitor naming a slot is refused
        outright rather than quietly served their own — the refusal is what says
        the request was wrong, and silence here is how the previous critical bug
        stayed invisible."""
        client = _signed_in(accounts["li"]["cookie"])
        other = accounts["zhang"]["id"]
        assert client.get(f"/app/{PUBLISHED}/config.json?key={other}").status_code == 401
        assert client.get(f"/app/{PUBLISHED}/data/rows.json?key={other}").status_code == 401

    def test_an_anonymous_visitor_is_refused(self, accounts, visitor):
        """The one reason this mode exists. If the gate judged it by "is it
        published" alone, every one of these would be a 200 before the identity
        check ever ran."""
        for path in ("/", "config.json", "data/rows.json", "index.html"):
            assert visitor.get(f"/app/{PUBLISHED}/{path}").status_code == 401

    def test_the_identity_config_is_filtered_as_hard_as_the_public_one(self, accounts):
        """The regression nail for the "is it the owner" question.

        Asking "is it anonymous" instead puts a signed-in visitor in the else
        branch, where the unfiltered slot lives: this server's absolute paths,
        and whatever the recipe parked next to them.
        """
        body = _signed_in(accounts["zhang"]["cookie"]).get(f"/app/{PUBLISHED}/config.json")
        assert "dataDir" not in body.text
        assert "sk-ZHANG-PRIVATE" not in body.text
        assert body.json()["apiBase"] is None
        assert body.json()["readOnly"] is True

    def test_a_person_who_never_used_the_page_gets_an_empty_one(self, accounts, tmp_path):
        """No slot file yet is a blank page, not a 500."""
        newcomer = ident.create_user("wang@example.com", PASSWORD)
        client = _signed_in(ident.create_session(newcomer.id))
        config = client.get(f"/app/{PUBLISHED}/config.json")
        assert config.status_code == 200
        assert config.json()["slot"] == newcomer.id
        assert client.get(f"/app/{PUBLISHED}/data/rows.json").status_code == 404

    def test_a_recipe_slot_of_the_same_name_is_not_theirs_to_read(self, accounts):
        """The two roots are separate directories, not separate names in one.

        A recipe may write any slot name at any moment without asking the
        server, so a name-based rule could never hold. Here the recipe writes a
        slot named exactly like an account id; the account must still read its
        own file under `app-state-users/`.
        """
        uid = accounts["zhang"]["id"]
        app_state.publish(PUBLISHED, {"public": {"title": "recipe-owned"}}, slot=uid)
        config = _signed_in(accounts["zhang"]["cookie"]).get(f"/app/{PUBLISHED}/config.json")
        assert config.json()["title"] == "zhang"

    @pytest.mark.parametrize(
        "path", ["/api/file?path=/etc/passwd", "/api/status", "/api/recipes", "/workbench"]
    )
    def test_signing_in_does_not_make_a_visitor_a_weakened_owner(self, accounts, path):
        assert _signed_in(accounts["zhang"]["cookie"]).get(path).status_code in (401, 404)


class TestPublishedMode:
    """How the `mode` field is read, including when it cannot be."""

    def test_an_entry_from_before_this_field_existed_stays_public(self, world, visitor):
        pub.published_path().write_text(
            json.dumps({PUBLISHED: {"slot": "default", "since": "2026-01-01T00:00:00"}}),
            encoding="utf-8",
        )
        pub._cache = None
        assert visitor.get(f"/app/{PUBLISHED}/config.json").status_code == 200

    @pytest.mark.parametrize("mode", ["pubic", "PUBLIC", "", None, 1, ["public"]])
    def test_a_mode_nobody_recognises_refuses_the_anonymous_visitor(self, world, visitor, mode):
        """Fail closed. A switch that falls back to the permissive answer when it
        cannot parse its own input is the shape of the previous audit's D-F1."""
        pub.published_path().write_text(
            json.dumps({PUBLISHED: {"slot": "default", "mode": mode, "since": "x"}}),
            encoding="utf-8",
        )
        pub._cache = None
        assert pub.published_slot(PUBLISHED) is None
        assert visitor.get(f"/app/{PUBLISHED}/config.json").status_code == 401

    def test_an_unreadable_mode_still_leaves_the_page_addressable(self, world, accounts):
        """Refusing anonymous readers is not the same as unpublishing: the entry
        still exists, so someone signed in reaches it."""
        pub.published_path().write_text(
            json.dumps({PUBLISHED: {"slot": "default", "mode": "pubic", "since": "x"}}),
            encoding="utf-8",
        )
        pub._cache = None
        client = _signed_in(accounts["zhang"]["cookie"])
        assert client.get(f"/app/{PUBLISHED}/config.json").status_code == 200

    def test_publishing_refuses_a_mode_it_would_have_to_guess_at(self, world):
        with pytest.raises(ValueError):
            pub.publish(PUBLISHED, mode="sort-of-public")

    def test_a_public_page_stays_the_same_page_for_everyone(self, world, accounts, visitor):
        """Signing in must not change what a *public* dashboard shows. The gate
        settles the public zone first, so the published slot is served to
        everybody — which is what "published for anyone to read" means."""
        anonymous = visitor.get(f"/app/{PUBLISHED}/config.json").json()
        signed_in = _signed_in(accounts["zhang"]["cookie"]).get(
            f"/app/{PUBLISHED}/config.json"
        ).json()
        assert signed_in == anonymous
        assert signed_in["slot"] == "default"


class TestTheRouteAsksTheRightQuestion:
    """Read off the source, because the failure this guards is a *shape*.

    `is_public_request` cannot tell a signed-in visitor from the owner, so every
    decision made with it hands one of them the other's answer. The route may
    not ask it, and may not re-derive a visitor's slot from the URL either.
    """

    def test_the_page_route_no_longer_asks_whether_a_request_is_public(self):
        from frago.server.routes import app_pages

        source = Path(app_pages.__file__).read_text(encoding="utf-8")
        assert "is_public_request" not in source
        assert "public_slot" not in source

    def test_the_url_is_read_for_a_slot_in_exactly_one_place(self):
        """The owner's `?key=` branch, and nowhere else."""
        from frago.server.routes import app_pages

        source = Path(app_pages.__file__).read_text(encoding="utf-8")
        assert source.count('query_params.get("key")') == 1


class TestDotPaths:
    """Found by audit 20260817.

    Two things the gate used to wave through and leave entirely to the route:
    dot segments (one lock doing the work of two) and dotfiles (`.env` in a
    recipe's assets, read straight off a published page).
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/app/pubapp/.env",
            "/app/pubapp/.git/config",
            "/app/pubapp/data/.secrets",
        ],
    )
    def test_dotfiles_are_refused_at_the_gate(self, visitor, path):
        assert visitor.get(path).status_code == 401

    @pytest.mark.parametrize(
        "path",
        [
            "/app/pubapp/./index.html",
            "/app/pubapp/../pubapp/index.html",
            "/app/pubapp/../../api/file",
        ],
    )
    def test_dot_segments_are_refused_at_the_gate(self, world, path):
        """Checked against the gate directly: an HTTP client collapses these
        before they are sent, so only a raw socket — or this — reaches the code
        that has to cope with them. uvicorn does not collapse them.
        """
        from frago.server.security import classify_public

        scope = {"type": "http", "method": "GET", "path": path, "query_string": b""}
        assert classify_public(scope) is None

    def test_the_owner_can_still_reach_them(self, owner, world):
        (world["recipes"] / PUBLISHED / "assets" / ".env").write_text("x", encoding="utf-8")
        assert owner.get(f"/app/{PUBLISHED}/.env").status_code == 200

    def test_ordinary_files_are_unaffected(self, visitor):
        assert visitor.get(f"/app/{PUBLISHED}/index.html").status_code == 200
        assert visitor.get(f"/app/{PUBLISHED}/data/rows.json").status_code == 200
