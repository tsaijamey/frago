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
def client(recipe_dir, state_dir):
    from frago.server.app import create_app

    return TestClient(create_app(), follow_redirects=False)


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
    def test_serves_from_the_declared_directory_without_copying(self, client, tmp_path):
        data = tmp_path / "board-data"
        data.mkdir()
        (data / "records.json").write_text('{"rows": 3}', encoding="utf-8")
        app_state.publish(RECIPE, {"dataDir": str(data)})

        response = client.get(f"/app/{RECIPE}/data/records.json")
        assert response.status_code == 200
        assert response.json() == {"rows": 3}

    def test_each_slot_reads_its_own_directory(self, client, tmp_path):
        for slot, rows in (("default", 1), ("b", 2)):
            directory = tmp_path / f"data-{slot}"
            directory.mkdir()
            (directory / "n.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
            app_state.publish(RECIPE, {"dataDir": str(directory)}, slot=slot)

        assert client.get(f"/app/{RECIPE}/data/n.json").json()["rows"] == 1
        assert client.get(f"/app/{RECIPE}/data/n.json?key=b").json()["rows"] == 2

    def test_recipe_that_declares_no_directory_says_so(self, client):
        app_state.publish(RECIPE, {"title": "no data here"})
        response = client.get(f"/app/{RECIPE}/data/anything.json")
        assert response.status_code == 404
        assert "dataDir" in response.json()["detail"]

    def test_missing_directory_is_reported_not_crashed(self, client, tmp_path):
        app_state.publish(RECIPE, {"dataDir": str(tmp_path / "gone")})
        assert client.get(f"/app/{RECIPE}/data/x.json").status_code == 404


class TestBoundaries:
    def test_data_route_refuses_to_climb_out(self, client, tmp_path):
        """A page must not be able to read the disk through its own data route."""
        data = tmp_path / "board-data"
        data.mkdir()
        app_state.publish(RECIPE, {"dataDir": str(data)})

        secret = tmp_path / "secret.txt"
        secret.write_text("private", encoding="utf-8")

        response = client.get(
            f"/app/{RECIPE}/data/{Path('..') / 'secret.txt'}", follow_redirects=False
        )
        assert response.status_code in (307, 403, 404)
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
        response = client.get(f"/app/{RECIPE}/config.json")
        assert response.status_code == 200  # sanity: the good name still works
        with pytest.raises(Exception):
            app_pages._assets_dir("../etc")


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
