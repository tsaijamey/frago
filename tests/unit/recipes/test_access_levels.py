"""How far out a mode reaches, and where that answer is written.

It used to be written in three places — ``exports`` and ``page_actions`` in
``recipe.md``, ``modes`` in the class — that had to agree with each other and
with the methods, kept in step by hand. Two of the ways they could disagree
raised nothing at all on the machine the recipe was written on and surfaced as
a 403 in front of a stranger, days later, on a server.

So the mark moved onto the method. These tests hold the two halves of that to
each other: the class works its own surface out at import, the platform reads
the same answer out of the source without importing, and neither half is
allowed to be quietly wrong.
"""

import sys
from pathlib import Path

import pytest

from frago.recipes.contract import read_source

RUNTIME = Path(__file__).resolve().parents[3] / "src" / "frago" / "recipes" / "runtime"
sys.path.insert(0, str(RUNTIME))

from frago_recipe import ContractBroken, Recipe, action, export  # noqa: E402

SOURCE = '''
# frago-recipe/1
from frago_recipe import Recipe, export, action


class Ledger(Recipe):
    name = "ledger"
    default_mode = "view"

    @export
    def mode_data(self):
        return {}

    @action
    def mode_save(self):
        return {}

    def mode_backfill(self):
        return {}

    def mode_view(self):
        return {}


Ledger.main()
'''


class Ledger(Recipe):
    name = "ledger"
    default_mode = "view"

    @export
    def mode_data(self):
        return {}

    @action
    def mode_save(self):
        return {}

    def mode_backfill(self):
        return {}

    def mode_view(self):
        return {}


class TestTheTwoHalvesAgree:
    """The class and the parser must reach the same answer or the whole scheme
    is worse than the lists it replaced: the recipe would behave one way and be
    authorised another, which is precisely the silent divergence being removed.
    """

    @pytest.mark.parametrize("field", ["modes", "exports", "page_actions"])
    def test_the_class_and_the_source_say_the_same_thing(self, field):
        surface = read_source(SOURCE)
        parsed = {"modes": surface.modes, "exports": surface.exports,
                  "page_actions": surface.actions}[field]
        assert getattr(Ledger, field) == parsed

    def test_and_the_same_default(self):
        assert read_source(SOURCE).default == Ledger.default_mode


class TestWhatEachMarkMeans:
    def test_an_unmarked_mode_reaches_nobody(self):
        """The default, and the default is right: whoever can open a page can
        press it, and pressing it runs on the owner's machine."""
        assert "backfill" not in Ledger.exports
        assert "backfill" not in Ledger.page_actions
        assert "backfill" in Ledger.modes

    def test_export_is_for_other_modules_and_the_page_s_reads(self):
        assert Ledger.exports == ("data",)

    def test_action_is_for_the_page_s_buttons_and_not_the_bus(self):
        """The two do not nest. A page may press `save`; another module asking
        the bus for it is refused, because the bus additionally promises
        read-only and this door does not."""
        assert Ledger.page_actions == ("save",)
        assert "save" not in Ledger.exports


class TestTheOrderIsTheMethodsOrder:
    def test_modes_follow_the_source(self):
        assert Ledger.modes == ("data", "save", "backfill", "view")

    def test_the_default_is_a_decision_not_a_position(self):
        """`view` is the last method and still the default. Deriving the
        default from position would make reordering two methods silently change
        what a bare run does — eleven installed recipes had a default that was
        not their first method when this was introduced."""
        assert Ledger({}).resolve_mode() == "view"

    def test_without_one_the_first_method_answers(self):
        class Plain(Recipe):
            name = "plain"

            def mode_first(self):
                return {}

            def mode_second(self):
                return {}

        assert Plain({}).resolve_mode() == "first"


