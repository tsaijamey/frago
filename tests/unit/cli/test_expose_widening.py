"""Reopening a page to everyone must be said, not forgotten.

`frago recipe expose` writes the whole exposure record every time, so a flag
left off is a flag turned off. For most of them that is harmless and obvious.
For `--allow` it is neither: the command that drops an allow list looks exactly
like the command that changed something else — "I only wanted to add
--runnable" — and the page silently goes from three named people to everyone
who can register an account.

So that one transition is refused unless it is spelled out. The tests below fix
both halves of the contract: the refusal happens where it should, and it does
not fire anywhere else (a guard that cries wolf gets --force'd by habit, which
is the same hole with extra steps).
"""

import json

import pytest
from click.testing import CliRunner

from frago.cli.recipe_commands import expose_recipe
from frago.recipes import publish as pub

NAME = "trial_page"
ALICE = "a" * 32
BOB = "b" * 32


@pytest.fixture
def page(tmp_path, monkeypatch):
    """A recipe with a front end, plus an empty exposure registry."""
    monkeypatch.setattr(pub, "PUBLISHED_PATH", tmp_path / "published.json")
    monkeypatch.setattr(pub, "_cache", None, raising=False)

    recipe_dir = tmp_path / "recipes" / NAME
    (recipe_dir / "assets").mkdir(parents=True)
    (recipe_dir / "assets" / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    monkeypatch.setattr(
        "frago.cli.recipe_commands._find_recipe_dir_by_name",
        lambda n: recipe_dir if n == NAME else None,
    )
    # The audit reads slot state and the readiness check reads the recipe body;
    # neither is what these tests are about.
    monkeypatch.setattr(
        "frago.cli.recipe_commands._publish_audit", lambda *a, **k: ({}, [])
    )
    monkeypatch.setattr(
        "frago.cli.recipe_commands._runnable_readiness", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "frago.cli.recipe_commands._resolve_allow",
        lambda named: ([ALICE if "a" in n else BOB for n in named], None),
    )
    return CliRunner()


def _named(page_runner, *args):
    return page_runner.invoke(expose_recipe, [NAME, *args])


class TestTheWideningIsRefused:
    def test_dropping_the_allow_list_is_refused(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--require-identity", "--yes")
        assert result.exit_code == 1
        assert "would reopen it to everyone" in result.output

    def test_yes_does_not_grant_it(self, page):
        # --yes is the documented automation path. If it carried this decision,
        # every script that habitually passes it would widen pages by accident.
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE, BOB])
        assert _named(page, "--require-identity", "--yes").exit_code == 1
        assert pub.published_entry(NAME)["allow"] == [ALICE, BOB]

    def test_the_refusal_names_who_would_have_been_dropped(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert ALICE in _named(page, "--require-identity", "--yes").output

    def test_adding_runnable_alone_does_not_quietly_widen(self, page):
        # The realistic accident: the operator wanted one more capability and
        # got one fewer restriction.
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert _named(page, "--runnable", "--yes").exit_code == 1
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_json_callers_get_a_code_they_can_branch_on(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--require-identity", "--yes", "--format", "json")
        assert json.loads(result.output)["code"] == "would_widen"


class TestForceSaysItOutLoud:
    def test_force_opens_the_page_up(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--require-identity", "--force", "--yes")
        assert result.exit_code == 0
        assert pub.published_entry(NAME)["allow"] is None


class TestWhatMustNotTripTheGuard:
    def test_a_first_time_expose_is_untouched(self, page):
        # Nothing to widen: there is no list yet.
        assert _named(page, "--require-identity", "--yes").exit_code == 0

    def test_naming_the_accounts_again_is_untouched(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--allow", "alice@example.com", "--runnable", "--yes")
        assert result.exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_narrowing_the_list_is_untouched(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE, BOB])
        result = _named(page, "--allow", "alice@example.com", "--yes")
        assert result.exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_a_page_that_was_already_open_to_everyone_is_untouched(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY)
        assert _named(page, "--require-identity", "--runnable", "--yes").exit_code == 0

    def test_a_public_page_is_untouched(self, page):
        pub.publish(NAME, mode=pub.MODE_PUBLIC)
        assert _named(page, "--yes").exit_code == 0
