"""What a recipe does not get to decide once someone else is the caller.

Every test here is a recipe doing something entirely reasonable — naming its
slot, passing the directory it has always used — and the platform overruling it.
The distinction the tests exist to hold is between *overriding* and *defaulting*:
a default means the recipe wins whenever it passes something, which hands the
key back to the code the isolation is supposed to survive.
"""

import json

import pytest

from frago.recipes import app_state, context


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point both roots into a temp directory and keep them apart there too."""
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "app-state")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    return tmp_path


@pytest.fixture
def as_visitor(monkeypatch, roots):
    account = "a1b2c3d4"
    data_dir = roots / "users" / account / "data" / "kline"
    monkeypatch.setenv(context.CALLER_ENV, "visitor")
    monkeypatch.setenv(context.SLOT_ENV, account)
    monkeypatch.setenv(context.DATA_DIR_ENV, str(data_dir))
    return account, data_dir


class TestTheRecipeDoesNotChooseTheSlot:
    def test_a_named_slot_is_ignored_in_favour_of_the_account(self, roots, as_visitor):
        account, _ = as_visitor
        path = app_state.publish("kline", {"public": {"n": 1}}, slot="default")
        assert path == roots / "users" / account / "state" / "kline.json"

    def test_even_an_unrelated_slot_name_is_ignored(self, roots, as_visitor):
        account, _ = as_visitor
        path = app_state.publish("kline", {}, slot="someone_elses_account")
        assert path.parent.parent.name == account

    def test_identity_false_is_ignored(self, roots, as_visitor):
        """A recipe passing identity=False must not be able to write itself
        out of the identity root."""
        account, _ = as_visitor
        path = app_state.publish("kline", {}, slot="default", identity=False)
        assert (roots / "users" / account / "state" / "kline.json").is_file()
        assert path.is_relative_to(roots / "users")


class TestTheRecipeDoesNotChooseTheDirectory:
    def test_data_dir_is_replaced_not_filled_in(self, roots, as_visitor):
        """The recipe hard-codes the owner's directory — which was the correct
        thing to write before any of this existed. Publishing it into a
        visitor's slot would serve the owner's files to that visitor, rendering
        perfectly and saying nothing."""
        _, expected = as_visitor
        path = app_state.publish(
            "kline",
            {"dataDir": "/Users/owner/.frago/data/stock/recipe-caches/kline"},
            slot="default",
        )
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["dataDir"] == str(expected)

    def test_the_rest_of_the_state_survives(self, roots, as_visitor):
        path = app_state.publish("kline", {"public": {"title": "x"}, "keep": 1})
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["public"] == {"title": "x"}
        assert written["keep"] == 1

    def test_the_caller_s_dict_is_not_mutated(self, roots, as_visitor):
        state = {"dataDir": "/Users/owner/somewhere"}
        app_state.publish("kline", state)
        assert state["dataDir"] == "/Users/owner/somewhere"


class TestRefusalRatherThanFallback:
    def test_a_blank_slot_refuses_to_write(self, roots, monkeypatch):
        """`default` belongs to the recipe, i.e. to the owner's page. Landing
        there would both pollute the owner's page and let the next visitor read
        the previous one's data."""
        monkeypatch.setenv(context.CALLER_ENV, "visitor")
        monkeypatch.setenv(context.SLOT_ENV, "")
        monkeypatch.setenv(context.DATA_DIR_ENV, str(roots / "d"))
        with pytest.raises(context.InvalidInvocationContext):
            app_state.publish("kline", {})
        assert not (roots / "app-state" / "kline").exists()

    def test_an_unknown_caller_refuses_to_write(self, roots, monkeypatch):
        monkeypatch.setenv(context.CALLER_ENV, "guest")
        with pytest.raises(context.InvalidInvocationContext):
            app_state.publish("kline", {})


class TestTheOwnerPathIsUnchanged:
    def test_owner_still_writes_the_recipe_s_own_slot(self, roots, monkeypatch):
        monkeypatch.delenv(context.CALLER_ENV, raising=False)
        path = app_state.publish("kline", {"dataDir": "/Users/owner/mine"}, slot="default")
        assert path == roots / "app-state" / "kline" / "default.json"
        assert json.loads(path.read_text(encoding="utf-8"))["dataDir"] == "/Users/owner/mine"

    def test_owner_can_still_name_slots(self, roots, monkeypatch):
        monkeypatch.delenv(context.CALLER_ENV, raising=False)
        app_state.publish("kline", {}, slot="acme")
        assert (roots / "app-state" / "kline" / "acme.json").is_file()


class TestTwoPeopleDoNotShare:
    def test_each_account_reads_its_own(self, roots, monkeypatch):
        for account, value in (("aaaa1111", "first"), ("bbbb2222", "second")):
            monkeypatch.setenv(context.CALLER_ENV, "visitor")
            monkeypatch.setenv(context.SLOT_ENV, account)
            monkeypatch.setenv(context.DATA_DIR_ENV, str(roots / "users" / account / "data" / "kline"))
            app_state.publish("kline", {"public": {"who": value}})

        monkeypatch.delenv(context.CALLER_ENV, raising=False)
        first = app_state.read("kline", "aaaa1111", identity=True)
        second = app_state.read("kline", "bbbb2222", identity=True)
        assert first["public"]["who"] == "first"
        assert second["public"]["who"] == "second"

    def test_a_visitor_who_never_ran_reads_empty_rather_than_raising(self, roots, monkeypatch):
        monkeypatch.delenv(context.CALLER_ENV, raising=False)
        assert app_state.read("kline", "never_here", identity=True) == {}


class TestPermissions:
    def test_every_level_of_the_account_subtree_is_private(self, roots, as_visitor):
        """`mkdir(parents=True)` builds the middle level under the umask. The
        files inside are 0600, but a 0755 `users/<id>/` hands a second unix
        account on this machine every account id on the server."""
        account, _ = as_visitor
        app_state.publish("kline", {})
        users = roots / "users"
        for level in (users, users / account, users / account / "state"):
            assert level.stat().st_mode & 0o077 == 0, f"{level} is readable by others"
