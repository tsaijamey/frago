"""A page is only finished when someone who is not its author can open it.

The two recipes here were exposed to a real account on a real server, opened, and
showed nothing. Every part worked in isolation: the recipe ran, the page loaded,
the account was on the allow list. What failed was the join — the page asked for
its data through a channel that answers only the owner, and the machine it was
copied to had never been given the file anyway.

So these tests take the visitor's side. They do not ask "does the recipe run"; a
recipe that runs is what produced the empty page. They ask: **is everything this
page fetches actually reachable through the only channel a visitor has?**

They skip rather than fail when the recipes are not installed — these are one
person's recipes, not fixtures, and a machine without them has nothing to say
about them.
"""

import json
import re
from pathlib import Path

import pytest

from frago.recipes import checks

RECIPES_ROOT = Path.home() / ".frago" / "recipes" / "workflows"
STATE_ROOT = Path.home() / ".frago" / "app-state"

VIEWER = "astock_trade_history"
LEDGER = "astock_trade_ledger"

# What a page is allowed to fetch: its own directory, served by the platform at
# /app/<name>/data/. Anything else is either an asset it shipped with or a
# channel a visitor does not have.
_PAGE_FETCH = re.compile(r"""fetch\(\s*[`'"](data/[^`'"?]+)""")
_TEMPLATED_FETCH = re.compile(r"""fetch\(\s*fileUrl\(\s*[`'"]([^`'"]+)""")


def recipe_dir(name: str) -> Path:
    directory = RECIPES_ROOT / name
    if not directory.is_dir():
        pytest.skip(f"{name} is not installed on this machine")
    return directory


def published_state(name: str) -> dict:
    path = STATE_ROOT / name / "default.json"
    if not path.exists():
        pytest.skip(f"{name} has never published a page on this machine")
    return json.loads(path.read_text(encoding="utf-8"))


def test_viewer_page_has_nothing_a_visitor_cannot_reach():
    """The gate's verdict on the page a visitor is meant to open."""
    directory = recipe_dir(VIEWER)

    blocking = checks.blocking(checks.audit(directory))

    assert blocking == [], "\n".join(f.render(directory) for f in blocking)


def test_everything_the_viewer_fetches_is_actually_staged():
    """The join that failed in production: the page asks, the directory answers.

    Statically pairing what the page fetches with what the last run left behind
    catches the case the gate cannot see — a page that reads the right *kind* of
    path but a file nobody ever put there.
    """
    directory = recipe_dir(VIEWER)
    state = published_state(VIEWER)

    data_dir = Path(state.get("dataDir", ""))
    assert data_dir.is_dir(), f"published dataDir does not exist: {data_dir}"

    wanted = set()
    for asset in (directory / "assets").glob("*.js"):
        text = asset.read_text(encoding="utf-8", errors="ignore")
        wanted |= {m for m in _PAGE_FETCH.findall(text)}
        wanted |= {f"data/{m}" for m in _TEMPLATED_FETCH.findall(text)}

    assert wanted, "the page fetches nothing from its own directory — did it regress?"

    missing = [w for w in sorted(wanted) if not (data_dir / w[len("data/"):]).exists()]
    assert not missing, f"page fetches these but the run never staged them: {missing}"


def test_the_ledger_entry_page_is_refused_rather_than_quietly_broken():
    """The entry page cannot be served to visitors, and the gate says so.

    Its whole purpose is writing — back to the ledger file, and by triggering
    runs. Neither exists for a visitor. Exposing it read-only would put a page in
    front of someone whose every control is dead, so the honest outcome is a
    refusal at the door, and the narrow read-only recipe (the viewer above) is
    what gets exposed instead.
    """
    directory = recipe_dir(LEDGER)

    blocking = checks.blocking(checks.audit(directory))

    assert blocking, "expected the entry page to be refused; it now looks servable"
    assert all(f.rule == "page-asks-platform-for-files" for f in blocking)


def test_the_viewer_never_needs_an_absolute_path_from_its_state():
    """A visitor's config carries no filesystem path, so the page must not want one.

    This is the specific shape of the original failure: the page read
    `CFG.ledgerPath`, which the platform strips for visitors, so the fetch went
    out as the literal string "undefined".
    """
    directory = recipe_dir(VIEWER)
    app_js = (directory / "assets" / "app.js").read_text(encoding="utf-8", errors="ignore")

    live_lines = [
        line for line in app_js.splitlines()
        if "ledgerPath" in line and not line.strip().startswith(("*", "/*", "//"))
    ]

    assert live_lines == [], f"page still depends on a path from its state: {live_lines}"
