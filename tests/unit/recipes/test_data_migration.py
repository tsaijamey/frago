"""Moving recipe data onto the new layout without becoming the bug it fixes.

The failure that prompted the layout change was one ledger existing in four
places, drifting apart, with nothing raising. A migration tool is one copy
operation after another, so it is the single easiest place to reproduce exactly
that — which is why almost every test here is about not losing anything and
about refusing to guess.
"""

import json

import pytest

from frago.recipes import app_state, data_migration

WHO = "a" * 32
RECIPE = "demo_board"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A frago home of its own, with nothing of the real one reachable."""
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / ".frago" / "app-state")
    monkeypatch.setattr(app_state, "USER_STATE_DIR", tmp_path / ".frago" / "users")
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / ".frago" / "users"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / ".frago" / "app-state").mkdir(parents=True)
    return tmp_path


def _slot(home, recipe, slot, state):
    d = home / ".frago" / "app-state" / recipe
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slot}.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _data(home, *parts, files=(("rows.json", '{"n": 1}'),)):
    d = home.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files:
        (d / name).write_text(body, encoding="utf-8")
    return d


class TestPlanningTouchesNothing:
    def test_a_derivable_slot_becomes_a_move(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "board")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert [m.recipe for m in result.moves] == [RECIPE]
        assert result.moves[0].source == source

    def test_the_single_instance_case_gets_no_project_level(self, home):
        source = _data(home, ".frago", "data", "x")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        target = data_migration.plan(WHO, home).moves[0].target
        assert target == app_state.recipe_data_dir(WHO, RECIPE)
        assert app_state.PROJECTS_DIR not in target.parts

    def test_a_named_slot_becomes_a_project(self, home):
        source = _data(home, ".frago", "data", "y")
        _slot(home, RECIPE, "20260727-lenovo-demo", {"dataDir": str(source)})
        target = data_migration.plan(WHO, home).moves[0].target
        assert target == app_state.recipe_data_dir(WHO, RECIPE, "20260727-lenovo-demo")

    def test_planning_writes_nothing(self, home):
        source = _data(home, ".frago", "data", "z")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        before = sorted(p.relative_to(home) for p in home.rglob("*"))
        data_migration.plan(WHO, home)
        assert sorted(p.relative_to(home) for p in home.rglob("*")) == before


class TestWhatCannotBeWorkedOutIsListedNotGuessed:
    def test_a_recipe_invented_key_is_reported_for_a_person(self, home):
        _data(home, ".frago", "data", "videos", "one")
        _slot(home, RECIPE, "default", {"projectDir": str(home / ".frago/data/videos/one")})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert result.unresolved[0].keys == ("projectDir",)

    def test_a_slot_holding_both_moves_the_known_half_and_reports_the_rest(self, home):
        source = _data(home, ".frago", "data", "known")
        _slot(home, RECIPE, "default", {
            "dataDir": str(source),
            "ledgerPath": str(home / ".frago/data/elsewhere/ledger.json"),
        })
        result = data_migration.plan(WHO, home)
        assert len(result.moves) == 1
        assert result.unresolved[0].keys == ("ledgerPath",)

    def test_a_slot_with_nothing_to_move_is_skipped_with_a_reason(self, home):
        _slot(home, RECIPE, "default", {"public": {"title": "Q3"}})
        result = data_migration.plan(WHO, home)
        assert not result.moves and not result.unresolved
        assert result.skipped[0][0] == RECIPE

    def test_a_directory_that_no_longer_exists_is_skipped_not_created(self, home):
        gone = home / ".frago" / "data" / "gone"
        _slot(home, RECIPE, "default", {"dataDir": str(gone)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert not gone.exists()


class TestNothingIsEverLost:
    def _one(self, home):
        source = _data(home, ".frago", "data", "etf", "ledger",
                       files=(("ledger.json", '{"trades": []}'), ("prices.json", "{}")))
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        return data_migration.plan(WHO, home).moves[0]

    def test_the_original_is_still_there_afterwards(self, home):
        one = self._one(home)
        data_migration.apply(one, home)
        assert one.source.is_dir()
        assert (one.source / "ledger.json").read_text(encoding="utf-8") == '{"trades": []}'

    def test_the_copy_landed_whole(self, home):
        one = self._one(home)
        data_migration.apply(one, home)
        assert sorted(p.name for p in one.target.iterdir()) == ["ledger.json", "prices.json"]

    def test_a_target_that_already_holds_something_else_refuses(self, home):
        """Two different things under one name is the disease. Refusing costs a
        person one question; overwriting costs them whichever copy was real."""
        one = self._one(home)
        one.target.mkdir(parents=True)
        (one.target / "someone-elses.json").write_text("{}", encoding="utf-8")
        with pytest.raises(data_migration.MigrationFailed):
            data_migration.apply(one, home)
        assert (one.target / "someone-elses.json").is_file()

    def test_running_it_twice_is_the_same_as_running_it_once(self, home):
        one = self._one(home)
        data_migration.apply(one, home)
        again = data_migration.apply(one, home)
        assert "跳过" in again["note"]
        assert one.source.is_dir()


class TestTheManifestIsWhatMakesTheCopiesSafe:
    def _migrated(self, home):
        source = _data(home, ".frago", "data", "etf", "ledger")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        one = data_migration.plan(WHO, home).moves[0]
        return one, data_migration.apply(one, home)

    def test_it_records_both_ends_of_the_move(self, home):
        one, entry = self._migrated(home)
        assert entry["source"] == str(one.source)
        assert entry["target"] == str(one.target)

    def test_it_says_the_original_was_kept(self, home):
        """The question this answers months later is whether the old directory
        is still live. Recording the copy without recording that is useless."""
        _, entry = self._migrated(home)
        assert entry["source_kept"] is True

    def test_it_is_appended_to_never_rewritten(self, home):
        self._migrated(home)
        source = _data(home, ".frago", "data", "second")
        _slot(home, "other_board", "default", {"dataDir": str(source)})
        for move in data_migration.plan(WHO, home).moves:
            data_migration.apply(move, home)
        lines = data_migration.manifest_path(home).read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2
        assert {json.loads(x)["recipe"] for x in lines} >= {RECIPE, "other_board"}

    def test_it_can_be_asked_what_has_already_moved(self, home):
        self._migrated(home)
        assert (RECIPE, "default") in data_migration.already_migrated(home)
