"""What a recipe must not have done, if its page is going to be opened by someone else.

A recipe written on one machine is written under an assumption nobody states: that
the machine it runs on is the machine it was written on. Its files are where the
author left them, its page can ask the platform for any path it likes, and both
are true right up until the recipe is copied to a server. Then the page opens for
a visitor and there is nothing behind it — no error at publish time, no error at
copy time, just an empty screen for whoever was given the link.

So the checks here are **negative**: they do not ask whether a recipe declared
anything, they ask whether it did something that cannot survive the trip. A
positive check ("does it mention the data directory variable?") is satisfied by
writing that name in a comment, which is what a positive check always degrades
into. A negative one has to be answered by changing the code.

Two things they are not, both worth saying plainly:

**Not a security boundary.** A recipe is a process with the owner's privileges;
one that means harm does not need to violate a path convention, it can read
``~/.ssh``. These checks catch the recipe that never considered the question,
which is nearly all of them. The answer to malice is process isolation, and that
is a different piece of work.

**Not complete.** Every rule below is a text match over source. Each one names,
in its own docstring, the shape it cannot see. Being explicit about the holes is
what keeps this from being mistaken for a guarantee.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["block", "warn"]

#: Files that hold the recipe's own logic.
CODE_SUFFIXES = {".py", ".sh", ".js", ".mjs"}

#: Files a browser loads. Their mistakes are the expensive ones: a page is what
#: a visitor actually opens, so a page that cannot get its data is a page that
#: fails in front of the person you gave the link to.
PAGE_SUFFIXES = {".js", ".mjs", ".html", ".htm"}

# `/*` earns its place here the hard way: the first run of these checks over a
# real recipe reported a JSDoc block that merely *described* the endpoint it was
# moving away from. A rule that flags prose teaches people to ignore it.
_COMMENT_PREFIXES = ("#", "//", "/*", "*", "<!--")

# A path that names somebody's home directory. Machine-specific by construction:
# the author's disk is the only place it is true.
_HOME_LITERAL = re.compile(r"""["'](/Users/[^"'/]+|/home/[^"'/]+|[A-Za-z]:\\Users\\[^"'\\]+)""")

# The page asking the platform for a file by path. The endpoint behind this is
# closed to visitors and always will be — it reads any path on the machine.
_ARBITRARY_FILE_FETCH = re.compile(r"""(apiBase\s*[}+]?\s*[+`'"]?\s*/?file\b|/api/file\b)""")

# Home-derived paths. Portable in form, not in meaning: on a server this
# resolves to the service account, where the author's files were never copied.
_HOME_DERIVED = re.compile(r"""(Path\.home\(\)|os\.path\.expanduser|expanduser\(|\$HOME|~/)""")

_WRITE_CALL = re.compile(r"""(open\([^)]*["']w|write_text\(|write_bytes\(|mkdir\(|>\s*["']?\$)""")

# A relative path that reaches into a subdirectory — `assets/x.json`,
# `templates/page.html`. Those are almost always the recipe's own files, and the
# recipe no longer stands in its own directory.
# The extension has to be letters. Digits after a dot are a version, not a file
# type, and the first run of this rule over a real recipe proved it by reporting
# `"Mozilla/5.0"` in a User-Agent header as a path the recipe would fail to find.
_RELATIVE_SUBPATH = re.compile(r"""["']([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+\.[A-Za-z]{1,5})["']""")

_SELF_ANCHORED = re.compile(r"""(__file__|dirname\s*\(\s*["']?\$0|\$\(dirname)""")

_DATA_DIR_ENV = "FRAGO_RECIPE_DATA_DIR"


@dataclass(frozen=True)
class Finding:
    """One thing this recipe did that the platform cannot take over for it."""

    rule: str
    severity: Severity
    file: Path
    line: int
    excerpt: str
    fix: str

    def render(self, root: Path | None = None) -> str:
        where = self.file.relative_to(root) if root and self.file.is_relative_to(root) else self.file
        return f"[{self.severity}] {where}:{self.line}  {self.rule}\n    {self.excerpt}\n    → {self.fix}"


