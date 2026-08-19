"""Phase 1 end to end: a recipe runs for someone, and that someone reads it back.

The unit tests either side of this one each hold half the claim — that a recipe
started in a visitor context writes the account's subtree, and that a signed-in
request reads the account's subtree. Neither notices if the two halves name
different directories, which is the whole failure mode of moving a root.

So this runs the real `create_app()` with the deployment switches on, publishes
the way a recipe actually publishes (through `app_state`, with the context
supplied by environment variables the way `runner` supplies them), and then asks
for the page over HTTP as the visitor.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state, context
from frago.recipes import publish as pub
from frago.recipes.exceptions import RecipeNotFoundError
from frago.server import identity as ident
from frago.server import security

RECIPE = "ledger"
PASSWORD = "correct-horse-battery"

# A public address, so nothing here can be mistaken for the owner at the gate.
VISITOR = ("93.184.216.34", 41234)


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """A frago configured the way the deployment guide says a server must be."""
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

    assets = tmp_path / "recipes" / RECIPE / "assets"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("<h1>ledger</h1>", encoding="utf-8")

    class _Meta:
        ui_from = None

    class _Recipe:
        base_dir = tmp_path / "recipes" / RECIPE
        script_path = tmp_path / "recipes" / RECIPE / "recipe.py"
        metadata = _Meta()

    class _Registry:
        def find(self, name, source=None):
            if name != RECIPE:
                raise RecipeNotFoundError(name, [])
            return _Recipe()

    monkeypatch.setattr("frago.recipes.registry.get_registry", lambda: _Registry())

    pub.publish(RECIPE, mode=pub.MODE_IDENTITY)
    yield tmp_path
    ident.reset_rate_limits()


def _run_as(account_id: str, recipe: str, write) -> None:
    """Do what a recipe process does, in the environment `runner` gives it.

    The context arrives as three environment variables and nothing else,
    because that is all a recipe ever gets — most of them cannot import frago
    at all.
    """
    data_dir = app_state.user_data_dir(account_id, recipe)
    env = dict(os.environ)
    context.apply_to_env(
        env,
        context.InvocationContext(
            caller=context.VISITOR, slot=account_id, data_dir=data_dir
        ),
    )
    previous = {k: os.environ.get(k) for k in context.CONTEXT_ENV_KEYS}
    os.environ.update({k: env[k] for k in context.CONTEXT_ENV_KEYS})
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        write(data_dir)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _signed_in(cookie: str) -> TestClient:
    from frago.server.app import create_app

    client = TestClient(create_app(), follow_redirects=False, client=VISITOR)
    client.cookies.set(ident.COOKIE_NAME, cookie)
    return client


@pytest.fixture
def two_people(deployment):
    people = {}
    for who, email in (("zhang", "zhang@example.com"), ("li", "li@example.com")):
        user = ident.create_user(email, PASSWORD)

        def write(data_dir, who=who):
            (data_dir / "rows.json").write_text(json.dumps([who]), encoding="utf-8")
            # The recipe names its own slot and hands over the directory it has
            # always used. Both are wrong here, and both are overruled.
            app_state.publish(
                RECIPE,
                {
                    "dataDir": "/Users/owner/.frago/data/promo/recipe-caches/ledger",
                    "apiKey": f"sk-{who}-PRIVATE",
                    "public": {"title": who},
                },
                slot="default",
            )

        _run_as(user.id, RECIPE, write)
        people[who] = {"id": user.id, "cookie": ident.create_session(user.id)}
    return people


class TestTheTwoHalvesMeet:
    def test_what_the_run_wrote_is_what_the_page_serves(self, two_people):
        client = _signed_in(two_people["zhang"]["cookie"])
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert config["slot"] == two_people["zhang"]["id"]
        assert config["title"] == "zhang"
        assert client.get(f"/app/{RECIPE}/data/rows.json").json() == ["zhang"]

    def test_the_other_person_gets_their_own(self, two_people):
        client = _signed_in(two_people["li"]["cookie"])
        assert client.get(f"/app/{RECIPE}/data/rows.json").json() == ["li"]

    def test_the_owner_s_directory_is_never_served(self, two_people):
        """The recipe published the owner's absolute path. If that survived,
        this page would render perfectly while showing the wrong files."""
        client = _signed_in(two_people["zhang"]["cookie"])
        config = client.get(f"/app/{RECIPE}/config.json").json()
        assert "dataDir" not in config
        assert "apiKey" not in config

    def test_on_disk_each_account_owns_one_subtree(self, deployment, two_people):
        users = deployment / "users"
        for who in ("zhang", "li"):
            account = users / two_people[who]["id"]
            assert (account / "state" / f"{RECIPE}.json").is_file()
            assert (account / "data" / RECIPE / "rows.json").is_file()
        assert not (deployment / "app-state" / RECIPE).exists(), (
            "a visitor run must not touch the recipe's own slots"
        )

    def test_the_published_state_points_at_the_account_s_own_directory(
        self, deployment, two_people
    ):
        account = deployment / "users" / two_people["zhang"]["id"]
        written = json.loads((account / "state" / f"{RECIPE}.json").read_text("utf-8"))
        assert written["dataDir"] == str(account / "data" / RECIPE)


class TestTheGateStillHolds:
    def test_anonymous_gets_nothing(self, deployment, two_people):
        from frago.server.app import create_app

        anon = TestClient(create_app(), follow_redirects=False, client=VISITOR)
        assert anon.get(f"/app/{RECIPE}/config.json").status_code == 401
        assert anon.get(f"/app/{RECIPE}/data/rows.json").status_code == 401

    def test_a_visitor_cannot_ask_for_the_other_account(self, two_people):
        client = _signed_in(two_people["li"]["cookie"])
        other = two_people["zhang"]["id"]
        assert client.get(f"/app/{RECIPE}/data/rows.json?key={other}").status_code == 401

    def test_running_code_is_still_out_of_reach(self, two_people):
        """Phase 1 adds no way for a visitor to make the server do anything.
        That arrives in Phase 3, behind its own gate."""
        client = _signed_in(two_people["zhang"]["cookie"])
        assert client.post(f"/api/recipes/{RECIPE}/run", json={}).status_code == 401
        assert client.get("/api/file", params={"path": "/etc/passwd"}).status_code == 401


class TestOwnerRunsAreUntouched:
    def test_an_owner_run_writes_the_recipe_s_own_slot(self, deployment):
        app_state.publish(RECIPE, {"dataDir": "/Users/owner/mine"}, slot="default")
        own = deployment / "app-state" / RECIPE / "default.json"
        assert own.is_file()
        assert json.loads(own.read_text("utf-8"))["dataDir"] == "/Users/owner/mine"
        assert not (deployment / "users").exists() or not any(
            (deployment / "users").iterdir()
        )

    def test_an_inherited_visitor_variable_does_not_leak_into_an_owner_run(
        self, deployment, monkeypatch
    ):
        """A `.env` or a server process that inherited these would otherwise
        turn every owner run into someone else's."""
        monkeypatch.setenv(context.CALLER_ENV, "visitor")
        monkeypatch.setenv(context.SLOT_ENV, "somebody")
        monkeypatch.setenv(context.DATA_DIR_ENV, str(deployment / "elsewhere"))

        env = dict(os.environ)
        context.apply_to_env(env, None)

        for key in context.CONTEXT_ENV_KEYS:
            assert key not in env
