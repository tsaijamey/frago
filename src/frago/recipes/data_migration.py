"""Moving recipe data onto the layout in ``frago book must-recipe-data``.

The layout changed because letting each recipe pick its own directory produced
several copies of one thing, drifting apart with nothing raising: a ledger on
one server existed in four places holding 48, 45, 45 and 37 trades, and the page
people read showed the three-day-old one while reporting every refresh as a
success.

Three properties this has to have, each because of how that failure worked:

**Nothing is deleted.** Every move is a copy, verified, and the original stays
where it is. A migration that removes as it goes has no way back the moment one
of its guesses is wrong, and the guesses here are about a person's own records.

**Every move is written down.** The manifest is what makes the copies safe: two
copies of one thing is the disease, and the only thing that makes it survivable
is a record saying which one is authoritative and when the other stopped being
read. Without that record this tool would be reproducing the bug it exists to
fix.

**What cannot be worked out is listed, not guessed.** Where a recipe recorded
its directory under the platform's own key, the move is derivable. Where it
invented a key of its own — ``projectsDir``, ``ledgerPath``, ``comfy_dir`` — no
amount of reading gets a machine to certainty, so those are reported for a
person to confirm once rather than moved on a hunch.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.recipes.app_state import (
    APP_STATE_DIR,
    InvalidSlotName,
    _validate,
    recipe_data_dir,
)
from frago.recipes.app_state import (
    DEFAULT_SLOT as DEFAULT_SLOT_NAME,
)

#: Where the record of what moved lives. Beside the data rather than in a
#: temporary directory: it has to outlive the run that wrote it, because the
#: question it answers ("is the copy under the old path still being read?")
#: comes up months later.
MANIFEST_NAME = "migration-manifest.jsonl"

#: The key the platform itself writes. A slot that records its directory here is
#: one whose move can be derived; anything else is a recipe's own invention.
PLATFORM_KEY = "dataDir"


def manifest_path(home: Path | None = None) -> Path:
    root = (home or Path.home()) / ".frago"
    return root / MANIFEST_NAME


@dataclass(frozen=True)
class Move:
    """One directory that can be moved without anybody having to decide."""

    recipe: str
    slot: str
    source: Path
    target: Path
    #: Why a gate was waived for this one, when one was. Empty for the ordinary
    #: case. Carried into the manifest so the reason outlives the decision —
    #: "why is a deliverable filed under a recipe" gets asked long after the
    #: person who answered it has forgotten.
    exception: str = ""

    @property
    def is_project(self) -> bool:
        """Whether this slot is one body of work among several.

        The default slot is the recipe's single instance; a named slot is a
        project. This is the same distinction the layout draws, read off what
        the machine already has rather than asked again.
        """
        return self.slot != "default"


@dataclass(frozen=True)
class Unresolved:
    """A slot whose directory only its own recipe knows how to name."""

    recipe: str
    slot: str
    keys: tuple[str, ...]
    values: tuple[str, ...]


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    blocked: list[tuple[str, str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.moves) + len(self.unresolved) + len(self.blocked)


def _slot_states(home: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """Every slot the owner side has, as (recipe, slot, state)."""
    root = home / ".frago" / APP_STATE_DIR.name
    if not root.is_dir():
        return []
    out = []
    for recipe_dir in sorted(root.iterdir()):
        if not recipe_dir.is_dir():
            continue
        for slot_file in sorted(recipe_dir.glob("*.json")):
            try:
                state = json.loads(slot_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(state, dict):
                out.append((recipe_dir.name, slot_file.stem, state))
    return out


def _own_path_keys(state: dict[str, Any], home: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keys holding a path into this machine's frago home under a name the
    recipe chose itself."""
    keys, values = [], []
    for key, value in state.items():
        if key == PLATFORM_KEY or not isinstance(value, str):
            continue
        if value.startswith("/") and str(home / ".frago") in value:
            keys.append(key)
            values.append(value)
    return tuple(keys), tuple(values)


