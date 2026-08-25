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