class TestTheOldSpellingsAreRefusedRatherThanIgnored:
    """Silently computing a different answer than the file states is the exact
    failure this change removes, so a leftover list is an error at import."""

    @pytest.mark.parametrize("field", ["modes", "exports", "page_actions"])
    def test_a_hand_written_list_stops_the_class(self, field):
        body = {"name": "stale", field: ("status",),
                "mode_status": lambda self: {}}
        with pytest.raises(ContractBroken) as raised:
            type("Stale", (Recipe,), body)
        assert "@export" in str(raised.value)

    def test_the_parser_reports_it_too(self):
        """Reported rather than raised on this side: `validate` is where an
        author is looking, and it should list every problem at once instead of
        stopping at the first."""
        stale = SOURCE.replace('    default_mode = "view"',
                               '    exports = ("data",)')
        problems = read_source(stale).problems
        assert any("exports" in p for p in problems)

    def test_a_retired_frontmatter_key_is_an_error(self, tmp_path):
        """A file still saying `exports: [status]` reads, to anyone opening it,
        as a recipe that exports status — and it no longer does."""
        from frago.recipes.exceptions import RecipeValidationError
        from frago.recipes.metadata import parse_metadata_file, validate_metadata

        md = tmp_path / "recipe.md"
        md.write_text(
            "---\nname: r\ntype: atomic\nruntime: python\nversion: '1.0'\n"
            "description: d\nuse_cases: [x]\noutput_targets: [stdout]\n"
            "exports: [status]\npage_actions: [save]\n---\n",
            encoding="utf-8")

        with pytest.raises(RecipeValidationError) as raised:
            validate_metadata(parse_metadata_file(md))
        joined = " ".join(raised.value.errors)
        assert "exports" in joined and "@export" in joined
        assert "page_actions" in joined and "@action" in joined


class TestAMisplacedMarkIsNotSilent:
    def test_a_level_on_something_that_is_not_a_mode_is_reported(self):
        """It would do nothing at all, which is the worst outcome: the file says
        the method is open and no part of the platform agrees."""
        problems = read_source(
            "from frago_recipe import Recipe, export\n\n"
            "class R(Recipe):\n"
            "    name = 'r'\n\n"
            "    @export\n"
            "    def helper(self):\n        return {}\n\n"
            "    def mode_status(self):\n        return {}\n"
        ).problems
        assert any("helper" in p for p in problems)

    def test_two_levels_on_one_mode_are_reported(self):
        problems = read_source(
            "from frago_recipe import Recipe, export, action\n\n"
            "class R(Recipe):\n"
            "    name = 'r'\n\n"
            "    @export\n    @action\n"
            "    def mode_status(self):\n        return {}\n"
        ).problems
        assert any("mode_status" in p for p in problems)

    def test_a_default_naming_no_method_is_refused_on_both_sides(self):
        with pytest.raises(ContractBroken):
            type("Bad", (Recipe,), {"name": "bad", "default_mode": "nope",
                                    "mode_status": lambda self: {}})

        problems = read_source(
            "from frago_recipe import Recipe\n\n"
            "class R(Recipe):\n"
            "    name = 'r'\n"
            "    default_mode = 'nope'\n\n"
            "    def mode_status(self):\n        return {}\n"
        ).problems
        assert any("default_mode" in p for p in problems)


class TestNothingToReadIsNotTheSameAsNothingOpened:
    """The distinction the bus turns on: a file that is not a module has not
    agreed to anything and is told so, while a module that marked nothing has
    answered — with "only the owner"."""

    def test_a_file_with_no_module_answers_none(self):
        assert read_source("x = 1\n") is None

    def test_an_unparseable_file_answers_none(self):
        assert read_source("def (\n") is None

    def test_a_module_that_marked_nothing_answers_empty(self):
        surface = read_source(
            "from frago_recipe import Recipe\n\n"
            "class R(Recipe):\n"
            "    name = 'r'\n\n"
            "    def mode_status(self):\n        return {}\n"
        )
        assert surface is not None
        assert surface.modes == ("status",)
        assert surface.exports == () and surface.actions == ()
