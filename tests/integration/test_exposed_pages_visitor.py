"""A page is only finished when someone who is not its author can open it.

Two real recipes were exposed to a real account on a real server, opened, and
showed nothing. Every part worked in isolation: the recipe ran, the page loaded,
the account was on the allow list. What failed was the join — the page asked for
its data through a channel that answers only the owner, and the machine it was
copied to had never been given the file anyway.

So these tests take the reader's side. They do not ask "does the recipe run"; a
recipe that runs is what produced the empty page. They ask: **is everything this
page fetches actually reachable through the only channel a reader has?**

**Built here rather than read off this machine.** The first version of this file
pointed at two of one person's own recipes under ``~/.frago/recipes`` and skipped
when they were absent. That made the verdict depend on which recipes the
developer happened to have installed and what state they were last left in: the
same commit was green on one machine and red on another, and the red was about a
recipe nobody had touched. A test whose answer changes with the machine cannot
be used to decide whether a change is good. The shapes below are the ones that
actually shipped, reproduced as fixtures.
"""

import json
from pathlib import Path

import pytest

from frago.recipes import checks

# What a page is allowed to fetch: its own directory, served by the platform at
# /app/<name>/data/. Anything else is either an asset it shipped with or a
# channel a reader does not have.
_PAGE_FETCH = "data/"


def build(root: Path, name: str, *, page: str, recipe: str = "",
          page_actions: list[str] | None = None) -> Path:
    """One recipe on disk: a front end, a body, and its declared contract.

    ``page_actions`` becomes ``@action`` marks in ``recipe.py``. That is the
    whole declaration now — there is no list in the frontmatter to disagree
    with the methods, which is what the two used to do quietly.
    """
    directory = root / name
    (directory / "assets").mkdir(parents=True)
    (directory / "assets" / "app.js").write_text(page, encoding="utf-8")
    opened = "".join(
        f"\n    @action\n    def mode_{one}(self):\n        return {{}}\n"
        for one in (page_actions or [])
    )
    header = (
        "# frago-recipe/1\n"
        "from frago_recipe import Recipe, action\n\n\n"
        f'class Page(Recipe):\n    name = "{name}"\n{opened}\n\n'
    ) if page_actions else ""
    (directory / "recipe.py").write_text(
        header + (recipe or 'import os\nD = os.environ.get("FRAGO_RECIPE_DATA_DIR") or "."\n'),
        encoding="utf-8")
    (directory / "recipe.md").write_text(
        "---\n"
        f"name: {name}\ntype: atomic\nruntime: python\nversion: '1.0'\n"
        f"description: {name}\nuse_cases: [reading]\noutput_targets: [stdout]\n"
        "---\n",
        encoding="utf-8")
    return directory


@pytest.fixture
def viewer(tmp_path):
    """The page that showed nothing: reads its own directory, displays state."""
    return build(
        tmp_path, "trade_history",
        page=(
            "const CFG = await (await fetch('config.json')).json();\n"
            "const rows = await (await fetch('data/ledger.json')).json();\n"
            "render(CFG.tradeCount, rows);\n"
        ),
        recipe=(
            'import os, json\n'
            'D = os.environ.get("FRAGO_RECIPE_DATA_DIR") or "."\n'
            'print(json.dumps({"public": {"tradeCount": 46}}))\n'
        ),
    )


@pytest.fixture
def entry_page(tmp_path):
    """The page that writes: saving is a run, not a file write."""
    return build(
        tmp_path, "trade_ledger",
        page=(
            "await fetch('run', {method: 'POST', body: JSON.stringify("
            "{params: {mode: 'save', rows}})});\n"
        ),
        page_actions=["save"],
    )


class TestNothingThePageWantsIsOutOfReach:
    def test_the_viewer_passes_the_gate(self, viewer):
        blocking = checks.blocking(checks.audit(viewer))
        assert blocking == [], "\n".join(f.render(viewer) for f in blocking)

    def test_reading_through_the_owner_only_endpoint_is_caught(self, tmp_path):
        """The original failure, kept as a fixture because it is the shape the
        whole module exists for: it works perfectly for the author, who holds a
        token, and returns nothing for everyone else."""
        broken = build(
            tmp_path, "broken_viewer",
            page="const r = await fetch(`${CFG.apiBase}/file?path=${CFG.ledgerPath}`);\n")
        rules = {f.rule for f in checks.blocking(checks.audit(broken))}
        assert "page-asks-platform-for-files" in rules

    def test_a_page_depending_on_a_path_from_its_state_is_visible_in_the_source(self, viewer, tmp_path):
        """A reader's config carries no filesystem path — the platform strips it —
        so a page that wants one fetches the literal string "undefined"."""
        broken = build(
            tmp_path, "path_viewer",
            page="const rows = await (await fetch(CFG.ledgerPath)).json();\n")
        source = (broken / "assets" / "app.js").read_text(encoding="utf-8")
        live = [line for line in source.splitlines()
                if "ledgerPath" in line and not line.strip().startswith(("*", "//"))]
        assert live, "fixture no longer demonstrates the shape it was built for"

        clean = (viewer / "assets" / "app.js").read_text(encoding="utf-8")
        assert "ledgerPath" not in clean