def plan(identity: str, home: Path | None = None) -> Plan:
    """Work out what can move and what a person has to confirm.

    Reads only. Nothing here touches a byte — the whole point of splitting this
    from ``apply`` is that the answer can be looked at before anything happens.
    """
    home = home or Path.home()
    result = Plan()
    for recipe, slot, state in _slot_states(home):
        try:
            _validate(recipe, slot)
        except InvalidSlotName as err:
            result.skipped.append((recipe, slot, f"名字不合法：{err}"))
            continue

        raw = state.get(PLATFORM_KEY)
        keys, values = _own_path_keys(state, home)
        if not isinstance(raw, str) or not raw:
            if keys:
                result.unresolved.append(Unresolved(recipe, slot, keys, values))
            else:
                result.skipped.append((recipe, slot, "这个槽位没有记任何目录"))
            continue

        source = Path(raw).expanduser()
        target = recipe_data_dir(identity, recipe, slot if slot != "default" else None)
        if source == target:
            result.skipped.append((recipe, slot, "已经在新落点上了"))
            continue
        if not source.is_dir():
            result.skipped.append((recipe, slot, f"记着的目录不存在：{source}"))
            continue
        if _is_a_root(source, home):
            result.blocked.append((
                recipe, slot,
                f"这是一整棵树的根，不是某个配方的目录：{source}。"
                f"搬它等于把整台机器的东西挂到一个配方名下。"
                f"这个配方多半是把单个文件直接丢在根上了，先给它一个自己的目录",
            ))
            continue
        if _is_platform_owned(source, home):
            result.blocked.append((
                recipe, slot,
                f"这在 frago 自己维护的目录里，不是这个配方的数据：{source}。"
                f"把它挂到配方名下等于把别人的记录认领成自己的，还要把每个字节复制一遍。"
                f"配方往那儿写这件事本身该修，但复制不是修法",
            ))
            continue
        if _is_deliverable(source, home):
            result.blocked.append((
                recipe, slot,
                f"这是带日期的交付物目录、不是配方工作数据，按分界它留在原地：{source}",
            ))
            continue
        if _is_recipe_code(source, home):
            result.blocked.append((
                recipe, slot,
                f"这个目录在配方自己的代码包里，搬走会拆掉配方本体：{source}",
            ))
            continue
        if target.is_dir() and _weigh(target) == _weigh(source):
            # Already copied. Saying "would copy" here would make a dry run
            # describe work that is finished, and a dry run people cannot take
            # at face value is worse than no dry run at all.
            result.skipped.append((recipe, slot, f"已经搬过，两边一致：{target}"))
            continue
        result.moves.append(Move(recipe, slot, source, target))
        if keys:
            # It recorded the platform's key *and* invented some of its own. The
            # directory moves; the rest still needs a person, because a recipe
            # that names two directories may well be reading the second from
            # somewhere this tool has no business relocating.
            result.unresolved.append(Unresolved(recipe, slot, keys, values))

    shared = _shared_sources(result.moves)
    if shared:
        result.moves = [m for m in result.moves if m.source.resolve() not in shared]
        for src, claims in shared.items():
            who = "、".join(f"{m.recipe}/{m.slot}" for m in claims)
            for one in claims:
                result.blocked.append((
                    one.recipe, one.slot,
                    f"这个目录同时被 {who} 认领。复制它就是把一份数据变成几份——"
                    f"正是这次要修的毛病。先定下它归谁：{src}",
                ))
    return result


#: A transaction directory under ``must-data-dir``: a subject, then a date and a
#: slug. What lives there is a deliverable a person filed, not a recipe's working
#: data, and the two trees are kept apart on purpose — see ``must-recipe-data``.
_DATED = re.compile(r"^\d{8}-")


