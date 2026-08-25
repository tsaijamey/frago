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
#: ``state`` earned its place the hard way: the whole of ``~/.frago/state`` was
#: filed as one recipe's data directory and copied under its name, carrying
#: another recipe's cursor, a team watcher, and a credentials file into a second
#: location — the duplication this tool exists to end, performed by the tool
#: itself. The gate was there and this name simply was not on the list.
_PLATFORM_TREES = ("sessions", "app-state", "executions", "traces", "books",
                   "bin", "viewer", "state")


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

    if one.target.exists() and _weigh(one.target) != (0, 0):
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

    # An empty target counts as no target. Every recipe now creates its data
    # directory before writing anything, so merely *running* one leaves an empty
    # directory behind — and the guard above then refused the migration with
    # "somebody has written here, overwriting it destroys their work" while
    # reporting, in the same sentence, that it holds zero files and zero bytes.
    # A refusal whose stated reason contradicts its own evidence teaches people
    # to force past it, which is the last habit this tool should be building.
    one.target.parent.mkdir(parents=True, exist_ok=True)
    if one.target.exists():
        one.target.rmdir()  # empty by the check above; fails loudly if not
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
        # Which kind of line this is. Written from here on so the ledger says so
        # itself; the lines already in the file predate the lifecycle and are
        # read as copies, because that is what every one of them is.
        "lifecycle": LIFECYCLE_COPIED,
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


def data_left_behind(
    recipe_name: str,
    identity: str,
    slot: str = DEFAULT_SLOT_NAME,
    home: Path | None = None,
) -> Path | None:
    """The old directory this slot's records are still sitting in, if any.

    The platform withholds a recipe's new directory while its records are
    elsewhere, because pointing it at an empty one is a fresh start nobody asked
    for. The question that gate has to ask is **"is anything of this recipe's
    still under an old path"** — and it used to ask "has anything of this
    recipe's ever been copied", which is not the same question and is wrong in
    exactly one direction: a recipe that never had data cannot appear in the
    manifest, so it was told forever that the platform had not said where to
    write. ``etf_dma_signal_push`` kept its state inside its own package, which
    the migration refuses to move on purpose; once it stopped inventing a
    default of its own it could not start at all.

    So the answer comes from what is on disk rather than from what has been
    copied: a slot that recorded a directory, still has it, and has not had it
    copied is left behind. A slot that recorded nothing has nothing to lose.

    Scoped to one slot rather than the whole recipe. A multi-project recipe
    migrates its projects one at a time, and one project still waiting is not a
    reason to refuse the other six.
    """
    home = home or Path.home()
    slot_file = home / ".frago" / APP_STATE_DIR.name / recipe_name / f"{slot}.json"
    try:
        state = json.loads(slot_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    raw = state.get(PLATFORM_KEY)
    if not isinstance(raw, str) or not raw:
        return None
    if (recipe_name, slot) in already_migrated(home):
        return None
    try:
        target = recipe_data_dir(
            identity, recipe_name, None if slot == DEFAULT_SLOT_NAME else slot
        )
    except InvalidSlotName:
        return None
    source = Path(raw).expanduser()
    if source == target or not source.is_dir():
        return None
    return source


#: What a ledger line records. A line with no ``lifecycle`` key is a copy: every
#: line written before this existed is one, and reading them as anything else
#: would rewrite history by interpretation — which is exactly what an
#: append-only file is supposed to make impossible.
LIFECYCLE_COPIED = "copied"
LIFECYCLE_SEALED = "sealed"

#: The three stages a copied directory can be in. There is no fourth: either
#: something still touches the old copy, or nothing does and it is waiting for a
#: date, or it is gone and the ledger says so.
STILL_LIVE = "still_live"
READY_TO_EXPIRE = "ready_to_expire"
SEALED = "sealed"

#: How long an old copy has to sit untouched before "nobody reads this" is worth
#: believing. A month covers a monthly job, which is the longest cadence anything
#: on this machine runs at; below that the quiet may just be the gap between two
#: runs of the very thing that would have written to it.
QUIET_ENOUGH_DAYS = 30


@dataclass(frozen=True)
class Audited:
    """One migrated body of data, and which of the three stages it is in.

    ``reasons`` is what put it there, in the words a person can act on. A stage
    without a reason is a verdict nobody can check — and the whole reason this
    exists is that the last three rounds of "which copy is real" were settled by
    hand, by comparing timestamps.
    """

    recipe: str
    slot: str
    source: Path
    target: Path
    when: str
    stage: str
    reasons: tuple[str, ...] = ()
    #: Newest file in the old copy, ISO. Empty when the old copy is gone.
    last_write: str = ""
    #: Days since that write. -1 when there is nothing left to measure.
    quiet_days: int = -1
    files: int = 0
    size: int = 0

    @property
    def quiet_enough(self) -> bool:
        return self.quiet_days >= QUIET_ENOUGH_DAYS


@dataclass
class Audit:
    """What the ledger's entries look like right now.

    ``ledger_exists`` is carried separately from an empty list on purpose. "I
    scanned and everything is fine" and "there is nothing here to scan" produce
    the same empty result and mean opposite things, and the second one silently
    passing for the first is how a check stops being a check.
    """

    identity: str
    ledger: Path
    ledger_exists: bool
    lines: int = 0
    checked: list[Audited] = field(default_factory=list)

    def at(self, stage: str) -> list[Audited]:
        return [one for one in self.checked if one.stage == stage]

    @property
    def still_live(self) -> list[Audited]:
        return self.at(STILL_LIVE)

    @property
    def ready(self) -> list[Audited]:
        return self.at(READY_TO_EXPIRE)

    @property
    def sealed(self) -> list[Audited]:
        return self.at(SEALED)

    @property
    def needs_attention(self) -> int:
        """How many a person has to do something about. Zero is a real answer
        and is not the same as having checked nothing — see ``ledger_exists``."""
        return len(self.still_live)


def _ledger_lines(home: Path) -> list[dict[str, Any]]:
    """Every well-formed line, oldest first. Damaged lines are stepped over.

    A single unparseable line must not take the rest of the ledger with it: the
    whole point of one JSON document per line is that the file survives partial
    damage, and a reader that gives up on the first bad byte throws that away.
    """
    try:
        raw = manifest_path(home).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("recipe"):
            out.append(entry)
    return out


def _unit_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry["recipe"]),
        str(entry.get("slot") or DEFAULT_SLOT_NAME),
        str(entry.get("source") or ""),
    )


