"""`frago recipe publish --identity`, and why the rules do not live in this command.

Dozens of recipes publish their page state by shelling out to this command
rather than importing anything, because a recipe carrying a PEP 723 block runs
in an isolated environment where `import frago` fails. That makes this command a
second front door to the state layer — and a front door is exactly where a rule
enforced somewhere else stops being enforced.

So the tests here come in two halves. The first is the flag doing what it says
for the owner. The second is the part that matters: started inside a visitor
run, this command writes that visitor's slot no matter what the recipe asked
for, because the rules live one layer down in `app_state.publish()`.
"""

import json

import pytest
from click.testing import CliRunner

from frago.recipes import app_state, context

ACCOUNT = "a1b2c3d4e5f6"


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    for key in context.CONTEXT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def _publish(args, state):
    from frago.cli.recipe_commands import publish_state

    return CliRunner().invoke(publish_state, args, input=json.dumps(state))


class TestTheOwnerUsesTheFlag:
    def test_identity_writes_the_named_account_s_slot(self, roots):
        result = _publish(["ledger", "--slot", ACCOUNT, "--identity"], {"public": {"n": 1}})
        assert result.exit_code == 0, result.output
        written = roots / "users" / ACCOUNT / "state" / "ledger.json"
        assert written.is_file()
        assert json.loads(written.read_text("utf-8"))["public"] == {"n": 1}

    def test_without_the_flag_it_writes_the_recipe_s_own_slot(self, roots):
        result = _publish(["ledger", "--slot", "default"], {"public": {"n": 1}})
        assert result.exit_code == 0, result.output
        assert (roots / "app-state" / "ledger" / "default.json").is_file()
        assert not (roots / "users").exists()

    def test_an_identity_url_never_names_the_slot(self, roots):
        """The gate decides which slot a visitor reads, so an address naming one
        would be both wrong and a copy of an account id in whatever the recipe
        logs next."""
        result = _publish(["ledger", "--slot", ACCOUNT, "--identity"], {})
        assert ACCOUNT not in result.output
        assert result.output.strip().endswith("/app/ledger")

    def test_an_ordinary_slot_still_appears_in_the_url(self, roots):
        result = _publish(["ledger", "--slot", "acme"], {})
        assert "key=acme" in result.output


class TestInsideAVisitorRunTheFlagsStopMattering:
    @pytest.fixture(autouse=True)
    def as_visitor(self, roots, monkeypatch):
        monkeypatch.setenv(context.CALLER_ENV, "visitor")
        monkeypatch.setenv(context.SLOT_ENV, ACCOUNT)
        monkeypatch.setenv(
            context.DATA_DIR_ENV, str(roots / "users" / ACCOUNT / "data" / "ledger")
        )

    def test_a_recipe_asking_for_its_own_slot_still_writes_the_visitor_s(self, roots):
        """This is the ordinary case, not a hostile one: the recipe was written
        before any of this existed and publishes `--slot default` because that
        was always right."""
        result = _publish(["ledger", "--slot", "default"], {"public": {"n": 1}})
        assert result.exit_code == 0, result.output
        assert (roots / "users" / ACCOUNT / "state" / "ledger.json").is_file()
        assert not (roots / "app-state" / "ledger").exists()

    def test_naming_someone_else_s_account_does_not_reach_them(self, roots):
        result = _publish(["ledger", "--slot", "ffff0000ffff", "--identity"], {})
        assert result.exit_code == 0, result.output
        assert (roots / "users" / ACCOUNT / "state" / "ledger.json").is_file()
        assert not (roots / "users" / "ffff0000ffff").exists()

    def test_the_owner_s_directory_is_replaced_in_what_gets_written(self, roots):
        _publish(
            ["ledger", "--slot", "default"],
            {"dataDir": "/Users/owner/.frago/data/promo/recipe-caches/ledger"},
        )
        written = json.loads(
            (roots / "users" / ACCOUNT / "state" / "ledger.json").read_text("utf-8")
        )
        assert written["dataDir"] == str(roots / "users" / ACCOUNT / "data" / "ledger")

    def test_the_url_it_prints_carries_no_account_id(self, roots):
        result = _publish(["ledger", "--slot", "default"], {})
        assert ACCOUNT not in result.output


class TestBrokenContextIsRefusedRatherThanRedirected:
    def test_a_visitor_run_without_a_slot_fails_loudly(self, roots, monkeypatch):
        """`default` belongs to the recipe. Landing there would pollute the
        owner's page and hand the next visitor the previous one's data."""
        monkeypatch.setenv(context.CALLER_ENV, "visitor")
        monkeypatch.setenv(context.SLOT_ENV, "")
        monkeypatch.setenv(context.DATA_DIR_ENV, str(roots / "d"))

        result = _publish(["ledger", "--slot", "default"], {})

        assert result.exit_code == 1
        assert not (roots / "app-state" / "ledger").exists()

    def test_an_unknown_caller_fails_loudly(self, roots, monkeypatch):
        monkeypatch.setenv(context.CALLER_ENV, "guest")
        result = _publish(["ledger", "--slot", "default"], {})
        assert result.exit_code == 1
        assert not (roots / "app-state" / "ledger").exists()