def _is_deliverable(source: Path, home: Path) -> bool:
    """Whether this directory is somebody's filed work rather than a recipe's.

    A recipe that published a dated transaction directory as its data directory
    was reaching into the other tree. Copying it into the recipe's own area
    would put a deliverable somewhere nobody looks for one, and leave the
    original as the copy people actually open.

    The shape is exact, and has to be. ``must-data-dir`` puts a transaction at
    ``data/<subject>/<date>-<slug>/`` — the date sits at the second level and
    nowhere else. A first pass here matched a dated component at *any* depth
    and swept up ten video projects filed as
    ``data/agent-os/videos/<date>-<slug>/``: those are one recipe's projects,
    which are exactly what this migration is for, and naming a project after a
    date does not make it somebody's filed report. A gate that blocks the case
    it exists to serve is worse than no gate, because the person reading its
    refusal has no way to tell it apart from a real one.
    """
    data_root = home / ".frago" / "data"
    if not source.is_relative_to(data_root):
        return False
    parts = source.relative_to(data_root).parts
    # parts[0] is the subject; a transaction directory is parts[1]. Anything at
    # or below it belongs to that transaction; anything else merely has a date
    # in its name.
    return len(parts) >= 2 and bool(_DATED.match(parts[1]))


def _is_recipe_code(source: Path, home: Path) -> bool:
    """Whether this directory is part of a recipe's own package.

    Some recipes ship data beside their code. That is its own problem, but it is
    not this one: moving it takes a file the recipe imports or reads by relative
    path and leaves the recipe broken, which is a worse outcome than the
    duplication being fixed here.
    """
    return source.is_relative_to(home / ".frago" / "recipes")


def _is_a_root(source: Path, home: Path) -> bool:
    """Whether this is a whole tree rather than one recipe's directory.

    A recipe that keeps a single file directly under ``~/.frago/data`` reports
    its directory as ``~/.frago/data`` — and copying that would take everything
    on the machine and file it under one recipe's name. It is the largest
    possible version of this tool's own failure mode, and unlike the others it
    would look like a success right up until the disk filled.

    Named explicitly rather than by depth: a rule like "at least three levels
    down" is one refactor away from being wrong, while these five are what they
    are.
    """
    try:
        resolved = source.resolve()
    except OSError:
        return True
    roots = {
        Path("/"),
        home.resolve(),
        (home / ".frago").resolve(),
        (home / ".frago" / "data").resolve(),
        (home / ".frago" / "recipes").resolve(),
        (home / ".frago" / "users").resolve(),
        (home / ".frago" / "projects").resolve(),
    }
    return resolved in roots


#: Trees frago itself owns and writes. A recipe that keeps things in one of
#: these is not keeping its own data — it is writing into the platform's, which
#: is a separate problem and not one a copy can fix.
_PLATFORM_TREES = ("sessions", "app-state", "executions", "traces", "books", "bin", "viewer")


def _is_platform_owned(source: Path, home: Path) -> bool:
    """Whether this lives inside something frago maintains for itself.

    One recipe reads and writes the session store at ``~/.frago/sessions`` —
    5 GB that frago's own session sync also owns. Filing that under the recipe's
    name would claim 5 GB of somebody else's records as this recipe's data and
    duplicate every byte of it. The recipe writing there at all is worth fixing;
    copying it is not the fix.
    """
    root = (home / ".frago").resolve()
    try:
        resolved = source.resolve()
    except OSError:
        return True
    if not resolved.is_relative_to(root):
        return False
    parts = resolved.relative_to(root).parts
    return bool(parts) and parts[0] in _PLATFORM_TREES


def _shared_sources(moves: list[Move]) -> dict[Path, list[Move]]:
    """Sources that more than one slot claims.

    Two slots pointing at one directory is the defect this whole layout exists
    to remove: the platform believes there are two bodies of work and the disk
    holds one, each overwriting the other in silence. Copying it would turn one
    directory into two that then drift apart — this tool reproducing, by hand,
    exactly the failure it was written to end. So it stops and says whose.
    """
    seen: dict[Path, list[Move]] = {}
    for one in moves:
        seen.setdefault(one.source.resolve(), []).append(one)
    return {src: claims for src, claims in seen.items() if len(claims) > 1}


