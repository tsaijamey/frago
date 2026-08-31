"""What a recipe opened, and to whom. Read off the methods, never off a list.

A mode's reach used to be two lists of names in ``recipe.md`` — ``exports``
and ``page_actions`` — that had to agree with a third list of names in the
class. Three places, kept in step by hand, and two of the three ways they
could disagree were invisible on the machine the recipe was written on:

* ``page_actions`` naming a mode that does not exist raised nothing anywhere.
  The recipe validated, the page worked for its author, and the first stranger
  to press the button got a 403.
* The owner's own path consults neither list, so a page missing an access
  level works perfectly for whoever wrote it and fails for everybody else.

So the answer moved onto the thing it is about. ``@export`` and ``@action``
sit on the method, one level per mode, and everything the platform needs — the
mode list, the exported surface, the page's buttons — is derived from that one
mark. There is nothing left to keep in step.

**Read, never imported.** Working out what a module offers must not run it.
Importing a recipe to ask it a question would execute whatever sits at its
module level, on a machine where no run is in progress, every time anybody
asked — and recipes are written to be run, not imported: ``main()`` is called
bare at the bottom of the file precisely so that importing one *is* running
it. So this parses. It reads the decorator's **name**, which is why a recipe
may spell it ``@export`` or ``@frago_recipe.export`` and both are seen, and
why an aliased import is not.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: The decorator names that carry an access level. Closed set, and closed on
#: purpose: an unrecognised mark is reported rather than ignored, because a
#: typo'd ``@exports`` that silently meant "owner only" would take a mode off
#: the bus with the file still saying otherwise.
EXPORT = "export"
ACTION = "action"
LEVELS = (EXPORT, ACTION)


@dataclass(frozen=True)
class Surface:
    """Everything one module opened, in one answer.

    One object rather than three functions because the three answers come from
    one reading and must never disagree — the previous arrangement had the
    export list and the action list arriving from different files, which is how
    a mode ended up in both.
    """

    #: Every mode, in the order the methods are written.
    modes: tuple[str, ...] = ()
    #: What another module may ask for. Read-only by contract.
    exports: tuple[str, ...] = ()
    #: What this recipe's own page may trigger. Allowed to do work.
    actions: tuple[str, ...] = ()
    #: Which mode a caller gets when they name none.
    default: str = ""
    #: What is wrong with the declaration itself, in the author's words. These
    #: are the recipe's mistakes, not the caller's, and `frago recipe validate`
    #: is where they are meant to surface.
    problems: tuple[str, ...] = ()


def read_source(source: str) -> Surface | None:
    """The surface of the module in this source, or None if there is no module.

    None and an empty ``Surface`` are different answers and the difference
    matters at every call site: a file with no ``Recipe`` subclass has not
    agreed to anything and cannot be asked, while a module that marked nothing
    has answered — with "only the owner". The bus draws exactly this line when
    it decides between "does not export that" and "is not a module".
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    node = _subclass(tree)
    if node is None:
        return None

    modes: list[str] = []
    exports: list[str] = []
    actions: list[str] = []
    problems: list[str] = []

    for stmt in node.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        marks = _marks(stmt)
        if not stmt.name.startswith("mode_"):
            if marks:
                problems.append(
                    f"{stmt.name} 上标了 @{marks[0]}，但它不是一个 mode——"
                    f"访问级别是给 mode_<名字> 方法用的，标在别处不起任何作用。"
                )
            continue
        mode = stmt.name[len("mode_"):]
        if mode in modes:
            problems.append(f"mode_{mode} 定义了不止一次，后一个会盖掉前一个。")
            continue
        modes.append(mode)
        if len(marks) > 1:
            # Unreachable through the intended shape and refused anyway: one
            # mode has one level. "Exported and also a page button" was never
            # coherent — an exported mode is read-only and the page reads it
            # through api/<mode> without a button.
            problems.append(
                f"mode_{mode} 同时标了 {'、'.join('@' + m for m in marks)}。"
                f"一个 mode 只有一个访问级别：@export 是只读契约（总线和页面都读得到），"
                f"@action 是页面能触发、允许干活，两者不是一回事也不叠加。"
            )
            continue
        if marks == [EXPORT]:
            exports.append(mode)
        elif marks == [ACTION]:
            actions.append(mode)

    default = _default_mode(node)
    if default and default not in modes:
        problems.append(
            f"default_mode 是 {default!r}，但没有 mode_{default} 方法。"
            f"本模块有的是：{'、'.join(modes) or '（一个都没有）'}"
        )
        default = ""

    for retired in ("modes", "exports", "page_actions"):
        if _assigns(node, retired):
            problems.append(
                f"类上还写着 {retired}。这一项现在由平台从 mode_* 方法上的访问级别推导，"
                f"手写的那份一旦和方法对不上，页面和总线各按各的答案走，而且不报错。"
                f"删掉它，改在方法上标 @export / @action。"
            )

    return Surface(
        modes=tuple(modes),
        exports=tuple(exports),
        actions=tuple(actions),
        default=default,
        problems=tuple(problems),
    )


