"""Opening a page wider has to be said. Nothing widens by omission.

`frago recipe expose` used to write the whole exposure record every time, so a
flag left off was a flag turned off. For most fields that was harmless. For the
allow list it was neither: the command that dropped it looked exactly like the
command that changed something else, and the page went from three named people
to everyone who can register an account. The guard was `--force`, which had to
be remembered in the one case nobody remembers — and on 2026-08-28 the accident
happened anyway in the other direction, a five-person list copied wholesale onto
a page that should have had one.

So the command is incremental now: it changes what it is told to change. These
tests pin both halves. Omitting a flag leaves that field alone, and every
widening — dropping the list, replacing it, going public — has its own spelling.
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
        "frago.cli.recipe_commands._exposure_notes", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "frago.cli.recipe_commands._resolve_allow",
        lambda named: ([ALICE if n.startswith("alice") else BOB for n in named], None),
    )
    return CliRunner()


def _named(page_runner, *args):
    return page_runner.invoke(expose_recipe, [NAME, *args])


class TestNothingWidensByOmission:
    def test_re_exposing_without_naming_anyone_keeps_the_list(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert _named(page, "--yes").exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_changing_the_slot_keeps_the_list(self, page):
        # The realistic accident under the old command: one field changed, one
        # restriction lost.
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE, BOB],
                    reads=pub.READS_RECIPE)
        assert _named(page, "--slot", "demo", "--yes").exit_code == 0
        entry = pub.published_entry(NAME)
        assert entry["slot"] == "demo"
        assert entry["allow"] == [ALICE, BOB]

    def test_a_slot_that_could_not_be_honoured_is_refused_not_stored(self, page):
        """Under `--each-their-own` the slot is the reader's own account id, so
        naming one here would be written down and enforce nothing."""
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--slot", "demo", "--yes")
        assert result.exit_code == 1
        assert "--shared" in result.output
        assert pub.published_entry(NAME)["slot"] == "default"

    def test_adding_one_account_keeps_the_others(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert _named(page, "--allow", "bob@example.com", "--yes").exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE, BOB]

    def test_a_signed_in_page_does_not_fall_back_to_public(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY)
        assert _named(page, "--yes").exit_code == 0
        assert pub.published_entry(NAME)["mode"] == pub.MODE_IDENTITY


class TestEveryWideningHasItsOwnSpelling:
    def test_dropping_the_whole_list_takes_signed_in(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert _named(page, "--signed-in", "--yes").exit_code == 0
        assert pub.published_entry(NAME)["allow"] is None

    def test_deny_removes_exactly_one(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE, BOB])
        assert _named(page, "--deny", "bob@example.com", "--yes").exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_only_replaces_the_list(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE, BOB])
        assert _named(page, "--only", "alice@example.com", "--yes").exit_code == 0
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_denying_the_last_account_is_refused(self, page):
        # "Exposed to nobody" is not a configuration; unexpose is.
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--deny", "alice@example.com", "--yes")
        assert result.exit_code == 1
        assert pub.published_entry(NAME)["allow"] == [ALICE]

    def test_going_public_drops_the_list_and_says_so(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        assert _named(page, "--public", "--yes").exit_code == 0
        entry = pub.published_entry(NAME)
        assert entry["mode"] == pub.MODE_PUBLIC
        assert entry["allow"] is None


class TestTheFirstExposureHasNoDefault:
    def test_a_bare_expose_of_a_new_page_is_refused(self, page):
        result = _named(page, "--yes")
        assert result.exit_code == 1
        assert "谁能看" in result.output
        assert pub.published_entry(NAME) is None

    def test_json_callers_get_a_code_they_can_branch_on(self, page):
        result = _named(page, "--yes", "--format", "json")
        assert json.loads(result.output)["code"] == "audience_required"

    @pytest.mark.parametrize("flag", ["--public", "--signed-in"])
    def test_naming_the_audience_is_enough(self, page, flag):
        assert _named(page, flag, "--yes").exit_code == 0


class TestTheRetiredFlagsExplainThemselves:
    def test_runnable_says_where_the_answer_moved(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY)
        result = _named(page, "--runnable", "--yes", "--format", "json")
        assert json.loads(result.output)["code"] == "runnable_retired"
        assert "page_actions" in result.output

    def test_force_says_why_it_is_gone(self, page):
        pub.publish(NAME, mode=pub.MODE_IDENTITY, allow=[ALICE])
        result = _named(page, "--force", "--yes", "--format", "json")
        assert json.loads(result.output)["code"] == "force_retired"
