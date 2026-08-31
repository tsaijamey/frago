"""The gate at the door: what a recipe must not have done before its page opens.

Each test here is a shape that has actually shipped. The page-fetch one is the
reason this exists — two ledger pages were exposed to a real account, opened, and
showed nothing, because the data they wanted came through an endpoint no visitor
can use. Nothing in the publish path had anything to say about it.
"""

from pathlib import Path

from frago.recipes import checks


def make_recipe(tmp_path: Path, *, code: str = "", page: str = "",
                page_actions: list[str] | None = None) -> Path:
    """A recipe on disk, optionally opening some of its modes to its page.

    ``page_actions`` becomes real ``@action`` marks in ``recipe.py`` rather
    than a list in the frontmatter, because that is where the answer lives now
    — and a fixture that put it anywhere else would be testing a shape no
    recipe has.
    """
    recipe = tmp_path / "some_recipe"
    (recipe / "assets").mkdir(parents=True)
    opened = "".join(
        f"\n    @action\n    def mode_{one}(self):\n        return {{}}\n"
        for one in (page_actions or [])
    )
    module = (
        "# frago-recipe/1\n"
        "from frago_recipe import Recipe, action\n\n\n"
        'class SomeRecipe(Recipe):\n    name = "some_recipe"\n'
        f"{opened}\n    def mode_status(self):\n        return {{}}\n\n\n"
        "SomeRecipe.main()\n"
    ) if page_actions else ""
    (recipe / "recipe.py").write_text(
        module + (code or "print('ok')\n"), encoding="utf-8")
    if page:
        (recipe / "assets" / "app.js").write_text(page, encoding="utf-8")
    (recipe / "recipe.md").write_text(
        "---\n"
        "name: some_recipe\ntype: atomic\nruntime: python\nversion: '1.0'\n"
        "description: a recipe\nuse_cases: [testing]\noutput_targets: [stdout]\n"
        "---\n# some_recipe\n",
        encoding="utf-8",
    )
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


def test_a_version_number_is_not_a_file_path(tmp_path):
    """Caught in the wild: a User-Agent header reported as a missing file.

    `Mozilla/5.0` has a slash and a dot, which was enough for the first version
    of this rule. A warning that fires on a browser string is a warning people
    learn to scroll past."""
    recipe = make_recipe(tmp_path, code='HEADERS = {"User-Agent": "Mozilla/5.0"}\n')

    assert checks.audit(recipe) == []


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


HOME_WRITE = 'from pathlib import Path\nPath.home().joinpath("x.json").write_text("{}")\n'


def test_a_fixed_landing_spot_is_a_warning_until_a_page_can_press_it(tmp_path):
    """The severity tracks who can trigger the write, not what the line says.

    A recipe only its owner runs is entitled to keep long-lived data in the
    owner's tree — blocking that would train people to skip this module. The
    same line under `@action` means every reader's press lands in one person's
    directory, and that is the failure the retired `actions-ignore-data-dir`
    rule existed to catch.
    """
    quiet = make_recipe(tmp_path / "quiet", code=HOME_WRITE)
    assert [f.severity for f in checks.audit(quiet)
            if f.rule == "home-derived-write"] == ["warn"]
    assert checks.blocking(checks.audit(quiet)) == []

    loud = make_recipe(tmp_path / "loud", code=HOME_WRITE, page_actions=["save"])
    assert "home-derived-write" in rules(checks.blocking(checks.audit(loud)))


def test_a_recipe_on_the_base_class_may_open_a_mode_without_naming_the_variable(tmp_path):
    """`Recipe.data_dir` *is* that read, and it raises when the platform did not
    set one — so requiring the name in the source would refuse exactly the
    recipes the conversion produced. Six of them failed this way, on the server
    only, with a message telling the author to restore a line whose absence was
    the point."""
    recipe = make_recipe(tmp_path, code="", page_actions=["save"])

    assert checks.honours_the_landing_spot(recipe)
    assert checks.blocking(checks.audit(recipe)) == []


def test_findings_render_with_file_line_and_a_fix(tmp_path):
    """A refusal that does not say how to fix it gets worked around, not fixed."""
    recipe = make_recipe(tmp_path, page='fetch(`${CFG.apiBase}/file?path=x`)\n')

    text = checks.audit(recipe)[0].render(recipe)

    assert "assets/app.js:1" in text
    assert "data/" in text
