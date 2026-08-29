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


def _check_home_derived_writes(recipe_dir: Path) -> list[Finding]:
    """Writing somewhere derived from a home directory.

    Portable in form, wrong in meaning: on a server it resolves to whatever
    account runs the service, and the author's files were never put there. Warn
    rather than block — plenty of recipes legitimately keep long-lived data in
    the owner's tree, and only the exposed ones have a visitor to disappoint.

    Cannot see: a home path that travels through a helper before being written.
    """
    findings = []
    for path in _files(recipe_dir, CODE_SUFFIXES):
        for line, text in _code_lines(path):
            if _HOME_DERIVED.search(text) and _WRITE_CALL.search(text):
                findings.append(Finding(
                    rule="home-derived-write",
                    severity="warn",
                    file=path, line=line, excerpt=text[:120],
                    fix=("落点跟着「谁在跑」变，搬到服务器上就不是同一个地方了。"
                         "写相对路径，让平台决定这一次该落在哪。"),
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


def declares_page_actions(recipe_dir: Path) -> bool:
    """Whether this recipe opened any of its modes to its own page.

    Read straight off ``recipe.md`` rather than through the registry, because
    every caller here has a directory in hand and may well be looking at a
    recipe that is not installed — one being written, one on a checkout, one in
    a test fixture.
    """
    metadata_path = recipe_dir / "recipe.md"
    if not metadata_path.is_file():
        return False
    try:
        from frago.recipes.metadata import parse_metadata_file

        return bool(parse_metadata_file(metadata_path).page_actions)
    except Exception:
        # Unparseable metadata is reported by `validate`, loudly and by itself.
        # Answering "no actions" here is the closed direction and keeps one
        # broken file from turning into two unrelated complaints.
        return False


def _check_actions_read_data_dir(recipe_dir: Path) -> list[Finding]:
    """The pre-existing gate for ``--runnable``, now keyed on the declaration.

    Weak by design and known to be: mentioning the name in a comment satisfies
    it. It catches the recipe that never considered the question, which is every
    recipe written before the variable existed.

    What changed is *when* it runs. It used to fire when a page was exposed with
    ``--runnable``, i.e. at the moment somebody who may not have written the
    recipe decided to open it. It now fires whenever the recipe itself says a
    page may trigger one of its modes — which is the moment the author is still
    holding the file, and is the same answer on every machine the recipe reaches.
    """
    for path in _files(recipe_dir, CODE_SUFFIXES) + _files(recipe_dir, CODE_SUFFIXES, assets_only=True):
        try:
            if _DATA_DIR_ENV in path.read_text(encoding="utf-8", errors="ignore"):
                return []
        except OSError:
            continue
    return [Finding(
        rule="actions-ignore-data-dir",
        severity="block",
        file=recipe_dir, line=0, excerpt="(recipe as a whole)",
        fix=(f"这个配方在 page_actions 里开了页面能触发的 mode，而它写死了自己的落点——"
             f"于是每个人从页面按下去，写的都是主人那一份。"
             f"读一下 {_DATA_DIR_ENV}：\n"
             f'    data_dir = os.environ.get("{_DATA_DIR_ENV}") or <自己的老默认值>\n'
             f"不打算开给页面按，就把 page_actions 清空。"),
    )]


def audit(recipe_dir: Path, *, actions: bool | None = None) -> list[Finding]:
    """Everything this recipe did that cannot be taken over, worst first.

    ``actions`` overrides the recipe's own declaration, for a caller asking the
    hypothetical question ("what would break if this page could be pressed?").
    Left alone it reads ``page_actions`` off the recipe, which is where the
    answer belongs.
    """
    findings: list[Finding] = []
    findings += _check_page_asks_for_arbitrary_files(recipe_dir)
    findings += _check_absolute_path_literals(recipe_dir)
    findings += _check_home_derived_writes(recipe_dir)
    findings += _check_bare_relative_self_reads(recipe_dir)
    if declares_page_actions(recipe_dir) if actions is None else actions:
        findings += _check_actions_read_data_dir(recipe_dir)
    return sorted(findings, key=lambda f: (f.severity != "block", str(f.file), f.line))


def blocking(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "block"]