def plan_from_entries(
    identity: str,
    entries: list[dict[str, Any]],
    home: Path | None = None,
) -> Plan:
    """Turn hand-supplied source directories into a plan, gates and all.

    Most recipes never recorded their directory anywhere a machine can read, so
    the only way to learn it is for someone to read the code. That answer comes
    in here — and it goes through **exactly the same three refusals** as one the
    tool worked out itself.

    That symmetry is the point. A hand-supplied path feels more authoritative
    than a derived one and is in fact less: it was typed by whoever read the
    code last, and the failures the gates catch (two recipes claiming one
    directory, a dated deliverable, a directory inside a recipe's package) are
    exactly the ones a reader is most likely to miss. Letting an explicit plan
    skip them would put the gates where they are never needed and remove them
    where they are.
    """
    home = home or Path.home()
    result = Plan()
    for entry in entries:
        recipe = str(entry.get("recipe") or "")
        slot = str(entry.get("slot") or DEFAULT_SLOT_NAME)
        raw = str(entry.get("source") or "")
        if not recipe or not raw:
            result.skipped.append((recipe or "?", slot, "这条没写清 recipe 或 source"))
            continue
        try:
            _validate(recipe, slot)
        except InvalidSlotName as err:
            result.skipped.append((recipe, slot, f"名字不合法：{err}"))
            continue

        source = Path(raw).expanduser()
        target = recipe_data_dir(identity, recipe, slot if slot != DEFAULT_SLOT_NAME else None)
        if source == target:
            result.skipped.append((recipe, slot, "已经在新落点上了"))
            continue
        if not source.is_dir():
            result.skipped.append((recipe, slot, f"给的目录不存在：{source}"))
            continue
        if _is_a_root(source, home):
            result.blocked.append((
                recipe, slot,
                f"这是一整棵树的根，不是某个配方的目录：{source}。"
                f"搬它等于把整台机器的东西挂到一个配方名下。"
                f"这个配方多半是把单个文件直接丢在根上了，先给它一个自己的目录",
            ))
            continue
        if _is_platform_owned(source, home):
            result.blocked.append((
                recipe, slot,
                f"这在 frago 自己维护的目录里，不是这个配方的数据：{source}。"
                f"把它挂到配方名下等于把别人的记录认领成自己的，还要把每个字节复制一遍。"
                f"配方往那儿写这件事本身该修，但复制不是修法",
            ))
            continue
        if _is_deliverable(source, home) and not entry.get("deliverable_ok"):
            result.blocked.append((
                recipe, slot,
                f"这是带日期的交付物目录、不是配方工作数据，按分界它留在原地：{source}。"
                f"确实要搬的，在这一条上写 deliverable_ok 与 why——"
                f"例外要逐条写在它适用的那一项旁边，NEVER 做成一个一开就全放行的开关",
            ))
            continue
        if _is_recipe_code(source, home):
            result.blocked.append((
                recipe, slot,
                f"这个目录在配方自己的代码包里，搬走会拆掉配方本体：{source}",
            ))
            continue
        if target.is_dir() and _weigh(target) == _weigh(source):
            result.skipped.append((recipe, slot, f"已经搬过，两边一致：{target}"))
            continue
        result.moves.append(Move(recipe, slot, source, target,
                                 exception=str(entry.get("why") or "")))

    shared = _shared_sources(result.moves)
    if shared:
        result.moves = [m for m in result.moves if m.source.resolve() not in shared]
        for src, claims in shared.items():
            who = "、".join(f"{m.recipe}/{m.slot}" for m in claims)
            for one in claims:
                result.blocked.append((
                    one.recipe, one.slot,
                    f"这个目录同时被 {who} 认领。复制它就是把一份数据变成几份——"
                    f"正是这次要修的毛病。先定下它归谁：{src}",
                ))
    return result


def _weigh(directory: Path) -> tuple[int, int]:
    """How many files and how many bytes, for checking a copy landed whole."""
    files = 0
    total = 0
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += 1
            with contextlib.suppress(OSError):
                total += path.stat().st_size
    return files, total


class MigrationFailed(RuntimeError):
    """A copy did not land whole. The original is untouched; nothing was lost."""


