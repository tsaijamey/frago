"""Where a recipe's data belongs, decided by the platform rather than the recipe.

Every path in ``frago book must-recipe-data`` is derived here and nowhere else.
That is the point of the module: the four copies of one ledger that started this
work existed because each caller worked its own path out, and two callers who
each look correct in isolation are how a person ends up reading three-day-old
numbers off a page that reports every refresh as a success.
"""

import pytest

from frago.recipes import app_state

WHO = "a" * 32
OTHER = "b" * 32
RECIPE = "demo_board"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAGO_USER_STATE_DIR", str(tmp_path / "users"))
    monkeypatch.setattr(app_state, "USER_STATE_DIR", tmp_path / "users")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


class TestOneShapeForEverybody:
    def test_a_single_instance_recipe_gets_one_directory(self):
        assert app_state.recipe_data_dir(WHO, RECIPE).name == RECIPE

    def test_it_hangs_off_that_account_and_nobody_else(self, isolated):
        mine = app_state.recipe_data_dir(WHO, RECIPE)
        assert mine.is_relative_to(app_state.user_root(WHO))
        assert not mine.is_relative_to(app_state.user_root(OTHER))

    def test_two_accounts_never_share_a_directory(self):
        assert app_state.recipe_data_dir(WHO, RECIPE) != app_state.recipe_data_dir(OTHER, RECIPE)

    def test_a_multi_project_recipe_gets_one_directory_per_project(self):
        a = app_state.recipe_data_dir(WHO, RECIPE, "20260727-lenovo-demo")
        b = app_state.recipe_data_dir(WHO, RECIPE, "20260820-lose-30-percent")
        assert a != b
        assert a.parent == b.parent

    def test_projects_sit_under_a_named_level_of_their_own(self):
        """Not hung straight off the recipe directory: a project called `share`
        would otherwise collide with the recipe's cross-project files."""
        one = app_state.recipe_data_dir(WHO, RECIPE, "share")
        assert one.parent.name == app_state.PROJECTS_DIR
        assert one != app_state.share_root(RECIPE)


class TestTheNoteLivesInsideWhatItDescribes:
    def test_the_note_is_in_the_directory_it_is_about(self):
        for project in (None, "20260727-lenovo-demo"):
            note = app_state.recipe_state_path(WHO, RECIPE, project)
            assert note.parent == app_state.recipe_data_dir(WHO, RECIPE, project)

    def test_each_body_of_work_has_its_own_note(self):
        a = app_state.recipe_state_path(WHO, RECIPE, "one")
        b = app_state.recipe_state_path(WHO, RECIPE, "two")
        assert a != b

    def test_the_note_has_a_reserved_name(self):
        """A recipe writing this filename would clobber the platform's answer,
        so the name is spelled out once here for the check that refuses it."""
        assert app_state.recipe_state_path(WHO, RECIPE).name == app_state.STATE_FILE


class TestCrossUserDataIsNotInAnybodysTree:
    def test_shared_data_hangs_off_the_machine_not_a_person(self, isolated):
        for shared in (app_state.seed_dir(RECIPE), app_state.common_dir(RECIPE)):
            assert not shared.is_relative_to(app_state.user_root(WHO))

    def test_starting_data_and_read_together_data_are_different_places(self):
        """They behave in opposite ways — one is copied and then forgotten, the
        other must never be copied — so they must not share a directory."""
        assert app_state.seed_dir(RECIPE) != app_state.common_dir(RECIPE)

    def test_two_recipes_do_not_share_a_shared_area(self):
        assert app_state.share_root(RECIPE) != app_state.share_root("other_board")


class TestNothingEscapes:
    @pytest.mark.parametrize("bad", ["..", ".", "a/b", "", "x/../y"])
    def test_a_bad_recipe_name_is_refused(self, bad):
        with pytest.raises(app_state.InvalidSlotName):
            app_state.recipe_data_dir(WHO, bad)

    @pytest.mark.parametrize("bad", ["..", ".", "a/b", "", "x/../y"])
    def test_a_bad_project_name_is_refused(self, bad):
        with pytest.raises(app_state.InvalidSlotName):
            app_state.recipe_data_dir(WHO, RECIPE, bad)

    @pytest.mark.parametrize("bad", ["..", ".", "a/b", ""])
    def test_a_bad_account_id_is_refused(self, bad):
        with pytest.raises(app_state.InvalidSlotName):
            app_state.recipe_data_dir(bad, RECIPE)

    def test_a_project_cannot_climb_into_another_account(self):
        one = app_state.recipe_data_dir(WHO, RECIPE, "ok")
        assert one.resolve().is_relative_to(app_state.user_root(WHO).resolve())


