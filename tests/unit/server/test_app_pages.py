"""Recipe pages served at /app/<recipe-name>.

What these tests pin down is the promise the address makes: the same recipe
always lives at the same readable URL, the page's own relative paths keep
working there, and nothing outside the recipe's assets or declared data
directory can be reached through it.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server.routes import app_pages

RECIPE = "demo_board"


@pytest.fixture
def recipe_dir(tmp_path, monkeypatch):
    """A recipe on disk with a small front end, wired into the registry."""
    base = tmp_path / "recipes" / RECIPE
    assets = base / "assets"
    (assets / "layouts").mkdir(parents=True)
    (assets / "index.html").write_text("<h1>demo board</h1>", encoding="utf-8")
    (assets / "app.js").write_text("fetch('config.json')", encoding="utf-8")
    (assets / "layouts" / "grid.css").write_text(".grid{}", encoding="utf-8")

    class _Meta:
        ui_from = None
        # What this recipe opened to its own page. Tests that care set it; the
        # default is the honest one — almost no recipe declares any.
        page_actions: list[str] = []

    class _Recipe:
        base_dir = base
        script_path = base / "recipe.py"
        metadata = _Meta()

    class _Registry:
        def find(self, name, source=None):
            if name != RECIPE:
                raise RecipeNotFoundError(name, [])
            return _Recipe()

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
    return base


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    directory = tmp_path / "app-state"
    monkeypatch.setattr(app_state, "APP_STATE_DIR", directory)
    return directory


@pytest.fixture
def landing(tmp_path, monkeypatch):
    """The directory the platform gives this recipe on this machine.

    Both halves of that answer move together: the account tree the layout hangs
    off, and this machine's record of whose runs these are. A fixture that moved
    only one would be describing a machine that cannot exist — and the point of
    these tests is that nobody *tells* the server this directory, so a test that
    could not compute the same one would be testing nothing.
    """
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("FRAGO_IDENTITY_FILE", str(tmp_path / "identity.json"))
    monkeypatch.setenv("FRAGO_MIGRATION_MANIFEST", str(tmp_path / "manifest.jsonl"))

    from frago.recipes.app_state import recipe_data_dir
    from frago.recipes.context import default_identity

    spot = recipe_data_dir(default_identity(), RECIPE)
    spot.mkdir(parents=True)
    return spot


@pytest.fixture
def client(recipe_dir, state_dir):
    from frago.server.app import create_app

    # Pose as a process on this machine. The access-zone middleware trusts
    # loopback and challenges everything else; these tests are about the owner
    # reading their own page, so they take the local seat. The anonymous-visitor
    # side is covered in test_security.py.
    return TestClient(create_app(), follow_redirects=False, client=("127.0.0.1", 50000))


class TestAddress:
    def test_bare_name_redirects_to_directory_form(self, client):
        """Without the trailing slash the page's relative fetches resolve one level too high."""
        response = client.get(f"/app/{RECIPE}")
        assert response.status_code == 307
        assert response.headers["location"] == f"/app/{RECIPE}/"

    def test_redirect_carries_the_slot_along(self, client):
        response = client.get(f"/app/{RECIPE}?key=second")
        assert response.headers["location"] == f"/app/{RECIPE}/?key=second"

    def test_directory_form_serves_the_index(self, client):
        response = client.get(f"/app/{RECIPE}/")
        assert response.status_code == 200
        assert "demo board" in response.text

    def test_assets_come_from_the_recipe_itself(self, client):
        assert client.get(f"/app/{RECIPE}/app.js").status_code == 200
        assert client.get(f"/app/{RECIPE}/layouts/grid.css").status_code == 200

    def test_unknown_recipe_is_not_found(self, client):
        assert client.get("/app/no_such_recipe/").status_code == 404

    def test_recipe_without_a_front_end_says_so(self, client, tmp_path, monkeypatch):
        headless = tmp_path / "recipes" / "headless"
        headless.mkdir(parents=True)

        class _Meta:
            ui_from = None

        class _Recipe:
            base_dir = headless
            script_path = headless / "recipe.py"
            metadata = _Meta()

        class _Registry:
            def find(self, name, source=None):
                return _Recipe()

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
        response = client.get("/app/headless/")
        assert response.status_code == 404
        assert "no assets" in response.json()["detail"]


