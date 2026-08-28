"""Whose page a module writes when it publishes through the hub.

``app_state.publish`` answers that by reading the environment of the process it
runs in. Inside a recipe that is exactly right. Inside the hub it is exactly
wrong, because the process the hub runs in is the server — so a recipe started
for a signed-in visitor published into the *recipe's own* slot instead of
theirs. Two consequences, neither of which reports anything: the visitor's page
stays empty however many times they press the button, and the owner's page is
overwritten by a stranger's render state.

``bus_ask`` had the same hole on the reading side and was closed on 2026-08-26
with the same key — the execution id the caller carries, looked up in the runs
this process started, never a header the caller could choose. These are the
tests for that fix applied to the other verb.
"""

import json

import pytest
from fastapi.testclient import TestClient

from frago.recipes import app_state, context
from frago.recipes import runner as recipe_runner

RECIPE = "video_pipeline_studio"
ACCOUNT = "0123456789abcdef0123456789abcdef"
EXECUTION = "exec-1234"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    monkeypatch.delenv("FRAGO_BEHIND_PROXY", raising=False)
    # The server process must not itself look like a visitor: that is the state
    # this whole fix is about not relying on.
    for key in context.CONTEXT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


@pytest.fixture
def client(roots):
    from frago.server.app import create_app

    return TestClient(create_app(), follow_redirects=False, client=("127.0.0.1", 5555))


@pytest.fixture
def visitor_run(roots):
    """A run this process started for a signed-in account, as the hub sees it."""
    data_dir = roots / "users" / ACCOUNT / "data" / RECIPE
    ctx = context.InvocationContext(
        caller=context.VISITOR, slot=ACCOUNT, data_dir=data_dir
    )
    recipe_runner._remember_run_context(EXECUTION, ctx)
    yield data_dir
    recipe_runner._forget_run_context(EXECUTION)


def _publish(client, state, execution=None):
    headers = {"X-Frago-Recipe": RECIPE}
    if execution:
        headers["X-Frago-Execution"] = execution
    return client.post(
        "/api/bus/publish",
        json={"recipe": RECIPE, "slot": "20260827-a-film", "state": state},
        headers=headers,
    )


class TestARunStartedForSomebodyWritesTheirPage:
    def test_it_lands_in_that_account_s_slot(self, client, visitor_run, roots):
        assert _publish(client, {"public": {"project": "20260827-a-film"}},
                        EXECUTION).status_code == 200
        written = roots / "users" / ACCOUNT / "state" / f"{RECIPE}.json"
        assert written.is_file()
        assert json.loads(written.read_text("utf-8"))["public"]["project"] == "20260827-a-film"

    def test_the_recipe_s_own_slot_is_left_alone(self, client, visitor_run, roots):
        """The half that has teeth: without this, a signed-in stranger pressing
        a button replaces what the owner's page renders."""
        app_state.publish(RECIPE, {"project": "20260827-a-film", "title": "the owner's"},
                          slot="20260827-a-film")
        _publish(client, {"project": "somebody else's"}, EXECUTION)
        assert app_state.read(RECIPE, "20260827-a-film") == {
            "project": "20260827-a-film", "title": "the owner's"
        }

    def test_the_data_directory_is_the_platform_s_answer_not_the_recipe_s(
        self, client, visitor_run, roots
    ):
        """A recipe that hard-codes the owner's directory — the correct thing to
        write before any of this existed — must not put that path where
        `/app/<name>/data/…` will serve it to a visitor."""
        _publish(client, {"dataDir": "/Users/owner/.frago/data/films"}, EXECUTION)
        written = json.loads(
            (roots / "users" / ACCOUNT / "state" / f"{RECIPE}.json").read_text("utf-8")
        )
        assert written["dataDir"] == str(visitor_run)

    def test_the_address_handed_back_names_no_slot(self, client, visitor_run):
        """A visitor's slot is their account id and the access gate decides it;
        `?key=` is the owner's control alone. An address carrying the account id
        would be both useless and a leak."""
        url = _publish(client, {"public": {}}, EXECUTION).json()["url"]
        assert "key=" not in url
        assert ACCOUNT not in url


class TestTheOwnerIsUnchanged:
    def test_a_run_with_no_execution_id_publishes_the_named_slot(self, client, roots):
        assert _publish(client, {"project": "20260827-a-film"}).status_code == 200
        assert app_state.read(RECIPE, "20260827-a-film")["project"] == "20260827-a-film"

    def test_an_execution_this_process_never_started_falls_back_to_the_owner(
        self, client, roots
    ):
        """The CLI, another machine, a run from before a restart. No entry means
        no claim about who this is for — not a licence to guess."""
        assert _publish(client, {"project": "20260827-a-film"}, "never-seen").status_code == 200
        assert app_state.read(RECIPE, "20260827-a-film")["project"] == "20260827-a-film"

    def test_an_owner_run_that_knows_whose_it_is_still_names_its_own_slot(
        self, client, roots
    ):
        """An owner context carries a slot too (the machine's identity). That is
        not a visitor and must not be routed like one."""
        ctx = context.InvocationContext(caller=context.OWNER, slot="deadbeef" * 4)
        recipe_runner._remember_run_context("owner-exec", ctx)
        try:
            _publish(client, {"project": "20260827-a-film"}, "owner-exec")
            assert app_state.read(RECIPE, "20260827-a-film")["project"] == "20260827-a-film"
        finally:
            recipe_runner._forget_run_context("owner-exec")