def _code_lines(path: Path) -> Iterable[tuple[int, str]]:
    """Lines with the obvious comments dropped.

    Deliberately crude — a path inside a docstring still counts. Erring toward
    reporting is the right side to err on here: a false report costs a person
    ten seconds, a missed one costs a visitor a blank page.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(_COMMENT_PREFIXES):
            continue
        yield number, stripped


def _files(recipe_dir: Path, suffixes: set[str], *, assets_only: bool = False) -> list[Path]:
    found = []
    for path in sorted(recipe_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if assets_only and "assets" not in path.parts:
            continue
        if not assets_only and "assets" in path.parts:
            continue
        found.append(path)
    return found


def _check_page_asks_for_arbitrary_files(recipe_dir: Path) -> list[Finding]:
    """The page reads its data through an endpoint visitors cannot use.

    This is the rule that pays for the module. A page written this way works
    perfectly for its author — the owner holds a token, so the endpoint answers —
    and returns nothing at all for every visitor, because that endpoint reads any
    path on the machine and is closed to anyone who is not the owner, signed in
    or not.

    Cannot see: a page that builds the same URL out of pieces at runtime.
    """
    findings = []
    for path in _files(recipe_dir, PAGE_SUFFIXES, assets_only=True):
        for line, text in _code_lines(path):
            if _ARBITRARY_FILE_FETCH.search(text):
                findings.append(Finding(
                    rule="page-asks-platform-for-files",
                    severity="block",
                    file=path, line=line, excerpt=text[:120],
                    fix=("这条路对主人以外一律关死，登录了也不行（那个接口能读机器上任意文件）。"
                         "改成读这张页面自己的目录：fetch('data/<文件名>')，"
                         "配方发布时把该文件放进它的数据目录。"),
                ))
    return findings


def _check_absolute_path_literals(recipe_dir: Path) -> list[Finding]:
    """A path that only exists on the machine the recipe was written on.

    Cannot see: the same path assembled from variables, or read from config.
    """
    findings = []
    for path in _files(recipe_dir, CODE_SUFFIXES):
        for line, text in _code_lines(path):
            match = _HOME_LITERAL.search(text)
            if match:
                findings.append(Finding(
                    rule="absolute-path-literal",
                    severity="block",
                    file=path, line=line, excerpt=text[:120],
                    fix=("这条路径只在写它的那台机器上存在。配方现在起跑在平台备好的目录里，"
                         "去掉开头那截、写相对路径即可。"),
                ))
    return findings


def _check_home_derived_writes(recipe_dir: Path, *, actions: bool) -> list[Finding]:
    """Writing somewhere derived from a home directory.

    Portable in form, wrong in meaning: on a server it resolves to whatever
    account runs the service, and the author's files were never put there.

    **A warning normally, and blocking once a mode carries ``@action``.** The
    severity tracks who can trigger the write. A recipe the owner runs is
    entitled to keep long-lived data in the owner's tree — that is the ordinary
    case and blocking it would train people to ignore this module. The moment a
    page can press it, the same line means every reader's press writes into one
    person's directory, which is the failure the retired
    ``actions-ignore-data-dir`` rule existed to catch and the one place it can
    still be caught.

    Cannot see: a home path that travels through a helper before being written.
    """
    findings = []
    for path in _files(recipe_dir, CODE_SUFFIXES):
        for line, text in _code_lines(path):
            if _HOME_DERIVED.search(text) and _WRITE_CALL.search(text):
                findings.append(Finding(
                    rule="home-derived-write",
                    severity="block" if actions else "warn",
                    file=path, line=line, excerpt=text[:120],
                    fix=(("这个 mode 标了 @action，页面上按得动，而这一行写的是一个"
                          "跟「谁在跑」无关的固定位置——于是每个人按下去，写的都是"
                          "同一份。" if actions else
                          "落点跟着「谁在跑」变，搬到服务器上就不是同一个地方了。")
                         + "写相对路径，让平台决定这一次该落在哪。"),
                ))
    return findings


def _check_bare_relative_self_reads(recipe_dir: Path) -> list[Finding]:
    """Reaching into a subdirectory by a relative path.

    ``assets/page.html`` is almost certainly the recipe's own file, and the
    recipe no longer stands in its own directory — it stands in this run's
    directory. The platform cannot tell these apart at runtime: it sees a file
    call, not an intent. So it is said here instead, once, with the fix.

    Cannot see: a bare filename with no directory in it, which is exactly the
    shape the new convention encourages and must not flag.
    """
    findings = []
    for path in _files(recipe_dir, CODE_SUFFIXES):
        for line, text in _code_lines(path):
            if _SELF_ANCHORED.search(text) or _HOME_DERIVED.search(text):
                continue
            match = _RELATIVE_SUBPATH.search(text)
            if match and not match.group(1).startswith(("http", "data/")):
                findings.append(Finding(
                    rule="relative-path-not-anchored",
                    severity="warn",
                    file=path, line=line, excerpt=text[:120],
                    fix=(f"「{match.group(1)}」看起来是配方自己的文件，但配方现在跑在数据目录里。"
                         "以自身位置起算：Path(__file__).parent / ...（shell 用 $(dirname \"$0\")）。"),
                ))
    return findings


def page_actions(recipe_dir: Path) -> tuple[str, ...]:
    """The modes this recipe opened to its own page — every ``@action``.

    Read straight off the recipe's source rather than through the registry,
    because every caller here has a directory in hand and may well be looking
    at a recipe that is not installed — one being written, one on a checkout,
    one in a test fixture.

    An unreadable or unparseable file answers "none". That is the closed
    direction, and it keeps one broken file from turning into two unrelated
    complaints: `validate` reports the parse failure loudly and by itself.
    """
    from frago.recipes.contract import read_recipe_dir

    surface = read_recipe_dir(recipe_dir)
    return () if surface is None else surface.actions


def declares_page_actions(recipe_dir: Path) -> bool:
    """Whether this recipe opened any of its modes to its own page."""
    return bool(page_actions(recipe_dir))


#: How a recipe says it is built on the base class, without importing it.
#: ``Recipe.data_dir`` *is* the read of the landing-spot variable, and it
#: raises when the platform did not set one — there is no fallback to fall back
#: to, which is a stronger guarantee than the string search below can give.
_BASE_CLASS_IMPORT = ("from frago_recipe import", "import frago_recipe")


def honours_the_landing_spot(recipe_dir: Path) -> bool:
    """Whether a run of this recipe would write where the platform tells it to.

    Two ways to satisfy it, and the second one is why this lives in one place.

    A recipe built on the base class qualifies: ``self.data_dir`` reads the
    variable and raises when it is unset, so such a recipe cannot quietly write
    somewhere else without going out of its way to bypass it.

    Everything else is held to a string search for the variable name. Weak, and
    known to be — a mention in a comment satisfies it. It catches the recipe
    that never considered the question, which is every recipe written before the
    variable existed, and it has to be a string search rather than an import
    check because a recipe carrying a PEP 723 block runs in an isolated
    environment where ``import frago`` raises.

    **One predicate, two callers.** This answer is needed by `frago recipe
    validate` and by the audit `expose` runs, and they had a copy each. The
    copies drifted in exactly the way that costs the most: the CLI's learned
    about the base class after six converted recipes passed on the machine they
    were written on and failed on the server, and the one here never did — so
    the first base-class recipe to open a mode to its page validated cleanly
    and would have been refused at `expose`, on the other machine, with a
    message telling the author to restore a line whose absence was the point of
    the conversion.
    """
    for path in _files(recipe_dir, CODE_SUFFIXES) + _files(recipe_dir, CODE_SUFFIXES, assets_only=True):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _DATA_DIR_ENV in text or any(sig in text for sig in _BASE_CLASS_IMPORT):
            return True
    return False


def audit(recipe_dir: Path, *, actions: bool | None = None) -> list[Finding]:
    """Everything this recipe did that cannot be taken over, worst first.

    ``actions`` overrides the recipe's own declaration, for a caller asking the
    hypothetical question ("what would break if this page could be pressed?").
    Left alone it reads the ``@action`` marks off the recipe's own methods,
    which is where the answer belongs.

    **A rule retired here, and why it is not simply gone.**
    ``actions-ignore-data-dir`` asked whether a recipe opening a mode to its
    page had ever heard of the landing-spot variable. Its precondition can no
    longer occur: an access level is a decorator, so a recipe that declares one
    is built on the base class, and ``Recipe.data_dir`` *is* that read — it
    raises when the platform did not set one, and the runner starts the process
    inside the run's own directory, so even a bare ``open("x.json", "w")``
    lands in the right place. A rule that cannot fire is worse than no rule,
    because it reads as protection that is not there.

    What it was actually guarding against did not go away, so it moved: the
    remaining way an ``@action`` mode writes into one shared pile is naming a
    place that has nothing to do with who is running — and that is what
    ``absolute-path-literal`` and ``home-derived-write`` look for. The second
    of those was only a warning, which is right for a recipe only its owner
    runs and wrong the moment a page can press it, so it now blocks when the
    recipe declares an action.
    """
    opened = declares_page_actions(recipe_dir) if actions is None else actions
    findings: list[Finding] = []
    findings += _check_page_asks_for_arbitrary_files(recipe_dir)
    findings += _check_absolute_path_literals(recipe_dir)
    findings += _check_home_derived_writes(recipe_dir, actions=opened)
    findings += _check_bare_relative_self_reads(recipe_dir)
    return sorted(findings, key=lambda f: (f.severity != "block", str(f.file), f.line))


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]