class TestBuiltInPages:
    """A page whose front end ships inside frago, at the same kind of address.

    The virtual desktop's page is the one that exists today. Two things must hold
    for it, and neither is about the files themselves: the address stays exactly
    what the stage's ledger and the open browser tab already say it is, and a
    leftover recipe of the same name on disk can never take that address back.
    """

    def test_desktop_page_is_served_without_any_recipe_installed(self, client):
        """The registry in this fixture knows only `demo_board`; the page loads anyway."""
        response = client.get("/app/agent_os/")
        assert response.status_code == 200
        assert "<html" in response.text.lower()

    def test_bytes_come_from_the_package(self, client):
        from importlib.resources import files

        packaged = files("frago.desktop").joinpath("assets", "index.html").read_bytes()
        assert client.get("/app/agent_os/").content == packaged
        assert client.get("/app/agent_os/app.js").status_code == 200

    def test_a_recipe_of_the_same_name_cannot_take_the_address(
        self, client, tmp_path, monkeypatch
    ):
        """The retired recipe stays on disk as the rollback copy until Phase 5.

        If it could still answer here, the page would quietly go on being served
        from a directory nobody edits any more — and nothing would report it.
        """
        impostor = tmp_path / "recipes" / "agent_os"
        (impostor / "assets").mkdir(parents=True)
        (impostor / "assets" / "index.html").write_text("<h1>stale</h1>", encoding="utf-8")

        class _Meta:
            ui_from = None

        class _Recipe:
            base_dir = impostor
            script_path = impostor / "recipe.py"
            metadata = _Meta()

        class _Registry:
            def find(self, name, source=None):
                return _Recipe()

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())
        assert "stale" not in client.get("/app/agent_os/").text

    def test_the_address_is_the_one_written_into_the_ledger(self):
        """`http://127.0.0.1:8093/app/agent_os` is recorded per instance and never
        recomputed, so the route it points at is not free to move."""
        from frago.desktop import health

        assert health.expected_desktop_url("bc98c2f8114b") == (
            "http://127.0.0.1:8093/app/agent_os"
        )


class TestSharedFrontEnd:
    """One front end serving several recipes, declared with `ui_from`.

    This exists because two recipes really do share a UI in this install. It is
    the exception: a recipe's page normally lives in its own assets/ so the two
    halves ship and version together.
    """

    @pytest.fixture
    def borrower(self, tmp_path, monkeypatch, recipe_dir):
        lender = tmp_path / "recipes" / "shared_ui"
        (lender / "assets").mkdir(parents=True)
        (lender / "assets" / "index.html").write_text("<h1>shared</h1>", encoding="utf-8")

        def _make(base, ui_from):
            class _Meta:
                pass

            _Meta.ui_from = ui_from

            class _Recipe:
                pass

            _Recipe.base_dir = base
            _Recipe.script_path = base / "recipe.py"
            _Recipe.metadata = _Meta()
            return _Recipe()

        table = {
            "borrower": _make(tmp_path / "recipes" / "borrower", "shared_ui"),
            "shared_ui": _make(lender, None),
            "orphan": _make(tmp_path / "recipes" / "orphan", "not_installed"),
            RECIPE: _make(recipe_dir, None),
        }

        class _Registry:
            def find(self, name, source=None):
                if name not in table:
                    raise RecipeNotFoundError(name, [])
                return table[name]

        monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    def test_borrowed_page_is_served(self, client, borrower):
        response = client.get("/app/borrower/")
        assert response.status_code == 200
        assert "shared" in response.text

    def test_borrowed_page_keeps_its_own_config(self, client, borrower):
        """Two recipes sharing a front end must not share each other's state."""
        app_state.publish("borrower", {"title": "mine"})
        body = client.get("/app/borrower/config.json").json()
        assert body["recipeName"] == "borrower"
        assert body["title"] == "mine"

    def test_missing_lender_is_named_in_the_error(self, client, borrower):
        response = client.get("/app/orphan/")
        assert response.status_code == 404
        assert "not_installed" in response.json()["detail"]


class TestFreshness:
    """Editing a recipe's front end must show up on the next reload.

    Serving a stale copy is the worst kind of wrong here: it looks exactly like
    the edit did nothing, and sends people hunting through their own code.
    """

    @pytest.mark.parametrize("path", ["", "app.js", "config.json"])
    def test_browser_is_told_to_revalidate(self, client, path):
        response = client.get(f"/app/{RECIPE}/{path}")
        assert response.headers["cache-control"] == "no-cache"

    def test_edited_asset_is_served_immediately(self, client, recipe_dir):
        first = client.get(f"/app/{RECIPE}/app.js").text
        (recipe_dir / "assets" / "app.js").write_text("// edited", encoding="utf-8")
        assert client.get(f"/app/{RECIPE}/app.js").text != first