def apply(one: Move, home: Path | None = None) -> dict[str, Any]:
    """Copy one directory to its new home and write down that it happened.

    Copy rather than move, and verified by weight afterwards. A partial copy
    that nobody noticed would be the worst outcome available here — it looks
    exactly like a successful migration, and the thing it lost is a person's
    own records.

    Re-running is safe: a target that already matches the source is left alone
    and reported as such, so an interrupted migration can simply be run again.
    """
    home = home or Path.home()
    before = _weigh(one.source)

    if one.target.exists():
        now = _weigh(one.target)
        if now == before:
            return _record(one, before, home, note="已经搬过，内容一致，跳过")

        # The two differ. Which of them moved decides whether this is safe.
        #
        # A machine does not stop while it is being migrated: a scheduled task
        # or a running server writes to the source minutes after it was copied,
        # and the copy is then simply out of date. That is ordinary and worth
        # refreshing. What is not ordinary is somebody having written to the
        # *target* — then there is real work under the new path, and copying
        # over it destroys the only copy of it.
        #
        # The manifest tells them apart: it recorded what the copy weighed the
        # moment it was made. A target that still weighs that has not been
        # touched since.
        recorded = _recorded_weight(one, home)
        if recorded is not None and now == recorded:
            shutil.rmtree(one.target)
            shutil.copytree(one.source, one.target, symlinks=True)
            after = _weigh(one.target)
            if after != before:
                raise MigrationFailed(
                    f"{one.recipe}/{one.slot} 刷新后对不上：源 {before}，新落点 {after}。"
                )
            return _record(one, before, home, note="源在上次复制之后又变了，已按源刷新")

        raise MigrationFailed(
            f"{one.recipe}/{one.slot} 的新落点已存在且内容不同：{one.target}。"
            f"账本记的是 {recorded}，它现在是 {now}——有人往新落点写过东西，"
            f"覆盖它就是毁掉那份工作。没有动任何东西，先弄清那是什么再来。"
        )

    one.target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(one.source, one.target, symlinks=True)
    after = _weigh(one.target)
    if after != before:
        raise MigrationFailed(
            f"{one.recipe}/{one.slot} 复制后对不上：源 {before[0]} 个文件/{before[1]} 字节，"
            f"新落点 {after[0]}/{after[1]}。原目录一个字节都没动。"
        )
    return _record(one, before, home)


def _recorded_weight(one: Move, home: Path) -> tuple[int, int] | None:
    """What the manifest says this copy weighed when it was made.

    The last entry wins: the file is append-only, so a directory copied more
    than once has more than one line, and the current copy is the newest.
    """
    try:
        raw = manifest_path(home).read_text(encoding="utf-8")
    except OSError:
        return None
    found = None
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(entry, dict)
                and entry.get("recipe") == one.recipe
                and entry.get("slot") == one.slot
                and entry.get("target") == str(one.target)):
            try:
                found = (int(entry["files"]), int(entry["bytes"]))
            except (KeyError, TypeError, ValueError):
                continue
    return found


def _record(one: Move, weight: tuple[int, int], home: Path, note: str = "") -> dict[str, Any]:
    """Append one line to the manifest. Append, never rewrite.

    A manifest that gets rewritten can lose the very entry someone is looking
    for, and the thing it is asked months later is "was this old directory ever
    migrated, and to where".
    """
    entry = {
        "when": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recipe": one.recipe,
        "slot": one.slot,
        "source": str(one.source),
        "target": str(one.target),
        "files": weight[0],
        "bytes": weight[1],
        # The original is still there and still readable. It stops being read
        # when the cutover lands, and only then is it a candidate for removal —
        # which is a separate, deliberate act, never a side effect of this one.
        "source_kept": True,
        "note": note,
        "exception": one.exception,
    }
    path = manifest_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry


def already_migrated(home: Path | None = None) -> set[tuple[str, str]]:
    """Which (recipe, slot) pairs the manifest says have been copied."""
    path = manifest_path(home)
    done: set[tuple[str, str]] = set()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return done
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("recipe"):
            done.add((entry["recipe"], entry.get("slot", "default")))
    return done