def read_recipe_dir(recipe_dir: Path) -> Surface | None:
    """The surface of the recipe sitting in this directory.

    Takes a directory rather than a name because every caller in the authoring
    path has one in hand and may well be looking at a recipe that is not
    installed — one being written, one on a checkout, one in a test fixture.
    """
    script = recipe_dir / "recipe.py"
    try:
        return read_source(script.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return None


def surface_of(name: str, wanted: str | None = None) -> Surface | None:
    """The surface of an installed recipe, by name. None when it is not a module.

    ``wanted`` is the mode about to be checked, and it is passed for one
    reason: the registry is a snapshot taken at startup, so a level added
    afterwards is invisible until something happens to rescan. Being refused
    for something that was opened five minutes ago is indistinguishable from
    never having opened it, and the person debugging it is looking at a file
    that plainly says otherwise. So a refusal costs one rescan before it is
    final, and only a refusal — rescanning on every call would walk the recipe
    tree for every question anybody asks, and the overwhelmingly common answer
    is already correct from the snapshot.
    """
    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.registry import get_registry, invalidate_registry

    def _look() -> Surface | None:
        try:
            recipe = get_registry().find(name)
        except (RecipeNotFoundError, OSError):
            return None
        script = getattr(recipe, "script_path", None)
        if not script:
            return None
        try:
            return read_source(Path(script).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return None

    found = _look()
    if found is None or (wanted is not None and wanted not in found.modes):
        try:
            invalidate_registry()
        except OSError:
            logger.warning("could not rescan recipes before answering about %s",
                           name, exc_info=True)
            return found
        found = _look()
    return found


def exports_of(name: str, wanted: str | None = None) -> tuple[str, ...] | None:
    """Which modes this module offers other modules. None when it is not a module.

    The None is load-bearing and is not the same as an empty tuple: a file that
    is not a module has not agreed to anything, and the hub says so rather than
    assuming either way.
    """
    surface = surface_of(name, wanted)
    return None if surface is None else surface.exports


def page_actions_of(name: str, wanted: str | None = None) -> tuple[str, ...]:
    """The modes this recipe's page may trigger. Empty when it opened none.

    Never raises, and an empty tuple is the right answer to every failure here.
    A recipe that cannot be found opened nothing, which is the same answer as a
    recipe that opened nothing — and both mean the page gets no buttons.
    """
    surface = surface_of(name, wanted)
    return () if surface is None else surface.actions


def _subclass(tree: ast.AST) -> ast.ClassDef | None:
    """The ``Recipe`` subclass in this file, or None.

    Matched on the base's name rather than by resolving it, for the same reason
    the decorators are matched on their names: resolving would mean importing.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(b, ast.Name) and b.id == "Recipe")
            or (isinstance(b, ast.Attribute) and b.attr == "Recipe")
            for b in node.bases
        ):
            return node
    return None


def _marks(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """The access levels decorating this method, by name."""
    found = []
    for dec in fn.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in LEVELS:
            found.append(dec.id)
        elif isinstance(dec, ast.Attribute) and dec.attr in LEVELS:
            found.append(dec.attr)
    return found


def _assigns(node: ast.ClassDef, attr: str) -> bool:
    """Whether the class body binds this name."""
    for stmt in node.body:
        targets = (
            [stmt.target] if isinstance(stmt, ast.AnnAssign)
            else getattr(stmt, "targets", [])
        )
        if any(isinstance(t, ast.Name) and t.id == attr for t in targets):
            return True
    return False


def _default_mode(node: ast.ClassDef) -> str:
    for stmt in node.body:
        targets = (
            [stmt.target] if isinstance(stmt, ast.AnnAssign)
            else getattr(stmt, "targets", [])
        )
        if not any(isinstance(t, ast.Name) and t.id == "default_mode" for t in targets):
            continue
        value = getattr(stmt, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return ""