class TestConfig:
    def test_config_is_synthesized_not_a_file(self, client, recipe_dir):
        """No config.json exists in assets/; the server makes one per request."""
        assert not (recipe_dir / "assets" / "config.json").exists()
        body = client.get(f"/app/{RECIPE}/config.json").json()
        assert body["recipeName"] == RECIPE
        assert body["slot"] == "default"

    def test_api_base_is_relative_so_other_devices_can_open_the_page(self, client):
        body = client.get(f"/app/{RECIPE}/config.json").json()
        assert body["apiBase"] == "/api"

    def test_published_state_reaches_the_page(self, client):
        app_state.publish(RECIPE, {"dataDir": "/tmp", "title": "Q3"})
        body = client.get(f"/app/{RECIPE}/config.json").json()
        assert body["title"] == "Q3"

    def test_rerunning_replaces_what_the_page_shows(self, client):
        app_state.publish(RECIPE, {"title": "first"})
        app_state.publish(RECIPE, {"title": "second"})
        assert client.get(f"/app/{RECIPE}/config.json").json()["title"] == "second"

    def test_slots_hold_several_things_open_at_once(self, client):
        app_state.publish(RECIPE, {"title": "project A"})
        app_state.publish(RECIPE, {"title": "project B"}, slot="b")
        assert client.get(f"/app/{RECIPE}/config.json").json()["title"] == "project A"
        assert client.get(f"/app/{RECIPE}/config.json?key=b").json()["title"] == "project B"

    def test_never_published_slot_still_renders(self, client):
        """A page opened before its recipe ever ran gets config, just an empty one."""
        body = client.get(f"/app/{RECIPE}/config.json?key=fresh").json()
        assert body["slot"] == "fresh"
        assert body["apiBase"] == "/api"


class TestDataProxy:
    """The owner reading their own recipe's output through their own page.

    Nothing here publishes a directory, because a module built on the base class
    cannot: it may not put a path in what it hands its page. The route works out
    where to read from who is asking, which is the same answer a run gets when it
    is told where to write — and until it did, this whole class of page was
    broken for the one person actually using the tool. Its files were sitting on
    disk and every request for one came back 404.
    """

    def test_serves_from_the_landing_spot_without_being_told_where_it_is(
            self, client, landing):
        (landing / "records.json").write_text('{"rows": 3}', encoding="utf-8")
        app_state.publish(RECIPE, {"title": "no path in here"})

        response = client.get(f"/app/{RECIPE}/data/records.json")
        assert response.status_code == 200
        assert response.json() == {"rows": 3}

    def test_a_recipe_that_holds_several_projects_addresses_one_by_name(
            self, client, landing):
        """A page that keeps several bodies of work names the project the way the
        layout spells it — `projects/<name>/…` — which is the recipe's own naming
        and not a location. There is no second addressing scheme for this, and
        no query parameter: the project is part of *which file*, and it goes
        through the same containment test as every other file address.
        """
        for project, rows in (("alpha", 1), ("beta", 2)):
            where = landing / "projects" / project
            where.mkdir(parents=True)
            (where / "n.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")

        assert client.get(
            f"/app/{RECIPE}/data/projects/alpha/n.json").json()["rows"] == 1
        assert client.get(
            f"/app/{RECIPE}/data/projects/beta/n.json").json()["rows"] == 2

    def test_the_page_state_slot_no_longer_chooses_a_directory(self, client, landing):
        """`?key=` picks which state a page renders. It used to pick a data
        directory too, because each slot published one — two things behind one
        name. The recipe's data has one landing spot per person; a body of work
        inside it is addressed as a project, above."""
        (landing / "n.json").write_text(json.dumps({"rows": 1}), encoding="utf-8")
        app_state.publish(RECIPE, {"title": "A"})
        app_state.publish(RECIPE, {"title": "B"}, slot="b")

        assert client.get(f"/app/{RECIPE}/data/n.json").json()["rows"] == 1
        assert client.get(f"/app/{RECIPE}/data/n.json?key=b").json()["rows"] == 1

    def test_a_recipe_that_has_never_written_anything_says_so(self, client, landing):
        landing.rmdir()
        response = client.get(f"/app/{RECIPE}/data/anything.json")
        assert response.status_code == 404
        assert str(landing) in response.json()["detail"]

    def test_a_missing_file_in_a_real_directory_is_just_missing(self, client, landing):
        assert client.get(f"/app/{RECIPE}/data/x.json").status_code == 404

    def test_records_still_under_an_old_path_are_refused_rather_than_shown_empty(
            self, client, landing, tmp_path):
        """The platform withholds a recipe's directory while its records sit
        somewhere else, so a run cannot start fresh without saying so. The read
        door has to answer the same way: serving the new, empty directory would
        render a page of nothing while everything the recipe wrote is elsewhere,
        which is the exact silence this layout exists to remove."""
        old = tmp_path / "old-home"
        old.mkdir()
        app_state.publish(RECIPE, {"dataDir": str(old)})

        response = client.get(f"/app/{RECIPE}/data/anything.json")
        assert response.status_code == 404
        assert "data-migrate" in response.json()["detail"]


