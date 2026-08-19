"""The gate at the door: what a recipe must not have done before its page opens.

Each test here is a shape that has actually shipped. The page-fetch one is the
reason this exists — two ledger pages were exposed to a real account, opened, and
showed nothing, because the data they wanted came through an endpoint no visitor
can use. Nothing in the publish path had anything to say about it.
"""

from pathlib import Path

import pytest

from frago.recipes import checks


def make_recipe(tmp_path: Path, *, code: str = "", page: str = "") -> Path:
    recipe = tmp_path / "some_recipe"
    (recipe / "assets").mkdir(parents=True)
    (recipe / "recipe.py").write_text(code or "print('ok')\n", encoding="utf-8")
    if page:
        (recipe / "assets" / "app.js").write_text(page, encoding="utf-8")
    return recipe


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


def test_page_reading_through_the_owner_only_endpoint_is_blocked(tmp_path):
    recipe = make_recipe(tmp_path, page='const r = await fetch(`${CFG.apiBase}/file?path=${p}`);\n')

    found = checks.audit(recipe)

    assert "page-asks-platform-for-files" in rules(checks.blocking(found))


def test_the_concatenated_spelling_is_caught_too(tmp_path):
    """The first grep written for this missed exactly this shape."""
    recipe = make_recipe(tmp_path, page='fetch(CONFIG.apiBase + "/file?path=" + encodeURIComponent(p))\n')

    assert "page-asks-platform-for-files" in rules(checks.blocking(checks.audit(recipe)))


def test_a_page_reading_its_own_directory_is_fine(tmp_path):
    """The blessed shape must not be flagged, or nobody will adopt it."""
    recipe = make_recipe(tmp_path, page="const r = await fetch('data/ledger.json', {cache:'no-store'});\n")

    assert checks.audit(recipe) == []


def test_a_path_from_the_authors_disk_is_blocked(tmp_path):
    recipe = make_recipe(tmp_path, code='LEDGER = "/Users/frago/.frago/data/ledger.json"\n')

    assert "absolute-path-literal" in rules(checks.blocking(checks.audit(recipe)))


def test_home_derived_writes_are_a_warning_not_a_wall(tmp_path):
    """Owner-side recipes legitimately keep data in the owner's tree."""
    recipe = make_recipe(tmp_path, code='from pathlib import Path\n(Path.home() / "out.json").write_text("{}")\n')

    found = checks.audit(recipe)

    assert "home-derived-write" in rules(found)
    assert checks.blocking(found) == []


def test_a_bare_filename_is_the_encouraged_shape_and_stays_clean(tmp_path):
    """`open("ledger.json","w")` is now correct everywhere. Flagging it would
    punish the exact behaviour this work is trying to produce."""
    recipe = make_recipe(tmp_path, code='open("ledger.json", "w").write("{}")\n')

    assert checks.audit(recipe) == []


def test_reaching_into_a_subdirectory_is_warned(tmp_path):
    recipe = make_recipe(tmp_path, code='open("assets/index.html").read()\n')

    found = checks.audit(recipe)

    assert "relative-path-not-anchored" in rules(found)
    assert checks.blocking(found) == []


def test_anchoring_to_the_recipes_own_location_clears_it(tmp_path):
    recipe = make_recipe(
        tmp_path,
        code='from pathlib import Path\n(Path(__file__).parent / "assets/index.html").read_text()\n',
    )

    assert "relative-path-not-anchored" not in rules(checks.audit(recipe))


def test_a_comment_does_not_satisfy_or_trigger_anything(tmp_path):
    """Positive checks degrade into comment-matching. This one must not."""
    recipe = make_recipe(tmp_path, code='# see /Users/frago/notes.md for why\nprint("ok")\n')

    assert checks.audit(recipe) == []


def test_a_jsdoc_block_describing_the_old_endpoint_is_not_a_finding(tmp_path):
    """Found by running these checks over a real recipe: the page had been fixed
    and the surviving report was its own comment explaining what it moved away
    from. A rule that flags prose gets ignored, and then it protects nothing."""
    recipe = make_recipe(
        tmp_path,
        page="/** /api/file 可能直接回内容，也可能包一层 */\nconst r = await fetch('data/x.json');\n",
    )

    assert checks.audit(recipe) == []


def test_runnable_gate_only_applies_when_runnable_is_asked_for(tmp_path):
    recipe = make_recipe(tmp_path, code='print("ok")\n')

    assert checks.audit(recipe) == []
    assert "runnable-ignores-data-dir" in rules(checks.audit(recipe, runnable=True))


def test_runnable_gate_is_satisfied_by_reading_the_variable(tmp_path):
    recipe = make_recipe(
        tmp_path,
        code='import os\nd = os.environ.get("FRAGO_RECIPE_DATA_DIR") or "/tmp/x"\n',
    )

    assert "runnable-ignores-data-dir" not in rules(checks.audit(recipe, runnable=True))


def test_findings_render_with_file_line_and_a_fix(tmp_path):
    """A refusal that does not say how to fix it gets worked around, not fixed."""
    recipe = make_recipe(tmp_path, page='fetch(`${CFG.apiBase}/file?path=x`)\n')

    text = checks.audit(recipe)[0].render(recipe)

    assert "assets/app.js:1" in text
    assert "data/" in text