class TestReadingSomebodyElsesDataIsItsOwnOffence:
    """Reading your own data is fine; reading another recipe's is not.

    They used to be reported as one thing, and they are not: a recipe naming a
    path inside its own subject tree has picked a bad location, while a recipe
    naming a path inside somebody else's has taken a dependency that the other
    side cannot see. The second one breaks when a person edits files they own,
    with no warning, in a place unrelated to what they changed.
    """

    @pytest.fixture
    def recipes_on_disk(self, tmp_path, monkeypatch):
        root = tmp_path / ".frago" / "recipes"
        for kind, name in (("workflows", "demo_board"), ("workflows", "cn_stock_data_feed")):
            d = root / kind / name
            d.mkdir(parents=True)
            (d / "recipe.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        return root / "workflows" / "demo_board"

    def _scan(self, src, me):
        import sys

        sys.path.insert(0, "src")
        from frago.cli.recipe_commands import _scan_data_location

        return _scan_data_location(src, me)

    def test_reading_another_recipes_cache_is_called_that(self, recipes_on_disk):
        src = ('HIST = Path.home() / ".frago" / "data" / "stock" / "recipe-caches"'
               ' / "cn_stock_data_feed" / "hist"')
        errors, _ = self._scan(src, recipes_on_disk)
        assert any("直接读了别的配方" in e for e in errors)

    def test_a_bad_location_of_ones_own_is_still_the_other_message(self, recipes_on_disk):
        src = 'D = Path.home() / ".frago" / "data" / "etf" / "recipe-caches" / "mine"'
        errors, _ = self._scan(src, recipes_on_disk)
        assert any("自己拼了数据路径" in e for e in errors)
        assert not any("直接读了别的配方" in e for e in errors)

    def test_a_recipe_naming_itself_is_not_naming_somebody_else(self, recipes_on_disk):
        """Its own name appearing in its own path is not a cross-recipe read."""
        src = 'D = Path.home() / ".frago" / "data" / "x" / "recipe-caches" / "demo_board"'
        errors, _ = self._scan(src, recipes_on_disk)
        assert not any("直接读了别的配方" in e for e in errors)

    def test_only_asking_the_platform_reports_nothing(self, recipes_on_disk):
        src = ('def data_dir():\n'
               '    d = os.environ.get("FRAGO_RECIPE_DATA_DIR")\n'
               '    if not d:\n        raise RuntimeError("x")\n    return d')
        errors, _ = self._scan(src, recipes_on_disk)
        assert not errors


class TestTheCheckDoesNotCondemnTheAnswerItAsksFor:
    """``users/<id>/recipe-data/`` is where the layout puts a recipe's data.

    The platform-tree rule refuses ``~/.frago/users/...`` because that tree is
    frago's own — and swept up the one thing inside it that is not. Two recipes
    documenting their real location, correctly, were reported as writing into
    somebody else's records. A check that condemns the thing it is asking for is
    worse than no check: the person reading it edits a document that was right
    into one that is wrong, and the check goes quiet, which reads as agreement.
    """

    @pytest.fixture
    def recipe_dir(self, tmp_path, monkeypatch):
        d = tmp_path / ".frago" / "recipes" / "workflows" / "demo_board"
        d.mkdir(parents=True)
        (d / "recipe.md").write_text("---\nname: x\n---\n", encoding="utf-8")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        return d

    def _scan(self, src, me):
        import sys

        sys.path.insert(0, "src")
        from frago.cli.recipe_commands import _scan_data_location

        return _scan_data_location(src, me)

    def _platform_complaints(self, src, me):
        errors, _ = self._scan(src, me)
        return [e for e in errors if "自己维护的目录" in e]

    @pytest.mark.parametrize("shape", [
        '"/Users/frago/.frago/users/74e083c8/recipe-data/demo_board/state.json"',
        '"~/.frago/users/<用户 id>/recipe-data/demo_board/projects/one/ledger.json"',
    ])
    def test_the_right_place_is_not_a_violation(self, shape, recipe_dir):
        assert not self._platform_complaints(f"D = {shape}", recipe_dir)

    @pytest.mark.parametrize("shape", [
        '"~/.frago/sessions/claude/abc123"',
        '"~/.frago/projects/<run>/outputs/test.mp4"',
        '"~/.frago/users/74e083c8/something-else/x.json"',
    ])
    def test_the_rest_of_the_platforms_trees_still_are(self, shape, recipe_dir):
        """Including ``users/`` used for anything other than recipe data — the
        exception is one directory, not the whole tree."""
        assert self._platform_complaints(f"D = {shape}", recipe_dir)


class TestTheGateOnlyCoversWhatTheContractCovers:
    """A chrome-js recipe has no base class to inherit from, so it is not asked to.

    The contract is Python: the base class is a Python module handed over on
    PYTHONPATH, and a recipe that executes inside a browser can no more inherit
    from it than it can import pandas. The gate that refuses unconverted
    recipes did not know that, and refused one — while telling its author to
    regenerate it from a template that produces Python, which would have
    destroyed the recipe.

    Three things disagreed at once: `frago recipe validate` said the file was
    fine, the runner refused to start it, and the refusal's suggested fix was
    wrong. A gate whose instructions break the thing it is guarding is worse
    than no gate, because a careful person follows them.
    """

    class _Meta:
        def __init__(self, runtime):
            self.runtime = runtime

    class _Recipe:
        def __init__(self, runtime, script):
            self.metadata = TestTheGateOnlyCoversWhatTheContractCovers._Meta(runtime)
            self.script_path = str(script)

    @pytest.fixture
    def unmarked(self, tmp_path):
        script = tmp_path / "recipe.js"
        script.write_text("// no contract header here\n", encoding="utf-8")
        return script

    @pytest.mark.parametrize("runtime", ["chrome-js", "shell", ""])
    def test_a_runtime_the_contract_does_not_cover_is_left_alone(self, runtime, unmarked):
        from frago.recipes.runner import _refuse_unconverted

        _refuse_unconverted("x", self._Recipe(runtime, unmarked))  # must not raise

    def test_python_is_still_refused(self, unmarked):
        from frago.recipes.runner import UnconvertedRecipe, _refuse_unconverted

        with pytest.raises(UnconvertedRecipe):
            _refuse_unconverted("x", self._Recipe("python", unmarked))

    def test_a_marked_python_recipe_starts(self, tmp_path):
        from frago.recipes.runner import _refuse_unconverted

        script = tmp_path / "recipe.py"
        script.write_text("#!/usr/bin/env python3\n# frago-recipe/1\n", encoding="utf-8")
        _refuse_unconverted("x", self._Recipe("python", script))  # must not raise


class TestAPageMayAskItsOwnBackEnd:
    """`POST /app/<recipe>/api/<mode>` is judged like `/run`, not refused.

    A recipe's page asks its own back end for data through this path. The
    security layer knew two things under `/app/`: GET is a page, and POST is
    allowed only for `/run`. So every signed-in visitor's fetch came back 401,
    the page showed «读取失败», and nothing on the page pointed at the layer
    where the refusal actually happened.

    Whether the caller may touch this page at all is one question with one
    answer, shared with `/run`. Which mode they may ask for is a different
    question, answered in the route by the exported surface — and exported
    means read-only.
    """

    @pytest.mark.parametrize("path,allowed", [
        ("/api/status", True),
        ("/api/read", True),
        ("/run", True),
        ("/api/../../etc/passwd", False),
        ("/api/a/b", False),
        ("/data/ledger.json", False),
        ("/api/", False),
    ])
    def test_only_a_mode_name_is_admitted(self, path, allowed):
        from frago.server.security import _APP_API_PATH

        assert bool(_APP_API_PATH.match(path)) == (allowed and path != "/run")

    def test_the_run_entrance_is_unchanged(self):
        """It was reachable before this and must stay reachable."""
        from frago.server.security import _APP_API_PATH

        assert not _APP_API_PATH.match("/run")  # handled by its own branch

    def test_a_mode_name_cannot_carry_a_path(self):
        """Anything with a separator or a dot is not a mode name. A mode is
        looked up as an attribute on the recipe class; a path there would be a
        way to address something that is not a mode at all."""
        from frago.server.security import _APP_API_PATH

        for bad in ("/api/../x", "/api/a/b", "/api/a.b", "/api/a%2Fb"):
            assert not _APP_API_PATH.match(bad), bad
