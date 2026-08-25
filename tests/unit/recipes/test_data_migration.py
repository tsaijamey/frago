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