class TestBoundaries:
    """The file address is the only thing the page controls, so it is the gate.

    Whatever a page asks for is resolved under the landing spot and refused if it
    comes out anywhere else. These are the four spellings of "anywhere else", and
    each is a separate mechanism rather than four ways of writing one: dot
    segments are text, an absolute path changes how the join works, a symlink is
    resolved by the kernel, and percent-encoding is undone before the route ever
    sees the path.
    """

    @pytest.fixture
    def secret(self, tmp_path):
        outside = tmp_path / "secret.txt"
        outside.write_text("private", encoding="utf-8")
        return outside

    def test_climbing_out_with_dots_is_refused(self, client, landing, secret):
        response = client.get(
            f"/app/{RECIPE}/data/{Path('..') / 'secret.txt'}", follow_redirects=False
        )
        assert response.status_code in (307, 403, 404)
        assert "private" not in response.text

    def test_a_percent_encoded_climb_is_refused(self, client, landing, secret):
        for spelling in ("..%2Fsecret.txt", "%2e%2e/secret.txt", "%2e%2e%2fsecret.txt"):
            response = client.get(f"/app/{RECIPE}/data/{spelling}", follow_redirects=False)
            assert "private" not in response.text, spelling

    def test_an_absolute_path_is_refused(self, client, landing, secret):
        response = client.get(f"/app/{RECIPE}/data/{secret}", follow_redirects=False)
        assert "private" not in response.text

    def test_a_symlink_pointing_out_is_refused(self, client, landing, tmp_path):
        """Resolved after the kernel has followed the link, because a rule about
        a link is a rule about nothing — the link is not what gets opened."""
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "creds.txt").write_text("SECRET-OUTSIDE", encoding="utf-8")
        (landing / "way-out").symlink_to(outside)

        response = client.get(f"/app/{RECIPE}/data/way-out/creds.txt")
        assert response.status_code in (403, 404)
        assert "SECRET-OUTSIDE" not in response.text

    def test_a_project_name_cannot_be_bent_into_a_climb(self, client, landing, secret):
        """The project is part of the file address, so it goes through the same
        test as the rest of it rather than being trusted for being a name."""
        response = client.get(
            f"/app/{RECIPE}/data/projects/../../secret.txt", follow_redirects=False
        )
        assert "private" not in response.text

    def test_resolver_blocks_escapes_directly(self, tmp_path):
        from fastapi import HTTPException

        base = tmp_path / "inside"
        base.mkdir()
        for escape in ("../outside.txt", "/etc/passwd", "a/../../outside.txt"):
            with pytest.raises(HTTPException) as caught:
                app_pages._resolve_within(base, escape)
            assert caught.value.status_code == 403

    def test_resolver_allows_paths_that_stay_inside(self, tmp_path):
        base = tmp_path / "inside"
        (base / "sub").mkdir(parents=True)
        assert app_pages._resolve_within(base, "sub/../ok.json") == base / "ok.json"

    def test_slot_name_cannot_escape_the_state_directory(self, client):
        assert client.get(f"/app/{RECIPE}/config.json?key=../evil").status_code == 400

    def test_recipe_name_with_a_slash_is_rejected(self, client):
        from fastapi import HTTPException

        response = client.get(f"/app/{RECIPE}/config.json")
        assert response.status_code == 200  # sanity: the good name still works
        with pytest.raises(HTTPException) as caught:
            app_pages._assets_dir("../etc")
        assert caught.value.status_code == 400