class TestEverythingItFetchesIsActuallyStaged:
    """The join that failed in production: the page asks, the directory answers.

    Pairing what the page fetches with what a run leaves behind catches the case
    the gate cannot see — a page that reads the right *kind* of path but a file
    nobody ever put there.
    """

    def _wanted(self, recipe_dir: Path) -> set[str]:
        wanted = set()
        for asset in (recipe_dir / "assets").glob("*.js"):
            text = asset.read_text(encoding="utf-8")
            for piece in text.split("fetch('")[1:]:
                path = piece.split("'")[0]
                if path.startswith(_PAGE_FETCH):
                    wanted.add(path)
        return wanted

    def test_a_run_that_staged_everything_passes(self, viewer, tmp_path):
        data_dir = tmp_path / "run-output"
        data_dir.mkdir()
        (data_dir / "ledger.json").write_text("[]", encoding="utf-8")

        wanted = self._wanted(viewer)
        assert wanted == {"data/ledger.json"}
        missing = [w for w in wanted if not (data_dir / w[len(_PAGE_FETCH):]).exists()]
        assert missing == []

    def test_a_run_that_staged_nothing_is_caught(self, viewer, tmp_path):
        data_dir = tmp_path / "empty-output"
        data_dir.mkdir()

        wanted = self._wanted(viewer)
        missing = [w for w in wanted if not (data_dir / w[len(_PAGE_FETCH):]).exists()]
        assert missing == ["data/ledger.json"], (
            "a page fetching a file the run never wrote must be visible here"
        )


class TestWritingIsARunAndTheRecipeSaysWhich:
    """A signed-in reader is not a weaker owner: the interface that reads and
    writes any path answers them with 401 exactly as it answers a stranger. The
    one write they have is triggering a mode the recipe opened to its page.
    """

    def test_the_entry_page_saves_through_a_run(self, entry_page):
        app_js = (entry_page / "assets" / "app.js").read_text(encoding="utf-8")
        assert "mode: 'save'" in app_js

    def test_the_mode_it_presses_is_one_the_recipe_declared(self, entry_page):
        declared = checks.page_actions(entry_page)
        assert "save" in declared, (
            "the page presses a button the recipe never opened; the run route "
            "answers that with a 403 naming what was on offer"
        )

    def test_an_action_writing_to_a_fixed_place_is_blocked(self, tmp_path):
        """Otherwise every reader's save lands in the owner's one pile.

        A bare `open("ledger.json", "w")` is *not* this failure and must not be
        flagged as one: the runner starts the process inside the run's own
        directory, so that lands where it should. What cannot be right is a
        place that has nothing to do with who is running.
        """
        fine = build(
            tmp_path / "fine", "careful_ledger",
            page="fetch('run', {method:'POST'});\n",
            recipe='open("ledger.json", "w").write("{}")\n',
            page_actions=["save"])
        assert checks.blocking(checks.audit(fine)) == []

        careless = build(
            tmp_path / "careless", "careless_ledger",
            page="fetch('run', {method:'POST'});\n",
            recipe='from pathlib import Path\n'
                   'Path.home().joinpath("ledger.json").write_text("{}")\n',
            page_actions=["save"])
        rules = {f.rule for f in checks.blocking(checks.audit(careless))}
        assert "home-derived-write" in rules


def test_what_a_page_displays_has_to_be_declared_public(viewer):
    """The second half of "where does the data come from", and the half missed
    the first time: the ledger arrived through the page's own directory so the
    trade list filled in, while the positions stayed empty because they come
    from published state — and state outside `public` never leaves the machine.
    Half a page works, which reads as a rendering bug rather than a missing field.
    """
    source = (viewer / "recipe.py").read_text(encoding="utf-8")
    assert '"public"' in source

    published = json.loads(source.split("json.dumps(")[1].split(")")[0].replace("'", '"'))
    assert "tradeCount" in published["public"]