def _moment(stamp: str) -> datetime | None:
    """A ledger timestamp as a moment, or ``None`` if it cannot be read as one.

    A line whose ``when`` is damaged must not silently become "the beginning of
    time", which would report every file under it as written after the copy and
    bury the real findings under fifty false ones.
    """
    try:
        return datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _newest_write(directory: Path) -> tuple[float, Path] | None:
    """The most recently written file anywhere under here, and which one.

    Naming the file matters as much as the time. "Something still writes here"
    sends a person hunting; "``progress.json`` was written at 09:43" tells them
    which process to go and stop.
    """
    newest: tuple[float, Path] | None = None
    try:
        for path in directory.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    stamp = path.stat().st_mtime
                    if newest is None or stamp > newest[0]:
                        newest = (stamp, path)
            except OSError:
                continue
    except OSError:
        return newest
    return newest


def _path_claims(home: Path, sources: list[tuple[str, str, str]]) -> list[tuple[str, Path]]:
    """Every directory anything on this machine claims, and which recipe claims it.

    Both halves are needed. A slot's *own* invented keys count — ``ledgerPath``
    and friends are how a recipe says "I read this", and a recipe reading inside
    someone else's migrated source is the thing being looked for. And a ledger
    source counts, because a directory two migrations both copied is two copies
    of one thing, which is the original disease.
    """
    claims: list[tuple[str, Path]] = []
    root = home / ".frago" / APP_STATE_DIR.name
    if root.is_dir():
        for recipe_dir in sorted(root.iterdir()):
            if not recipe_dir.is_dir():
                continue
            for slot_file in sorted(recipe_dir.glob("*.json")):
                try:
                    state = json.loads(slot_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(state, dict):
                    continue
                for value in state.values():
                    if isinstance(value, str) and value.startswith("/"):
                        claims.append((recipe_dir.name, Path(value)))
    for recipe, _slot, source in sources:
        if source:
            claims.append((recipe, Path(source)))
    return claims


def _other_claimants(source: Path, recipe: str, claims: list[tuple[str, Path]],
                     home: Path) -> list[str]:
    """Other recipes whose data lives in, or around, this source directory.

    The question is not "is this directory's name on a blocklist" — that is the
    gate's job, before the fact, and a list is only as good as the day somebody
    last added to it. The question here is whether the contents ever served one
    recipe, and the machine can answer that from who else points into the tree.

    ``~/.frago/state`` was filed as one poller's data directory and copied whole,
    carrying a team watcher, another recipe's cursor and a credentials file under
    that poller's name. Nothing about the *name* said so. What said so was that
    another recipe recorded ``~/.frago/state/upwork`` as its own — a claim
    sitting inside the source, which no blocklist would ever have to be updated
    to notice.

    Both directions count. A source with someone else's directory inside it was
    never one recipe's; a source sitting inside a directory someone else copied
    wholesale has had its bytes duplicated a second time, one level up. An
    ancestor that is a whole tree is ignored: "everything is inside
    ``~/.frago/data``" is true and says nothing.
    """
    found = set()
    for other, claimed in claims:
        if other == recipe:
            continue
        try:
            if claimed == source or claimed.is_relative_to(source):
                found.add(f"{other} 认领了源目录里的 {claimed}")
            elif source.is_relative_to(claimed) and not _is_a_root(claimed, home):
                found.add(f"{other} 把包着源目录的 {claimed} 整个认领了")
        except (OSError, ValueError):
            continue
    return sorted(found)


def _page_address(recipe: str, slot: str, home: Path) -> str | None:
    """The directory this recipe's page reads, as its slot records it.

    ``None`` covers two different situations that are both fine here: the slot
    was never published, or it holds no directory at all. Neither one points a
    reader at the old copy, which is the only failure this check is about.
    """
    slot_file = home / ".frago" / APP_STATE_DIR.name / recipe / f"{slot}.json"
    try:
        state = json.loads(slot_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    recorded = state.get(PLATFORM_KEY)
    return recorded if isinstance(recorded, str) and recorded else None


def audit(identity: str, home: Path | None = None, *, now: datetime | None = None) -> Audit:
    """Sort every copy the ledger records into the three stages.

    Reads only, like ``plan``. Copying without deleting was the right call — a
    wrong guess about somebody's own records has to be recoverable — but "both
    copies exist" is a state that has to end, and until this existed the ledger
    could only say a copy was *made*. It had no way to say the old one had
    stopped mattering, so nothing ever did, and three months of copies sat there
    with no way to tell the finished ones from the ones still being written to.

    The three questions, each one a round of hand-comparing timestamps that
    should not have to happen again:

    * Is anything still **writing** to the old copy? Then something never
      switched over, and deleting it loses whatever it wrote.
    * Is anything still **reading** it? The page's slot is the readable form of
      that: a slot recording the old directory means people are looking at the
      old copy while the recipe fills the new one.
    * Did the source ever belong to this recipe at all? See ``_other_claimants``.

    Anything that answers yes to one of those is not finished. Everything else
    has been quiet since a date this prints, and that date is what somebody can
    put an expiry on.
    """
    home = home or Path.home()
    now = now or datetime.now().astimezone()
    ledger = manifest_path(home)
    lines = _ledger_lines(home)
    report = Audit(identity=identity, ledger=ledger,
                   ledger_exists=ledger.is_file(), lines=len(lines))

    copies: dict[tuple[str, str, str], dict[str, Any]] = {}
    seals: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in lines:
        kind = str(entry.get("lifecycle") or LIFECYCLE_COPIED)
        # Last line wins. The file is append-only, so a directory copied twice
        # has two lines and the newer one describes what is on disk.
        (seals if kind == LIFECYCLE_SEALED else copies)[_unit_key(entry)] = entry

    claims = _path_claims(home, list(copies))
    for key, entry in copies.items():
        recipe, slot, raw_source = key
        source = Path(raw_source)
        target = Path(str(entry.get("target") or ""))
        when = str(entry.get("when") or "")
        files = int(entry.get("files") or 0)
        size = int(entry.get("bytes") or 0)
        sealed_line = seals.get(key)
        alive = source.is_dir()

        if sealed_line is not None:
            reasons = [f"账本已记封存：{sealed_line.get('when', '?')}"
                       f"{'，' + str(sealed_line.get('how')) if sealed_line.get('how') else ''}"]
            if alive:
                # Both statements cannot be true. Saying so is the only useful
                # thing to do with them — silently trusting either one is how a
                # ledger stops matching the disk without anybody finding out.
                reasons.append(f"但源目录还在：{source}。账本和磁盘对不上，以磁盘为准去看一眼")
            report.checked.append(Audited(recipe, slot, source, target, when, SEALED,
                                          tuple(reasons), files=files, size=size))
            continue

        if not alive:
            report.checked.append(Audited(
                recipe, slot, source, target, when, SEALED,
                (f"源目录已经不在了：{source}。"
                 f"但账本上没有这一笔封存记录——谁删的、删去哪了，现在没人答得上来，"
                 f"补记一条封存行",),
                files=files, size=size))
            continue

        reasons = []
        newest = _newest_write(source)
        last_write, quiet_days = "", -1
        if newest is not None:
            stamp = datetime.fromtimestamp(newest[0]).astimezone()
            last_write = stamp.isoformat(timespec="seconds")
            quiet_days = max(0, (now - stamp).days)
            # Compared as moments, not as strings: two correct timestamps sort
            # the wrong way as text the moment their offsets differ, and this
            # decides whether a directory is safe to delete.
            #
            # Both sides are cut to whole seconds first, because the ledger
            # records whole seconds. Comparing a file's microseconds against a
            # truncated ledger stamp made every directory look like it had been
            # written to *after* its own migration — the copy is recorded at
            # 09:33:25 and the file it just read is stamped 09:33:25.847 — so a
            # freshly migrated machine reported every single copy as "not cut
            # over yet". A check that fires on everything points at nothing.
            copied_at = _moment(when)
            if copied_at is not None and stamp.replace(microsecond=0) > copied_at:
                reasons.append(
                    f"搬完之后老地方还在被写：{last_write} 写了 {newest[1]}（搬于 {when}）。"
                    f"有东西没切过来，这会儿删掉老的就是删掉它写的那些")

        recorded = _page_address(recipe, slot, home)
        if recorded is not None:
            try:
                proper = recipe_data_dir(
                    identity, recipe, None if slot == DEFAULT_SLOT_NAME else slot)
            except InvalidSlotName:
                proper = None
            if proper is not None and Path(recorded).expanduser() != proper:
                where = "就是这次搬走的那个老地方" if Path(recorded).expanduser() == source \
                    else "既不是新落点也不是老源头"
                reasons.append(
                    f"页面的地址还记着 {recorded}（{where}），平台算出来的是 {proper}。"
                    f"页面读一个、配方写另一个，刷新永远成功，数字永远是旧的")

        shared = _other_claimants(source, recipe, claims, home)
        if shared:
            reasons.append(
                "这个源头不是只服务这一个配方：" + "；".join(shared)
                + "。当初搬的时候把别人的东西一起认领了，删它会删掉别人的")

        report.checked.append(Audited(
            recipe, slot, source, target, when,
            STILL_LIVE if reasons else READY_TO_EXPIRE,
            tuple(reasons), last_write=last_write, quiet_days=quiet_days,
            files=files, size=size))

    report.checked.sort(key=lambda one: (one.recipe, one.slot))
    return report


def seal(
    recipe: str,
    slot: str,
    source: Path,
    target: Path,
    how: str,
    where: str = "",
    note: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    """Write down that an old copy is out of service. Appends; never rewrites.

    This is the end the copies never had. ``apply`` records that a copy was
    made, and that line stays true forever — so the fact that the original later
    stopped being read cannot be expressed by editing it, only by adding a line
    that says so. Anyone reading the ledger months from now gets both: the move
    happened on this date, and this path was closed on that one.

    ``how`` is ``deleted`` or ``archived``, ``where`` is where it went when it
    was archived. Recording the destination is the difference between "it is
    gone" and "it is somewhere, and here is where" — the second is the only one
    a person can act on when it turns out something was still needed.

    Writing this line is not deleting anything. The removal is a separate,
    deliberate act; this only records that it was decided.
    """
    entry = {
        "when": (datetime.now().astimezone()).isoformat(timespec="seconds"),
        "lifecycle": LIFECYCLE_SEALED,
        "recipe": recipe,
        "slot": slot,
        "source": str(source),
        "target": str(target),
        "how": how,
        "where": where,
        "source_kept": False,
        "note": note,
    }
    path = manifest_path(home or Path.home())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry
