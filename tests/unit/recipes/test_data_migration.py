"""Moving recipe data onto the new layout without becoming the bug it fixes.

The failure that prompted the layout change was one ledger existing in four
places, drifting apart, with nothing raising. A migration tool is one copy
operation after another, so it is the single easiest place to reproduce exactly
that — which is why almost every test here is about not losing anything and
about refusing to guess.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

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


class TestTheThingsItRefusesToMove:
    """Three shapes it must recognise and stop on. Each was found by running the
    plan against a real machine before running it for effect — every one of them
    would have looked like a successful migration.
    """

    def test_two_slots_claiming_one_directory_stops_it(self, home):
        """The defect itself: the platform thinks there are two bodies of work
        and the disk holds one. Copying it makes two that then drift apart —
        this tool committing, by hand, the failure it exists to end."""
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "ledger")
        _slot(home, "trade_history", "default", {"dataDir": str(source)})
        _slot(home, "trade_ledger", "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert {b[0] for b in result.blocked} == {"trade_history", "trade_ledger"}
        assert "变成几份" in result.blocked[0][2]

    def test_a_dated_deliverable_directory_stays_where_it_is(self, home):
        """`data/<subject>/<date>-<slug>/` is somebody's filed work. Pulling it
        into the recipe tree files it where nobody looks and leaves the original
        as the copy people actually open."""
        source = _data(home, ".frago", "data", "one-off", "20260527-tau-deepdive")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert "交付物" in result.blocked[0][2]

    def test_a_directory_inside_a_recipes_own_package_stays(self, home):
        source = _data(home, ".frago", "recipes", "workflows", RECIPE, "model")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert "代码包" in result.blocked[0][2]

    def test_an_ordinary_directory_is_still_moved(self, home):
        """The gates must not swallow the normal case."""
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "board")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert len(result.moves) == 1 and not result.blocked

    def test_a_dated_directory_deeper_down_is_still_caught(self, home):
        """The date can sit at either level; `must-data-dir` puts it at the
        second, but a recipe pointing one level further in is the same claim."""
        source = _data(home, ".frago", "data", "etf", "20260807-composite", "out")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        assert not data_migration.plan(WHO, home).moves


class TestADryRunTellsTheTruth:
    def test_something_already_copied_is_not_reported_as_pending(self, home):
        """A dry run that describes finished work as pending is a dry run nobody
        can act on, and the whole reason for having one is that it can be."""
        source = _data(home, ".frago", "data", "etf", "board")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        one = data_migration.plan(WHO, home).moves[0]
        data_migration.apply(one, home)

        again = data_migration.plan(WHO, home)
        assert not again.moves
        assert any("已经搬过" in why for _, _, why in again.skipped)

    def test_a_half_copied_target_is_still_reported_as_pending(self, home):
        """Interrupted, not finished. It has to come back as work to do."""
        source = _data(home, ".frago", "data", "etf", "board",
                       files=(("a.json", "{}"), ("b.json", "{}")))
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        one = data_migration.plan(WHO, home).moves[0]
        one.target.mkdir(parents=True)
        (one.target / "a.json").write_text("{}", encoding="utf-8")
        assert data_migration.plan(WHO, home).moves


class TestTheMachineDoesNotStopWhileItIsMigrated:
    """A scheduled task or a running server writes to a source minutes after it
    was copied. That is ordinary. Somebody writing to the *target* is not — and
    the two look identical unless something recorded what the copy weighed.
    """

    def _setup(self, home):
        source = _data(home, ".frago", "data", "etf", "board",
                       files=(("rows.json", '{"n": 1}'),))
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        one = data_migration.plan(WHO, home).moves[0]
        data_migration.apply(one, home)
        return one

    def test_a_source_that_kept_growing_is_refreshed(self, home):
        one = self._setup(home)
        (one.source / "rows.json").write_text('{"n": 22}', encoding="utf-8")
        entry = data_migration.apply(one, home)
        assert "刷新" in entry["note"]
        assert (one.target / "rows.json").read_text(encoding="utf-8") == '{"n": 22}'

    def test_work_written_under_the_new_path_is_never_overwritten(self, home):
        """There is real work there and this copy is not it. Stopping costs a
        person one question; copying over it costs them the work."""
        one = self._setup(home)
        (one.source / "rows.json").write_text('{"n": 22}', encoding="utf-8")
        (one.target / "somebody-worked-here.json").write_text("{}", encoding="utf-8")
        with pytest.raises(data_migration.MigrationFailed) as caught:
            data_migration.apply(one, home)
        assert "有人往新落点写过" in str(caught.value)
        assert (one.target / "somebody-worked-here.json").is_file()

    def test_a_refresh_is_written_down_like_any_other_move(self, home):
        one = self._setup(home)
        (one.source / "rows.json").write_text('{"n": 22}', encoding="utf-8")
        data_migration.apply(one, home)
        lines = data_migration.manifest_path(home).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[-1])["source_kept"] is True

    def test_the_original_survives_a_refresh(self, home):
        one = self._setup(home)
        (one.source / "rows.json").write_text('{"n": 22}', encoding="utf-8")
        data_migration.apply(one, home)
        assert (one.source / "rows.json").read_text(encoding="utf-8") == '{"n": 22}'


class TestAHandSuppliedPlanGetsTheSameRefusals:
    """Most recipes never recorded their directory anywhere a machine can read,
    so someone has to read the code and say where it is. That answer is *less*
    authoritative than a derived one, not more — it was typed by whoever read
    last, and the three failures the gates catch are exactly the ones a reader
    misses. So an explicit plan goes through every one of them.
    """

    def test_a_hand_supplied_directory_is_moved(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "feed")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home)
        assert len(result.moves) == 1
        assert result.moves[0].target == app_state.recipe_data_dir(WHO, RECIPE)

    def test_a_named_slot_still_becomes_a_project(self, home):
        source = _data(home, ".frago", "data", "x")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "slot": "run-a", "source": str(source)}], home)
        assert result.moves[0].target == app_state.recipe_data_dir(WHO, RECIPE, "run-a")

    def test_two_entries_claiming_one_directory_are_still_stopped(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "shared")
        result = data_migration.plan_from_entries(WHO, [
            {"recipe": "reader", "source": str(source)},
            {"recipe": "writer", "source": str(source)},
        ], home)
        assert not result.moves
        assert {b[0] for b in result.blocked} == {"reader", "writer"}

    def test_a_dated_deliverable_is_still_refused(self, home):
        source = _data(home, ".frago", "data", "one-off", "20260527-deep-dive")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home)
        assert not result.moves and "交付物" in result.blocked[0][2]

    def test_a_directory_inside_a_package_is_still_refused(self, home):
        source = _data(home, ".frago", "recipes", "workflows", RECIPE, "data")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home)
        assert not result.moves and "代码包" in result.blocked[0][2]

    def test_a_path_that_is_not_there_is_reported_not_created(self, home):
        gone = home / ".frago" / "data" / "typo"
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(gone)}], home)
        assert not result.moves and not gone.exists()

    def test_an_entry_missing_its_fields_is_reported_not_guessed(self, home):
        result = data_migration.plan_from_entries(WHO, [{"recipe": RECIPE}], home)
        assert not result.moves and result.skipped


class TestTheDeliverableGateMatchesTheActualShape:
    """`must-data-dir` puts a transaction at `data/<subject>/<date>-<slug>/` —
    the date sits at the second level and nowhere else.

    A first pass matched a dated component at any depth and swept up ten video
    projects filed as `data/agent-os/videos/<date>-<slug>/`. Those are one
    recipe's projects, which is exactly what this migration is for. A gate that
    blocks the case it exists to serve is worse than no gate: the person reading
    its refusal cannot tell it from a real one.
    """

    def _plan_for(self, home, *parts):
        source = _data(home, ".frago", "data", *parts)
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        return data_migration.plan(WHO, home)

    def test_a_transaction_directory_is_refused(self, home):
        result = self._plan_for(home, "one-off", "20260527-tau-deepdive")
        assert not result.moves and "交付物" in result.blocked[0][2]

    def test_something_inside_a_transaction_directory_is_refused(self, home):
        result = self._plan_for(home, "one-off", "20260728-migration", "annotate-demo")
        assert not result.moves and "交付物" in result.blocked[0][2]

    def test_a_project_named_after_a_date_deeper_down_is_moved(self, home):
        """Naming a project after a date does not make it somebody's report."""
        result = self._plan_for(home, "agent-os", "videos", "20260727-lenovo-demo")
        assert len(result.moves) == 1 and not result.blocked

    def test_a_subject_level_directory_with_no_date_is_moved(self, home):
        result = self._plan_for(home, "etf", "recipe-caches", "ledger")
        assert len(result.moves) == 1 and not result.blocked


class TestItRefusesToMoveAWholeTree:
    """A recipe that keeps one file directly under `~/.frago/data` reports its
    directory as `~/.frago/data`. Copying that files everything on the machine
    under one recipe's name — the largest possible version of this tool's own
    failure mode, and the one that looks like success until the disk fills.

    Found while planning 48 hand-located recipes: one of them really did report
    the data root.
    """

    @pytest.mark.parametrize("parts", [
        (),                 # ~/.frago
        ("data",),          # ~/.frago/data
        ("recipes",),
        ("users",),
        ("projects",),
    ])
    def test_a_root_is_refused_by_the_derived_plan(self, home, parts):
        root = home.joinpath(".frago", *parts)
        root.mkdir(parents=True, exist_ok=True)
        _slot(home, RECIPE, "default", {"dataDir": str(root)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert "一整棵树的根" in result.blocked[0][2]

    def test_a_root_is_refused_by_a_hand_supplied_plan_too(self, home):
        root = home / ".frago" / "data"
        root.mkdir(parents=True, exist_ok=True)
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(root)}], home)
        assert not result.moves and "一整棵树的根" in result.blocked[0][2]

    def test_a_real_directory_under_a_root_is_still_moved(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "ledger")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        assert len(data_migration.plan(WHO, home).moves) == 1


class TestItRefusesToClaimThePlatformsOwnTrees:
    """One recipe reads and writes `~/.frago/sessions` — 5 GB that frago's own
    session sync also owns. Filing that under the recipe's name would claim
    somebody else's records and duplicate every byte. The recipe writing there
    is worth fixing; copying it is not the fix.
    """

    @pytest.mark.parametrize("tree", ["sessions", "app-state", "executions", "traces"])
    def test_a_platform_tree_is_refused(self, home, tree):
        source = _data(home, ".frago", tree, "something")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        result = data_migration.plan(WHO, home)
        assert not result.moves
        assert "frago 自己维护的目录" in result.blocked[0][2]

    def test_a_hand_supplied_plan_is_refused_the_same_way(self, home):
        source = _data(home, ".frago", "sessions", "claude")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home)
        assert not result.moves and "frago 自己维护的目录" in result.blocked[0][2]

    def test_the_ordinary_data_tree_is_untouched_by_this(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "x")
        _slot(home, RECIPE, "default", {"dataDir": str(source)})
        assert len(data_migration.plan(WHO, home).moves) == 1


class TestTheDeliverableGateTakesAWrittenException:
    """Some ledgers really were filed as one-off deliverables, and the fix is to
    move them — the location was wrong, not the rule.

    The exception is written per entry with a reason, not switched on globally:
    a flag that waives a gate for a whole run gets set once and then set out of
    habit, and the reason nobody wrote down is the reason nobody can check.
    """

    def _entry(self, home, **extra):
        source = _data(home, ".frago", "data", "lenovo", "20260716-board")
        return [{"recipe": RECIPE, "source": str(source), **extra}]

    def test_without_the_exception_it_is_still_refused(self, home):
        result = data_migration.plan_from_entries(WHO, self._entry(home), home)
        assert not result.moves
        assert "deliverable_ok" in result.blocked[0][2]

    def test_with_the_exception_it_moves(self, home):
        result = data_migration.plan_from_entries(
            WHO, self._entry(home, deliverable_ok=True, why="内容是账本，当初归档位置就错了"), home)
        assert len(result.moves) == 1

    def test_the_reason_is_written_into_the_manifest(self, home):
        result = data_migration.plan_from_entries(
            WHO, self._entry(home, deliverable_ok=True, why="内容是账本"), home)
        entry = data_migration.apply(result.moves[0], home)
        assert entry["exception"] == "内容是账本"

    def test_the_exception_waives_only_this_gate(self, home):
        """It says "this is not a deliverable", not "skip the checks"."""
        source = _data(home, ".frago", "recipes", "workflows", RECIPE, "data")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source), "deliverable_ok": True}], home)
        assert not result.moves and "代码包" in result.blocked[0][2]

    def test_an_ordinary_move_records_no_exception(self, home):
        source = _data(home, ".frago", "data", "etf", "recipe-caches", "x")
        result = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home)
        assert data_migration.apply(result.moves[0], home)["exception"] == ""


class TestAnEmptyTargetIsNoTarget:
    """Running a recipe leaves an empty data directory, and that must not block
    its own migration.

    Every recipe creates its directory before writing, so the mere act of
    starting one — a status check, a dry run — leaves an empty directory at the
    new location. The guard that protects real work from being overwritten then
    fired on it, refusing with "somebody has written here, overwriting it
    destroys their work" while reporting in the same sentence that the place
    holds zero files and zero bytes. A refusal whose stated reason contradicts
    its own evidence is worse than no refusal: it teaches the reader to force
    past the guard, and the next one it raises will be the real one.
    """

    def _move(self, tmp_path, files=(("a.csv", "1"),)):
        from frago.recipes import data_migration

        source = tmp_path / "old"
        source.mkdir()
        for name, body in files:
            (source / name).write_text(body, encoding="utf-8")
        target = tmp_path / "new"
        return data_migration.Move("feed", "default", source, target)

    def test_an_empty_directory_does_not_stop_the_copy(self, tmp_path):
        from frago.recipes import data_migration

        one = self._move(tmp_path)
        one.target.mkdir(parents=True)
        entry = data_migration.apply(one, home=tmp_path)
        assert entry["files"] == 1
        assert (one.target / "a.csv").read_text(encoding="utf-8") == "1"

    def test_a_directory_holding_work_still_stops_it(self, tmp_path):
        """The guard's real job is untouched."""
        from frago.recipes import data_migration

        one = self._move(tmp_path)
        one.target.mkdir(parents=True)
        (one.target / "somebody-elses.json").write_text("{}", encoding="utf-8")
        with pytest.raises(data_migration.MigrationFailed):
            data_migration.apply(one, home=tmp_path)
        assert (one.target / "somebody-elses.json").exists()

    def test_the_original_is_never_touched_either_way(self, tmp_path):
        from frago.recipes import data_migration

        one = self._move(tmp_path)
        one.target.mkdir(parents=True)
        data_migration.apply(one, home=tmp_path)
        assert (one.source / "a.csv").read_text(encoding="utf-8") == "1"


class TestAShareDirectoryIsNotOneRecipesData:
    """``~/.frago/state`` holds several recipes' files and belongs to none.

    It was filed as one recipe's data directory and copied under that recipe's
    name, taking another recipe's cursor, a team watcher and a credentials file
    to a second location — the duplication this tool exists to end, carried out
    by the tool itself. The gate that refuses the platform's own trees already
    existed; this directory simply was not on its list, and a list is only as
    good as the day somebody last added to it.
    """

    @pytest.mark.parametrize("tree", [
        "state", "sessions", "app-state", "executions", "traces", "books", "bin", "viewer",
    ])
    def test_the_platforms_own_trees_are_refused(self, tmp_path, tree):
        from frago.recipes import data_migration

        source = tmp_path / ".frago" / tree / "something"
        source.mkdir(parents=True)
        assert data_migration._is_platform_owned(source, tmp_path)

    def test_a_recipes_own_subject_directory_is_not(self, tmp_path):
        source = tmp_path / ".frago" / "data" / "etf" / "recipe-caches" / "feed"
        source.mkdir(parents=True)
        from frago.recipes import data_migration

        assert not data_migration._is_platform_owned(source, tmp_path)

    def test_an_explicit_plan_is_refused_too(self, tmp_path, monkeypatch):
        """A hand-written plan feels more authoritative than a derived one and
        is in fact less: it was typed by whoever read the code last. This entry
        was hand-written, and it is how the directory got copied."""
        from frago.recipes import data_migration

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / ".frago" / "users"))
        source = tmp_path / ".frago" / "state"
        source.mkdir(parents=True)
        (source / "someone_elses.json").write_text("{}", encoding="utf-8")
        result = data_migration.plan_from_entries(
            "a" * 32, [{"recipe": "poller", "source": str(source)}], home=tmp_path
        )
        assert not result.moves
        assert any("frago 自己维护的目录" in why for _, _, why in result.blocked)


class TestTheCopiesNeedAnEnd:
    """Copying without deleting was right, and it leaves a state that must end.

    Two copies of one thing is the disease this whole layout treats. A migration
    that copies is the safe way to move — a wrong guess about somebody's own
    records has to be recoverable — but it produces the disease on purpose, and
    the cure is only complete when somebody can say the old one stopped being
    read. Until this existed the ledger could only record that a copy was *made*.
    It had no room to say the original was finished, so nobody ever said it, and
    the question "is this old directory still live" was answered three times by
    hand, by comparing timestamps.

    Three stages, and every copy is in exactly one: still being used, quiet
    enough to put a date on, or closed.
    """

    def _migrated(self, home, recipe=RECIPE, slot="default", parts=("etf", "board")):
        """A finished migration with nothing else wrong: no page still pointing
        at the old copy, nobody else reaching into it. Each test then breaks
        exactly one of those and checks that this is what gets noticed."""
        source = _data(home, ".frago", "data", *parts)
        one = data_migration.plan_from_entries(
            WHO, [{"recipe": recipe, "slot": slot, "source": str(source)}], home).moves[0]
        data_migration.apply(one, home)
        return one

    def _age(self, path, days):
        """Put a file's clock back, so a test does not depend on how long it ran."""
        stamp = (datetime.now() - timedelta(days=days)).timestamp()
        os.utime(path, (stamp, stamp))

    def test_a_copy_nobody_touches_any_more_is_ready_for_a_date(self, home):
        one = self._migrated(home)
        self._age(one.source / "rows.json", days=40)
        report = data_migration.audit(WHO, home)
        assert [x.recipe for x in report.ready] == [RECIPE]
        assert report.ready[0].quiet_enough
        assert report.needs_attention == 0

    def test_a_copy_still_being_written_to_is_not(self, home):
        """Something never switched over. Deleting the old one now loses
        whatever it has been writing there since."""
        one = self._migrated(home)
        self._age(one.source / "rows.json", days=-1)  # written a day from now
        report = data_migration.audit(WHO, home)
        assert [x.recipe for x in report.still_live] == [RECIPE]
        assert any("还在被写" in why for why in report.still_live[0].reasons)

    def test_a_page_still_addressing_the_old_directory_is_not(self, home):
        """The page reads one copy while the recipe fills the other, and every
        refresh reports success. That is the original failure, exactly."""
        one = self._migrated(home)
        self._age(one.source / "rows.json", days=40)
        _slot(home, RECIPE, "default", {"dataDir": str(one.source)})
        report = data_migration.audit(WHO, home)
        assert [x.recipe for x in report.still_live] == [RECIPE]
        assert any("页面的地址还记着" in why for why in report.still_live[0].reasons)

    def test_a_page_pointed_at_the_proper_place_is_clean(self, home):
        one = self._migrated(home)
        self._age(one.source / "rows.json", days=40)
        _slot(home, RECIPE, "default", {"dataDir": str(one.target)})
        assert data_migration.audit(WHO, home).needs_attention == 0

    def test_a_source_that_served_more_than_one_recipe_is_not(self, home):
        """`~/.frago/state` was filed as one poller's data directory and copied
        whole, carrying a team watcher and a credentials file under that
        poller's name. Nothing about the *name* said so — what said so was that
        another recipe recorded a directory inside it as its own."""
        one = self._migrated(home, parts=("shared-tree",))
        self._age(one.source / "rows.json", days=40)
        _data(home, ".frago", "data", "shared-tree", "upwork")
        _slot(home, "other_watcher", "default",
              {"dataDir": str(home / ".frago/data/shared-tree/upwork")})
        report = data_migration.audit(WHO, home)
        assert any(x.recipe == RECIPE for x in report.still_live)
        mine = next(x for x in report.still_live if x.recipe == RECIPE)
        assert any("不是只服务这一个配方" in why for why in mine.reasons)

    def test_the_judgement_is_who_else_is_in_there_not_a_list_of_names(self, home):
        """The blocklist is the gate's job, before the fact, and a list is only
        as good as the day somebody last added to it. After the fact the
        evidence is the contents: a directory with an innocent name that no
        other recipe reaches into is clean, whatever it is called."""
        one = self._migrated(home, parts=("state-like-name",))
        self._age(one.source / "rows.json", days=40)
        assert data_migration.audit(WHO, home).needs_attention == 0

    def test_a_sealed_copy_is_reported_as_closed(self, home):
        one = self._migrated(home)
        import shutil as _shutil
        _shutil.rmtree(one.source)
        data_migration.seal(one.recipe, one.slot, one.source, one.target,
                            how="archived", where="/tmp/trash/board", home=home)
        report = data_migration.audit(WHO, home)
        assert [x.recipe for x in report.sealed] == [RECIPE]
        assert not report.still_live and not report.ready

    def test_a_source_that_vanished_with_no_seal_line_says_so(self, home):
        """Gone is not the same as closed. Somebody removed it and wrote nothing
        down, so "where did it go, and can it come back" has no answer."""
        one = self._migrated(home)
        import shutil as _shutil
        _shutil.rmtree(one.source)
        report = data_migration.audit(WHO, home)
        assert [x.recipe for x in report.sealed] == [RECIPE]
        assert any("没有这一笔封存记录" in why for why in report.sealed[0].reasons)

    def test_every_copy_lands_in_exactly_one_stage(self, home):
        for name, parts in (("a_board", ("etf", "a")), ("b_board", ("etf", "b"))):
            one = self._migrated(home, recipe=name, parts=parts)
            self._age(one.source / "rows.json", days=40)
        report = data_migration.audit(WHO, home)
        assert len(report.still_live) + len(report.ready) + len(report.sealed) == 2
        assert len(report.checked) == 2


class TestCleanIsNotTheSameAsUnchecked:
    """A check whose "all clear" is indistinguishable from "never ran" is not a
    check. This one is scheduled and unattended, so that confusion would not be
    caught by anybody noticing — it would just quietly stop covering anything.
    """

    def test_no_ledger_at_all_is_said_out_loud(self, home):
        report = data_migration.audit(WHO, home)
        assert report.ledger_exists is False
        assert not report.checked

    def test_a_ledger_with_clean_entries_reports_what_it_checked(self, home):
        source = _data(home, ".frago", "data", "etf", "board")
        one = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home).moves[0]
        data_migration.apply(one, home)
        report = data_migration.audit(WHO, home)
        assert report.ledger_exists is True
        assert len(report.checked) == 1 and report.needs_attention == 0

    def test_the_two_do_not_produce_the_same_answer(self, home):
        """Same `needs_attention`, different `ledger_exists`. Anything reading
        only the first number would call an absent ledger a clean one."""
        empty = data_migration.audit(WHO, home)
        source = _data(home, ".frago", "data", "etf", "board")
        one = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home).moves[0]
        data_migration.apply(one, home)
        clean = data_migration.audit(WHO, home)
        assert empty.needs_attention == clean.needs_attention == 0
        assert empty.ledger_exists != clean.ledger_exists


