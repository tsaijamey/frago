"""Moving identity slots from the by-recipe layout to the per-account one.

`app-state-users/<recipe>/<id>.json` becomes `users/<id>/state/<recipe>.json`.
The migration runs on every server start, so "runs twice" is the normal case
rather than the edge case, and most of these tests are about it being boring the
second time.
"""

import json

import pytest

from frago.server import identity


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Redirect the new root and let the legacy one follow it as a sibling.

    Setting only the new root and letting the legacy one default would have the
    migration reach into the real home and move the live server's files into a
    temp directory — which is exactly why `legacy_user_state_dir()` follows.
    """
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    return tmp_path / "app-state-users", tmp_path / "users"


def _legacy_slot(legacy, recipe, account, payload):
    path = legacy / recipe / f"{account}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestTheMove:
    def test_one_file_lands_in_the_account_subtree(self, roots):
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {"public": {"n": 1}})

        assert identity.migrate_user_state() == 1

        moved = new / "aaaa1111" / "state" / "kline.json"
        assert moved.is_file()
        assert json.loads(moved.read_text(encoding="utf-8")) == {"public": {"n": 1}}

    def test_one_account_across_several_recipes_collapses_into_one_subtree(self, roots):
        legacy, new = roots
        for recipe in ("kline", "ledger", "board"):
            _legacy_slot(legacy, recipe, "aaaa1111", {"r": recipe})

        assert identity.migrate_user_state() == 3

        state = new / "aaaa1111" / "state"
        assert sorted(p.name for p in state.glob("*.json")) == [
            "board.json", "kline.json", "ledger.json"
        ]

    def test_several_accounts_stay_apart(self, roots):
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {"who": "first"})
        _legacy_slot(legacy, "kline", "bbbb2222", {"who": "second"})

        identity.migrate_user_state()

        first = new / "aaaa1111" / "state" / "kline.json"
        second = new / "bbbb2222" / "state" / "kline.json"
        assert json.loads(first.read_text(encoding="utf-8"))["who"] == "first"
        assert json.loads(second.read_text(encoding="utf-8"))["who"] == "second"

    def test_the_old_root_is_left_empty_and_gone(self, roots):
        """An empty recipe directory left behind reads as "this recipe has
        users", which is the thing that is no longer true."""
        legacy, _ = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {})
        identity.migrate_user_state()
        assert not legacy.exists()


class TestRunningItAgain:
    def test_twice_is_the_same_as_once(self, roots):
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {"n": 1})

        first = identity.migrate_user_state()
        second = identity.migrate_user_state()

        assert (first, second) == (1, 0)
        assert (new / "aaaa1111" / "state" / "kline.json").is_file()

    def test_nothing_to_do_is_not_an_error(self, roots):
        assert identity.migrate_user_state() == 0

    def test_an_interrupted_run_resumes(self, roots):
        """Each file moves on its own by rename, which has no half-way state,
        so a run that died part-way leaves the rest where the next run finds
        it."""
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {})
        _legacy_slot(legacy, "ledger", "aaaa1111", {})

        # Stand in for "the first run moved one file and died".
        (new / "aaaa1111" / "state").mkdir(parents=True)
        (legacy / "kline" / "aaaa1111.json").rename(
            new / "aaaa1111" / "state" / "kline.json"
        )

        assert identity.migrate_user_state() == 1
        assert (new / "aaaa1111" / "state" / "ledger.json").is_file()


class TestMixedLayouts:
    def test_the_newer_file_wins_and_the_old_one_is_not_overwritten(self, roots):
        """A server that started writing the new layout before this ran holds
        the live data. Overwriting it with a copy from before the restart would
        be the migration losing a visitor's work."""
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {"who": "stale"})
        target = new / "aaaa1111" / "state" / "kline.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"who": "live"}), encoding="utf-8")

        assert identity.migrate_user_state() == 0
        assert json.loads(target.read_text(encoding="utf-8"))["who"] == "live"

    def test_a_name_that_is_not_an_account_id_is_skipped(self, roots):
        """These names come off the filesystem and become directory names, so
        they are checked rather than trusted."""
        legacy, new = roots
        bad = legacy / "kline" / "not an account id.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{}", encoding="utf-8")

        assert identity.migrate_user_state() == 0
        assert bad.is_file(), "a name it refuses to read is a name it leaves alone"

    def test_nothing_lands_outside_the_new_root(self, roots):
        """The guard that matters is not "which names look odd" but "can any
        of them escape". Whatever the migration decides to move, it moves
        inside `users/`."""
        legacy, new = roots
        for name in ("...json", "..json", ".json", "aaaa1111.json"):
            path = legacy / "kline" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

        identity.migrate_user_state()

        for moved in new.rglob("*.json"):
            assert moved.resolve().is_relative_to(new.resolve())


class TestPermissions:
    def test_every_level_is_private_after_the_move(self, roots):
        legacy, new = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {})
        identity.migrate_user_state()

        for level in (new, new / "aaaa1111", new / "aaaa1111" / "state"):
            assert level.stat().st_mode & 0o077 == 0, f"{level} is readable by others"
        assert (new / "aaaa1111" / "state" / "kline.json").stat().st_mode & 0o077 == 0


class TestHasDataAgrees:
    def test_the_answer_is_the_same_before_and_after(self, roots):
        """`has_data` is what separates a real visitor from a flooded-in
        account, so the migration must not change anyone's answer."""
        legacy, _ = roots
        _legacy_slot(legacy, "kline", "aaaa1111", {})

        identity.migrate_user_state()

        assert identity.has_data("aaaa1111") is True
        assert identity.has_data("never_here") is False

    def test_an_empty_id_is_not_data(self, roots):
        assert identity.has_data("") is False