class TestPublishing:
    def test_page_url_is_readable_and_typeable(self, state_dir):
        assert app_state.page_url(RECIPE) == f"http://localhost:8093/app/{RECIPE}"

    def test_non_default_slot_shows_in_the_address(self, state_dir):
        assert app_state.page_url(RECIPE, "b") == f"http://localhost:8093/app/{RECIPE}?key=b"

    def test_slots_are_listed_newest_first(self, state_dir):
        app_state.publish(RECIPE, {}, slot="older")
        app_state.publish(RECIPE, {}, slot="newer")
        assert app_state.list_slots(RECIPE)[0] == "newer"

    def test_unpublished_recipe_lists_nothing(self, state_dir):
        assert app_state.list_slots(RECIPE) == []

    def test_unreadable_state_reads_as_empty_rather_than_crashing(self, state_dir):
        path = app_state.slot_path(RECIPE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ this is not json", encoding="utf-8")
        assert app_state.read(RECIPE) == {}

    @pytest.mark.parametrize("bad", ["..", ".", "a/b", "", "x/../y"])
    def test_bad_slot_names_are_refused(self, state_dir, bad):
        with pytest.raises(app_state.InvalidSlotName):
            app_state.publish(RECIPE, {}, slot=bad)


class TestAnonymousVisitor:
    """The same page, seen by someone who is not the owner.

    A recipe's slot state is written for a page running on the owner's machine:
    it routinely carries absolute paths, and nothing stops a recipe from parking
    a credential in it. When the page is published, that document must not be
    the one a visitor receives.
    """

    @pytest.fixture
    def visitor(self, recipe_dir, state_dir, tmp_path, monkeypatch):
        from frago.recipes import publish as pub
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
        monkeypatch.setattr(pub, "_cache", None, raising=False)
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        security.ensure_token()
        pub.publish(RECIPE)
        return TestClient(create_app(), follow_redirects=False, client=("93.184.216.34", 41234))

    def _publish_state(self, data_dir):
        app_state.publish(
            RECIPE,
            {
                "dataDir": str(data_dir),
                "apiKey": "sk-live-do-not-leak",
                "public": {"title": "Q3 numbers"},
            },
        )

    def test_visitor_gets_only_the_declared_public_keys(self, visitor, tmp_path):
        self._publish_state(tmp_path / "data")
        config = visitor.get(f"/app/{RECIPE}/config.json").json()
        assert config["title"] == "Q3 numbers"
        assert "dataDir" not in config
        assert "apiKey" not in config

    def test_visitor_is_told_the_page_is_read_only(self, visitor, tmp_path):
        """`apiBase: null` is the signal a front end checks before offering
        anything that would have POSTed to /api/recipes/<name>/run."""
        self._publish_state(tmp_path / "data")
        config = visitor.get(f"/app/{RECIPE}/config.json").json()
        assert config["apiBase"] is None
        assert config["readOnly"] is True

    def test_owner_still_gets_the_whole_config(self, client, tmp_path, visitor):
        self._publish_state(tmp_path / "data")
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["dataDir"] == str(tmp_path / "data")
        assert config["apiBase"] == "/api"
        assert config["readOnly"] is False

    def test_visitor_can_read_the_data_the_page_exists_to_show(
            self, visitor, landing, tmp_path):
        (landing / "rows.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        self._publish_state(tmp_path / "data")
        response = visitor.get(f"/app/{RECIPE}/data/rows.json")
        assert response.status_code == 200
        assert response.json() == [1, 2, 3]

    def test_visitor_cannot_climb_out_of_the_data_directory(
            self, visitor, landing, tmp_path):
        (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
        self._publish_state(tmp_path / "data")
        assert visitor.get(f"/app/{RECIPE}/data/../secret.txt").status_code in (403, 404)

    def test_visitor_cannot_reach_the_api_through_the_published_recipe(self, visitor):
        """Publishing a page must not publish the machine it runs on."""
        assert visitor.get("/api/file?path=/etc/passwd").status_code == 401
        assert visitor.post(f"/api/recipes/{RECIPE}/run").status_code == 401
        assert visitor.get("/api/status").status_code == 401


class TestSlotSmuggling:
    """Two parsers must not disagree about which slot a URL names.

    Found by audit 20260817: the gate read the *first* `key` parameter
    (`urllib.parse.parse_qs`) while the route read the *last* (Starlette's
    `QueryParams`), so `?key=<published>&key=<private>` was authorised against
    one slot and served from another — every slot of a published recipe,
    anonymous, one GET.
    """

    @pytest.fixture
    def two_slots(self, recipe_dir, state_dir, tmp_path, monkeypatch):
        from frago.recipes import publish as pub
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
        monkeypatch.setattr(pub, "_cache", None, raising=False)
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        security.ensure_token()

        shown = tmp_path / "shown"
        shown.mkdir()
        (shown / "rows.json").write_text(json.dumps({"public": True}), encoding="utf-8")

        hidden = tmp_path / "hidden"
        hidden.mkdir()
        (hidden / "rows.json").write_text(json.dumps({"fee": 999999}), encoding="utf-8")

        app_state.publish(RECIPE, {"dataDir": str(shown), "public": {"title": "Q3"}})
        app_state.publish(
            RECIPE,
            {"dataDir": str(hidden), "apiKey": "sk-live-do-not-leak", "public": {"client": "ACME"}},
            slot="acme",
        )
        pub.publish(RECIPE)  # only the default slot is public

        return TestClient(create_app(), follow_redirects=False, client=("93.184.216.34", 41234))

    def test_the_honest_request_for_a_private_slot_is_refused(self, two_slots):
        assert two_slots.get(f"/app/{RECIPE}/config.json?key=acme").status_code == 401

    def test_duplicate_key_cannot_smuggle_a_private_slot_into_config(self, two_slots):
        response = two_slots.get(f"/app/{RECIPE}/config.json?key=default&key=acme")
        assert response.status_code == 401 or response.json().get("client") != "ACME"

    def test_duplicate_key_cannot_smuggle_a_private_slot_into_data(self, two_slots):
        response = two_slots.get(f"/app/{RECIPE}/data/rows.json?key=default&key=acme")
        assert response.status_code == 401 or response.json() != {"fee": 999999}

    def test_reversed_duplicate_key_is_no_better(self, two_slots):
        response = two_slots.get(f"/app/{RECIPE}/data/rows.json?key=acme&key=default")
        assert response.status_code == 401 or response.json() != {"fee": 999999}


class TestVisitorErrorMessages:
    """A refusal must not describe the machine it came from.

    Found by audit 20260817: 404 bodies carried the server's absolute paths,
    slot names, and the names of recipes that were never published.
    """

    @pytest.fixture
    def visitor(self, recipe_dir, state_dir, tmp_path, monkeypatch):
        from frago.recipes import publish as pub
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
        monkeypatch.setattr(pub, "_cache", None, raising=False)
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        security.ensure_token()
        pub.publish(RECIPE)
        return TestClient(create_app(), follow_redirects=False, client=("93.184.216.34", 41234))

    def test_a_directory_that_does_not_exist_yet_does_not_name_itself(
            self, visitor, landing):
        """The landing spot is under this account's id and inside this machine's
        frago home, so naming it in a refusal describes both."""
        landing.rmdir()
        app_state.publish(RECIPE, {"public": {}})
        response = visitor.get(f"/app/{RECIPE}/data/rows.json")
        assert response.status_code == 404
        assert str(landing) not in response.text
        assert "recipe-data" not in response.text

    def test_a_slot_without_a_data_directory_does_not_name_the_slot(self, visitor):
        app_state.publish(RECIPE, {"public": {}})
        response = visitor.get(f"/app/{RECIPE}/data/rows.json")
        assert response.status_code == 404
        assert "dataDir" not in response.text

    def test_a_missing_file_says_only_that(self, visitor, landing):
        app_state.publish(RECIPE, {"public": {}})
        response = visitor.get(f"/app/{RECIPE}/data/nope.json")
        assert response.status_code == 404
        assert str(landing) not in response.text

    def test_the_owner_still_gets_a_useful_diagnosis(self, client, landing, visitor):
        """Scrubbing is for visitors; debugging a page on your own machine needs
        the reason, and here the reason is which directory came up empty."""
        landing.rmdir()
        app_state.publish(RECIPE, {})
        response = client.get(f"/app/{RECIPE}/data/rows.json")
        assert response.status_code == 404
        assert str(landing) in response.text


class TestWhatThePageMayDo:
    """A page's buttons come from the recipe, its audience from the exposure.

    `readOnly` alone said nothing about whether the server would accept a run —
    only whether the requester is the owner. A page drawing a button the run
    gate then refuses already happened (2026-08-23): the refresh was rejected
    and the page wiped its own data.

    So `config.json` answers with the same source the run route reads —
    `page_actions` in the recipe — and the exposure can only subtract from it.
    """

    @pytest.fixture
    def identity_visitor(self, recipe_dir, state_dir, tmp_path, monkeypatch):
        from frago.server import identity as ident
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
        monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
        monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "app-state-users")
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
        monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
        security.ensure_token()
        ident.reset_rate_limits()

        # One sign-in-able account, id of which is looked up to publish by allow list.
        user = ident.create_user("caijia@frago.ai", "correct-horse-battery-staple")
        app = create_app()
        client = TestClient(app, client=("93.184.216.34", 41234))
        signed_in = client.post(
            "/api/auth/login",
            json={"email": "caijia@frago.ai", "password": "correct-horse-battery-staple"},
        )
        # Asserted rather than assumed: an anonymous client is refused an identity
        # page with the same 401 an off-list visitor gets, so a fixture that
        # silently failed to sign in would leave those tests passing for the
        # wrong reason.
        assert signed_in.status_code == 200, signed_in.text
        yield client, user.id
        ident.reset_rate_limits()

    @pytest.fixture
    def opens(self, monkeypatch):
        """Let a test say what the recipe opened to its page."""
        def _set(actions):
            monkeypatch.setattr(
                "frago.recipes.contract.page_actions_of",
                lambda name, wanted=None: tuple(actions),
            )
        return _set

    def test_a_declared_action_reaches_the_page(self, identity_visitor, opens):
        from frago.recipes import publish as pub

        client, account_id = identity_visitor
        opens(["save"])
        pub.publish(RECIPE, mode="identity", allow=[account_id])
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["readOnly"] is True
        assert config["actions"] == ["save"]
        assert config["runnable"] is True
        assert config["apiBase"] is None

    def test_a_recipe_that_opened_nothing_leaves_the_page_read_only(self, identity_visitor, opens):
        from frago.recipes import publish as pub

        client, account_id = identity_visitor
        opens([])
        pub.publish(RECIPE, mode="identity", allow=[account_id])
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["readOnly"] is True
        assert config["actions"] == []
        assert config["runnable"] is False

    def test_a_shared_reading_has_no_buttons_however_the_recipe_declared_itself(
            self, identity_visitor, opens):
        """The exposure subtracts: everyone reads the recipe's own slot, so
        nobody has a directory of their own for a run to land in."""
        from frago.recipes import publish as pub

        client, account_id = identity_visitor
        opens(["save"])
        pub.publish(RECIPE, mode="identity", allow=[account_id], reads=pub.READS_RECIPE)
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["actions"] == []
        assert config["runnable"] is False

    def test_being_signed_in_is_not_enough_the_list_decides(self, identity_visitor, opens):
        """Signing in gets a visitor as far as the gate and no further: an
        off-list account is refused before config.json is ever built, and the
        same session is served once the list names it.

        Both halves are needed. An anonymous client is refused with the same
        401, so a one-sided test would pass for a client that never signed in
        and would prove nothing about the allow list.
        """
        from frago.recipes import publish as pub

        client, account_id = identity_visitor
        opens(["save"])

        pub.publish(RECIPE, mode="identity", allow=["someone-else"])
        assert client.get(f"/app/{RECIPE}/config.json").status_code == 401

        pub.publish(RECIPE, mode="identity", allow=[account_id])
        served = client.get(f"/app/{RECIPE}/config.json")
        assert served.status_code == 200
        assert served.json()["runnable"] is True

    def test_anonymous_visitor_never_sees_runnable(self, recipe_dir, state_dir, tmp_path, monkeypatch):
        from frago.recipes import publish as pub
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
        monkeypatch.setattr(pub, "_cache", None, raising=False)
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        security.ensure_token()
        pub.publish(RECIPE, mode="public")
        visitor = TestClient(create_app(), follow_redirects=False, client=("93.184.216.34", 41234))
        config = visitor.get(f"/app/{RECIPE}/config.json").json()
        assert config["readOnly"] is True
        assert "runnable" not in config
        assert "actions" not in config

    def test_owner_can_run_whatever_they_open(self, client, tmp_path, monkeypatch):
        """The owner's answer does not consult the allow list — the list names
        somebody else here on purpose, and the owner still reads `runnable`.
        """
        from frago.recipes import publish as pub
        from frago.server import security

        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        security.ensure_token()
        app_state.publish(RECIPE, {"dataDir": "/x", "public": {"title": "Q3"}})
        pub.publish(RECIPE, mode="identity", allow=["somebody-else"])
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["dataDir"] == "/x"
        assert config["runnable"] is True


class TestWhichMethodReachesWhichMode:
    """`api/<mode>` is two doors, and the method says which one you are at.

    Read-only is `GET`/`HEAD` and reaches `@export` only; a button press is
    `POST` and reaches `@action` too. Before the split, one admission rule
    ("mode in exports or mode in actions") covered both methods, so any
    `--public` recipe's `@action` was reachable by a plain `GET` from anywhere —
    no CSRF protection anywhere in the path, and `github_star_watch`'s `update`
    (which shells out to `gh` and rewrites three files) was one URL away.

    A shared reading is read-only by construction, so its readers get no
    `@action` here either — the same subtraction `config.json` already applies.
    """

    @pytest.fixture
    def recipe_marks(self, monkeypatch):
        """Say what this recipe exports and what it opens to its page."""
        def _set(*, exports=(), actions=()):
            monkeypatch.setattr(
                "frago.recipes.contract.exports_of",
                lambda name, wanted=None: tuple(exports),
            )
            monkeypatch.setattr(
                "frago.recipes.contract.page_actions_of",
                lambda name, wanted=None: tuple(actions),
            )
        return _set

    @pytest.fixture
    def ran(self, monkeypatch):
        """Stub the recipe execution so a test can see whether it was reached."""
        from frago.server.services import recipe_service

        calls: list[dict] = []

        def _run(name, params=None, timeout=None, ctx=None, show_page=True):
            calls.append({"name": name, "params": params, "ctx": ctx})
            return {"status": "success", "data": {"ok": True}}

        monkeypatch.setattr(recipe_service.RecipeService, "run_recipe", staticmethod(_run))
        return calls

    def test_get_reaches_an_export(self, client, recipe_marks, ran):
        recipe_marks(exports=["stats"])
        response = client.get(f"/app/{RECIPE}/api/stats")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert ran and ran[0]["params"]["mode"] == "stats"

    def test_get_cannot_reach_an_action(self, client, recipe_marks, ran):
        """The regression this class exists for: a GET that triggers a write."""
        recipe_marks(actions=["update"])
        response = client.get(f"/app/{RECIPE}/api/update")
        assert response.status_code == 405
        assert response.headers.get("allow") == "POST"
        assert not ran, "a refused GET must not have run the recipe"

    def test_head_cannot_reach_an_action_either(self, client, recipe_marks, ran):
        """Starlette answers HEAD from the GET handler, so it inherits the rule.

        It used to reach the handler, which meant a request sent purely to fetch
        metadata carried its query string into a recipe execution.
        """
        recipe_marks(actions=["update"])
        response = client.head(f"/app/{RECIPE}/api/update?content=probe")
        assert response.status_code == 405
        assert not ran

    def test_post_still_reaches_an_action(self, client, recipe_marks, ran):
        """The door that must keep working: this is how a button press arrives."""
        recipe_marks(actions=["update"])
        response = client.post(f"/app/{RECIPE}/api/update", json={"content": "hi"})
        assert response.status_code == 200
        assert ran and ran[0]["params"]["content"] == "hi"

    def test_post_also_reaches_an_export(self, client, recipe_marks, ran):
        recipe_marks(exports=["stats"])
        assert client.post(f"/app/{RECIPE}/api/stats", json={}).status_code == 200

    def test_a_mode_the_recipe_never_opened_is_refused_by_every_method(
            self, client, recipe_marks, ran):
        recipe_marks(exports=["stats"], actions=["update"])
        assert client.get(f"/app/{RECIPE}/api/secret").status_code == 403
        assert client.post(f"/app/{RECIPE}/api/secret", json={}).status_code == 403
        assert not ran

    def test_a_shared_reader_cannot_reach_an_action(
            self, recipe_dir, state_dir, tmp_path, monkeypatch, ran):
        """`--shared` promises a read-only page, and `/run` already refuses.

        This door has to agree. Otherwise a reader names an action that
        `config.json` told them they had no buttons for and it runs against the
        machine's own slot — the exposure's promise defeated by the other route.
        """
        from frago.recipes import publish as pub
        from frago.server import identity as ident
        from frago.server import security
        from frago.server.app import create_app

        monkeypatch.setattr(ident, "USERS_PATH", tmp_path / "users.json")
        monkeypatch.setattr(ident, "SESSIONS_DIR", tmp_path / "login-sessions")
        monkeypatch.setattr(ident, "USER_STATE_DIR", tmp_path / "app-state-users")
        monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
        monkeypatch.setattr(pub, "_cache", None, raising=False)
        monkeypatch.setattr(security, "TOKEN_PATH", tmp_path / "server-token")
        monkeypatch.delenv("FRAGO_SIGNUP_GATE", raising=False)
        monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
        security.ensure_token()
        ident.reset_rate_limits()

        monkeypatch.setattr(
            "frago.recipes.contract.exports_of",
            lambda name, wanted=None: ("stats",),
        )
        monkeypatch.setattr(
            "frago.recipes.contract.page_actions_of",
            lambda name, wanted=None: ("update",),
        )

        user = ident.create_user("shared@frago.ai", "correct-horse-battery-staple")
        pub.publish(RECIPE, mode="identity", allow=[user.id], reads=pub.READS_RECIPE)
        client = TestClient(create_app(), client=("93.184.216.34", 41234))
        signed_in = client.post(
            "/api/auth/login",
            json={"email": "shared@frago.ai", "password": "correct-horse-battery-staple"},
        )
        assert signed_in.status_code == 200, signed_in.text

        # The page says so itself: no buttons. Asserted on the whole document,
        # so a fixture that silently fell back to the anonymous branch (where
        # there is no `actions` key at all) fails loudly instead of vacuously.
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config.get("actions") == [], config
        assert config["readOnly"] is True, config

        # And the door agrees. 404 and not 403 because a visitor's 4xx is
        # flattened to one shape by the scrubber in `app.py` — the same answer
        # `/run` gives a shared reader, and deliberately the same one: telling
        # "forbidden" from "no such mode" would describe this machine.
        refused = client.post(f"/app/{RECIPE}/api/update", json={})
        assert refused.status_code == 404, refused.text
        assert not ran, "a shared reader must not have run an action"

        # What a shared reader *may* do is read, which is the whole promise.
        assert client.post(f"/app/{RECIPE}/api/stats", json={}).status_code == 200
        ident.reset_rate_limits()