class TestTheLedgerIsStillOnlyEverAppendedTo:
    """Somebody months from now asks this file whether an old directory was ever
    migrated and to where. A line rewritten today is that answer gone."""

    def _migrated(self, home):
        source = _data(home, ".frago", "data", "etf", "board")
        one = data_migration.plan_from_entries(
            WHO, [{"recipe": RECIPE, "source": str(source)}], home).moves[0]
        data_migration.apply(one, home)
        return one

    def test_the_audit_changes_nothing_on_disk(self, home):
        self._migrated(home)
        before = {p: p.stat().st_mtime for p in home.rglob("*") if p.is_file()}
        data_migration.audit(WHO, home)
        after = {p: p.stat().st_mtime for p in home.rglob("*") if p.is_file()}
        assert before == after

    def test_sealing_adds_a_line_and_leaves_the_copy_line_word_for_word(self, home):
        one = self._migrated(home)
        ledger = data_migration.manifest_path(home)
        first = ledger.read_text(encoding="utf-8")
        data_migration.seal(one.recipe, one.slot, one.source, one.target,
                            how="deleted", home=home)
        after = ledger.read_text(encoding="utf-8")
        assert after.startswith(first)
        assert len(after.splitlines()) == len(first.splitlines()) + 1

    def test_the_seal_line_records_where_it_went(self, home):
        """"It is gone" and "it is here, and here is where" are different
        answers, and only the second one can be undone."""
        one = self._migrated(home)
        entry = data_migration.seal(one.recipe, one.slot, one.source, one.target,
                                    how="archived", where="/tmp/trash/board", home=home)
        assert entry["lifecycle"] == "sealed"
        assert entry["where"] == "/tmp/trash/board"
        assert entry["source_kept"] is False

    def test_sealing_deletes_nothing_by_itself(self, home):
        """Recording a decision is not carrying it out."""
        one = self._migrated(home)
        data_migration.seal(one.recipe, one.slot, one.source, one.target,
                            how="deleted", home=home)
        assert one.source.is_dir()

    def test_a_line_written_before_the_lifecycle_existed_is_read_as_a_copy(self, home):
        """Fifty-odd lines predate the field. Reading them as anything but what
        they are would rewrite history by interpretation, which is the one thing
        an append-only file is supposed to make impossible."""
        source = _data(home, ".frago", "data", "old", "board")
        ledger = data_migration.manifest_path(home)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({
            "when": "2026-08-25T09:33:25+08:00",
            "recipe": RECIPE, "slot": "default",
            "source": str(source),
            "target": str(app_state.recipe_data_dir(WHO, RECIPE)),
            "files": 1, "bytes": 8, "source_kept": True, "note": "",
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        report = data_migration.audit(WHO, home)
        assert len(report.checked) == 1
        assert report.checked[0].source == source

    def test_a_damaged_line_does_not_take_the_rest_with_it(self, home):
        self._migrated(home)
        ledger = data_migration.manifest_path(home)
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n")
        assert len(data_migration.audit(WHO, home).checked) == 1


class TestWhatTheScheduledCopyPrints:
    """The daily run has to stay silent when there is nothing to say, and the
    silence has to be unmistakable.

    A check that reports "fine" every morning is a check nobody reads by the end
    of the week, so `--only-problems` says nothing when nothing is wrong. What
    it must never do is say nothing for the *other* reason — no ledger, nothing
    scanned — because then the day the ledger goes missing looks exactly like
    the day everything was fine.
    """

    def _run(self, monkeypatch, report, *args):
        from click.testing import CliRunner

        from frago.cli import recipe_commands

        monkeypatch.setattr("frago.recipes.context.default_identity", lambda: WHO)
        monkeypatch.setattr("frago.recipes.data_migration.audit",
                            lambda who, *a, **k: report)
        return CliRunner().invoke(recipe_commands.data_migrate, ["--audit", *args])

    def _report(self, tmp_path, **kw):
        ledger = tmp_path / "migration-manifest.jsonl"
        base = {"identity": WHO, "ledger": ledger, "ledger_exists": True, "lines": 1}
        return data_migration.Audit(**{**base, **kw})

    def _one(self, stage, reasons=()):
        return data_migration.Audited(
            RECIPE, "default", Path("/old/board"), Path("/new/board"),
            "2026-08-25T09:33:25+08:00", stage, tuple(reasons), quiet_days=40)

    def test_a_clean_run_says_nothing_at_all(self, tmp_path, monkeypatch):
        report = self._report(tmp_path,
                              checked=[self._one(data_migration.READY_TO_EXPIRE)])
        result = self._run(monkeypatch, report, "--only-problems")
        assert result.exit_code == 0
        assert result.output == ""

    def test_a_run_with_something_wrong_speaks_up(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, checked=[
            self._one(data_migration.STILL_LIVE, ["老地方还在被写"])])
        result = self._run(monkeypatch, report, "--only-problems")
        assert "还没切干净" in result.output
        assert RECIPE in result.output

    def test_a_missing_ledger_is_never_silent(self, tmp_path, monkeypatch):
        """The one case that must not pass for "all clear": nothing was
        scanned, and if that reads as clean the check has stopped existing."""
        report = self._report(tmp_path, ledger_exists=False, lines=0, checked=[])
        result = self._run(monkeypatch, report, "--only-problems")
        assert "账本不存在" in result.output
        assert "这不是「干净」" in result.output

    def test_a_run_by_hand_reports_the_clean_case_too(self, tmp_path, monkeypatch):
        """Without `--only-problems` a person asked, so they get an answer —
        including how many were looked at."""
        report = self._report(tmp_path,
                              checked=[self._one(data_migration.READY_TO_EXPIRE)])
        result = self._run(monkeypatch, report)
        assert "1 笔全扫过了，0 笔要人处理" in result.output

    def test_the_counts_are_numbers_and_names_not_adjectives(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, lines=3, checked=[
            self._one(data_migration.STILL_LIVE, ["老地方还在被写"]),
            self._one(data_migration.READY_TO_EXPIRE),
            self._one(data_migration.SEALED, ["源目录已经不在了"]),
        ])
        result = self._run(monkeypatch, report)
        assert "【还没切干净】1 笔" in result.output
        assert "【可以定到期日】1 笔" in result.output
        assert "【已封存】1 笔" in result.output
