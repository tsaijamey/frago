"""What the platform tells a recipe about the run it is starting.

On a personal machine a recipe may assume it is the only user of the box: it
picks its own data directory, publishes to its own slot, and is right every
time. On a server that assumption is wrong without saying so — two people run
the same recipe, both write the same directory, and the numbers are mixed by
the time anyone notices. The fault is not in any one line of any one recipe:
nothing ever told it who this run is for, so it could only assume.

So the platform stops leaving it to the recipe and says three things when it
starts one:

    FRAGO_RECIPE_CALLER     "owner" | "visitor"
    FRAGO_RECIPE_SLOT       the account id, on a visitor run
    FRAGO_RECIPE_DATA_DIR   where that visitor's output goes

Environment variables rather than a base class, a registration handshake or a
changed signature, because a recipe has three runtimes (python / shell /
chrome-js) and the environment is the only entrance all three share. They are
also ignorable, which is the property that matters most: a recipe that never
reads them behaves exactly as it did before this module existed.

**This module is the platform side.** The runner, the CLI and the server import
it. A recipe must not, and no document should suggest it: whether `import
frago` works at all depends on whether the recipe carries a PEP 723 block, and
most of them do — `uv run` then builds an isolated environment holding only the
dependencies that recipe declared, where `import frago` is an ImportError. A
recipe that wants its directory writes one line and imports nothing:

    data_dir = os.environ.get("FRAGO_RECIPE_DATA_DIR") or <its own old default>

which costs it neither its PEP 723 block nor a dependency. `frago recipe
publish` is a command rather than a function for the same reason.

An owner run deliberately carries no data directory at all — the variable is
not set, so the `or` above lands on the recipe's own default. `must-data-dir`
files output by subject (client, product, domain) and that convention is right;
the platform has no better answer for the owner's own machine and should not
pretend it has one. Only a visitor run gives it both the right and the duty to
decide.
"""

import json
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CALLER_ENV = "FRAGO_RECIPE_CALLER"
SLOT_ENV = "FRAGO_RECIPE_SLOT"
DATA_DIR_ENV = "FRAGO_RECIPE_DATA_DIR"

#: Where this recipe's cross-user data may be read from. Read-only by contract:
#: everyone reads the same copy and exactly one recipe updates it, which is a
#: rule about permission and cannot be expressed by putting the directory
#: somewhere — a link says where a thing is and never who may write it.
COMMON_DIR_ENV = "FRAGO_RECIPE_COMMON_DIR"

#: Where the hub is listening. Everything a recipe does that leaves its own
#: boundary goes there, so this is not one convenience among several — a recipe
#: that cannot reach it cannot ask another module for data, cannot publish a
#: page, and cannot say how far along it is. Kept here beside the other three
#: because they are one contract: what this run is, where it writes, and how it
#: talks to the rest of the system.
BUS_ENV = "FRAGO_BUS_URL"

#: The keys, as one thing — but note that writing and clearing are not
#: symmetric. **Clearing is total**: every key here goes, because a half-cleared
#: context is a visitor slot paired with an owner's directory, which is exactly
#: the mix-up this module exists to prevent. **Writing is not**: the first three
#: are always written together (a run without all three has no isolation), while
#: the shared directory is written only for a recipe that has one — most do not,
#: and an empty variable is a different claim from an absent one.
CONTEXT_ENV_KEYS = (CALLER_ENV, SLOT_ENV, DATA_DIR_ENV, COMMON_DIR_ENV)

OWNER = "owner"
VISITOR = "visitor"

#: The owner's own slot name under ``~/.frago/users/``. A visitor slot is an
#: account id (32 hex characters), so this word cannot collide with one, and
#: using the same root for both keeps "where does this run write" a single rule
#: instead of two that have to be remembered apart.
OWNER_SLOT = OWNER


#: Where this machine records whose runs these are. One line of JSON, written
#: once, never again.
IDENTITY_PATH = Path.home() / ".frago" / "identity.json"

#: An account id is 32 lowercase hex characters, whether it was derived from an
#: email on a server or minted here. One shape everywhere is the point: code
#: that assumes "an id looks like this" must not be right on one machine and
#: wrong on another.
_ID_SHAPE = re.compile(r"^[0-9a-f]{32}$")


class NoIdentity(RuntimeError):
    """This machine cannot say whose run this is.

    Raised rather than resolved. The tempting default — mint a fresh id and
    carry on — is the same mistake in a new costume: the run would succeed, its
    output would land under an id nobody has seen before, and the data the
    person expected to find would still be sitting under the old one. A run
    that cannot name its owner is a run that must not start.
    """


def identity_path() -> Path:
    """Where the record lives. ``FRAGO_IDENTITY_FILE`` overrides, for tests."""
    override = os.environ.get("FRAGO_IDENTITY_FILE")
    return Path(override).expanduser() if override else IDENTITY_PATH


def default_identity(*, create: bool = True) -> str:
    """Whose runs this machine's own runs are.

    A personal install has exactly one person and should never be asked to
    think about accounts, so the record is written silently the first time
    anything needs it. From then on it is read, never rewritten.

    **Absent and unreadable are told apart on purpose.** Absent is a fresh
    install and mints an id. Unreadable — truncated, hand-edited, an id that is
    not an id — raises. Minting a replacement there would orphan everything
    written under the previous one while looking like a clean start.

    The id is minted at random rather than derived from the OS login name.
    Login names get renamed, collide across machines, and carry characters the
    slot validator refuses; an id that changes is an id that loses its data.
    The login name is recorded beside it as a label for a human reading the
    file, and nothing reads it back.
    """
    path = identity_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if not create:
            raise NoIdentity(
                f"this machine has no identity yet ({path}) and this caller asked "
                f"not to create one"
            ) from None
        return _mint(path)
    except OSError as err:
        raise NoIdentity(f"cannot read this machine's identity ({path}): {err}") from err

    try:
        record = json.loads(raw)
        who = record["id"]
    except (json.JSONDecodeError, TypeError, KeyError) as err:
        raise NoIdentity(
            f"this machine's identity file is unreadable ({path}): {err}. "
            f"Repair it rather than deleting it — everything written under the "
            f"id it held is filed by that id."
        ) from err

    if not isinstance(who, str) or not _ID_SHAPE.match(who):
        raise NoIdentity(
            f"this machine's identity file holds {who!r}, which is not an account "
            f"id ({path}). Repair it rather than deleting it."
        )
    return who


def _mint(path: Path) -> str:
    """Write a first identity for this machine and return it.

    Written with O_EXCL so two processes racing on a fresh install cannot each
    believe they created it: the loser reads the winner's file instead of
    overwriting it with a second id.
    """
    who = secrets.token_hex(16)
    record = {
        "id": who,
        # For a person opening this file, not for code. Nothing reads it back.
        "label": os.environ.get("USER") or os.environ.get("USERNAME") or "",
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return default_identity(create=False)
    except OSError as err:
        raise NoIdentity(f"cannot write this machine's identity ({path}): {err}") from err
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    return who


class InvalidInvocationContext(ValueError):
    """The three variables do not describe a run anyone should start.

    Raised rather than resolved to a default. A context that cannot be read is
    a context that cannot be honoured, and the only harmless-looking default —
    "treat it as the owner" — is the one that turns a typo into a silent loss
    of isolation.
    """


@dataclass(frozen=True)
class InvocationContext:
    """Who this run is for, and where its output belongs.

    ``slot`` and ``data_dir`` are only ever populated for a visitor. An owner
    run has neither: the owner's slot is whatever the recipe names, and the
    owner's directory is whatever the recipe has always used.
    """

    caller: str
    slot: str | None = None
    data_dir: Path | None = None
    common_dir: Path | None = None

    @property
    def is_visitor(self) -> bool:
        return self.caller == VISITOR


OWNER_CONTEXT = InvocationContext(caller=OWNER)


def _read(env: Mapping[str, str], key: str) -> str:
    return (env.get(key) or "").strip()


def current(env: Mapping[str, str] | None = None) -> InvocationContext:
    """Read the context this process was started with.

    Nothing set is the owner, because that is every run that predates this
    module and every run a person starts by hand. Anything else set wrong is an
    error: an unrecognised caller, a visitor without a slot, a visitor without a
    directory. Falling back to the owner in those cases would mean a misspelled
    variable name quietly turns a visitor's run into one that writes the
    owner's data — the failure would be silent, and the wrong data would look
    exactly like the right data.
    """
    env = os.environ if env is None else env
    caller = _read(env, CALLER_ENV).casefold()

    if not caller or caller == OWNER:
        # An owner run used to carry nothing at all, and that emptiness is what
        # forced every recipe to invent a directory of its own. It may now carry
        # the same three answers a visitor's does; nothing set still reads as the
        # bare owner, so a recipe started by hand behaves as it always has.
        slot = _read(env, SLOT_ENV)
        raw_dir = _read(env, DATA_DIR_ENV)
        raw_common = _read(env, COMMON_DIR_ENV)
        if not slot and not raw_dir and not raw_common:
            return OWNER_CONTEXT
        return InvocationContext(
            caller=OWNER,
            slot=slot or None,
            data_dir=Path(raw_dir).expanduser() if raw_dir else None,
            common_dir=Path(raw_common).expanduser() if raw_common else None,
        )
    if caller != VISITOR:
        raise InvalidInvocationContext(
            f"{CALLER_ENV}={caller!r} is not a caller this frago knows "
            f"(expected {OWNER!r} or {VISITOR!r})"
        )

    slot = _read(env, SLOT_ENV)
    if not slot:
        raise InvalidInvocationContext(
            f"{CALLER_ENV}={VISITOR} but {SLOT_ENV} is empty: there is no account to "
            f"write for, and the default slot belongs to the recipe, not to a visitor"
        )
    raw_dir = _read(env, DATA_DIR_ENV)
    if not raw_dir:
        raise InvalidInvocationContext(
            f"{CALLER_ENV}={VISITOR} but {DATA_DIR_ENV} is empty: a visitor run with "
            f"nowhere of its own to write would write wherever the recipe pleases"
        )
    raw_common = _read(env, COMMON_DIR_ENV)
    return InvocationContext(
        caller=VISITOR,
        slot=slot,
        data_dir=Path(raw_dir).expanduser(),
        common_dir=Path(raw_common).expanduser() if raw_common else None,
    )


def common_dirs_for(recipe_name: str) -> Path | None:
    """The directory a run may read other recipes' shared data from.

    Handed over as one root that the recipe joins a producer's name onto — the
    shape recipes already use — but the root is **built for this recipe** rather
    than being the tree itself. It holds one entry per producer the owner
    granted, and nothing else, so a recipe joining a name it was not granted
    finds no directory there.

    That indirection is the correction. The root used to be
    ``~/.frago/recipe-data/`` outright, handed over whenever the recipe declared
    *any* producer — so the declaration bought the whole tree, and a recipe that
    named one producer could read every one of them. A declaration is a request;
    the grant is the owner's, and it lives in ``frago.recipes.grants``.

    None when nothing is both declared and granted, which is almost every
    recipe. An empty variable and an absent one are different claims, and a
    recipe with nothing to read should not be handed a door at all.
    """
    from frago.recipes.exceptions import RecipeNotFoundError
    from frago.recipes.grants import readable_producers
    from frago.recipes.registry import get_registry

    try:
        recipe = get_registry().find(recipe_name)
    except (RecipeNotFoundError, OSError):
        return None
    declared = getattr(recipe.metadata, "reads_common", None) or []
    if not declared:
        return None
    allowed = readable_producers(recipe_name, list(declared))
    staged = _stage_common_dirs(recipe_name, allowed)
    # Built even when the answer is "nothing", because that is what a revocation
    # looks like: the grant is gone, and the link left behind from the last run
    # would otherwise keep the door open for as long as the directory survives.
    # Rebuilding first and refusing second is the difference between a revocation
    # and a note about one.
    return staged if allowed else None


def _stage_common_dirs(recipe_name: str, producers: list[str]) -> Path | None:
    """Build this recipe's view of the shared tree: one link per granted producer.

    Rebuilt from scratch each time rather than patched, because the interesting
    change is a *revocation* — and a patch that only adds is a revocation that
    never takes effect. Anything in here that is not on the current list goes,
    including a name that is no longer a recipe.

    Links rather than copies, for the reason ``app_state.common_dir`` gives:
    everyone reads the same copy and exactly one recipe updates it, so a copy
    would go stale silently in as many directions as there are readers.

    Returns None if the directory cannot be built. A run that would otherwise
    start with a half-built view is a run that reads some of its dependencies
    and silently skips the rest.
    """
    from frago.recipes.app_state import RECIPE_DATA, _validate

    root = Path.home() / ".frago" / RECIPE_DATA
    staged = root / recipe_name / "granted"
    try:
        staged.mkdir(parents=True, exist_ok=True)
        wanted = set()
        for producer in producers:
            try:
                _validate(producer, "default")
            except Exception:
                continue
            wanted.add(producer)
            link = staged / producer
            target = root / producer
            if link.is_symlink():
                if link.readlink() == target:
                    continue
                link.unlink()
            elif link.exists():
                # Something that is not a link of ours. Never removed: it may be
                # a real directory somebody put there, and deleting data is not
                # this function's business.
                continue
            link.symlink_to(target, target_is_directory=True)
        for existing in staged.iterdir():
            if existing.name not in wanted and existing.is_symlink():
                existing.unlink()
    except OSError:
        return None
    return staged


def for_owner(recipe_name: str, project: str | None = None) -> InvocationContext:
    """The context an owner run gets: whose it is, and where it writes.

    The directory is withheld in exactly one case: this recipe's records are
    still sitting under an old path that nothing has copied. Handing it over
    then would point the recipe at an empty directory while everything it has
    ever written is elsewhere — a recipe that starts fresh without saying so,
    which is the same silence this work exists to remove.

    Every other recipe gets its directory, **including one that has never had
    any data at all**. That distinction is the whole correction here: the test
    used to be "has anything of this recipe's ever been copied", answered from
    the migration manifest, and a recipe with nothing to migrate can never
    appear in a manifest. It was therefore told forever that the platform had
    not said where to write — which was fine while every recipe still carried a
    default of its own, and became a recipe that cannot start the moment they
    stopped. See ``data_left_behind``.

    A machine that cannot say who it is raises rather than guessing. See
    ``default_identity``.
    """
    from frago.recipes.app_state import DEFAULT_SLOT, recipe_data_dir
    from frago.recipes.data_migration import data_left_behind

    who = default_identity()
    behind = data_left_behind(recipe_name, who, project or DEFAULT_SLOT)
    return InvocationContext(
        caller=OWNER,
        slot=who,
        data_dir=recipe_data_dir(who, recipe_name, project) if behind is None else None,
        common_dir=common_dirs_for(recipe_name),
    )


def for_visitor(recipe_name: str, identity: str) -> InvocationContext:
    """The context a signed-in visitor's run gets — whichever door they came in.

    **One function, because reads and writes have to land on the same
    directory.** They did not. A page's write went through the run route, which
    built a visitor context here; a page's read went through the exported
    read-only mode, which built no context at all and therefore ran as the
    machine. On the server 2026-08-26 that meant the trade ledger was written
    into the signed-in account's directory and read out of the machine's: the
    account's own book stopped at 46 entries while every page on the site
    rendered a different book of 48, and nothing anywhere reported a problem.
    Two call sites deciding "where does this person's data live" is the shape
    that produced it, so there is now one.

    The spot is whatever this account's slot already records, and otherwise the
    same directory a visitor's run has always been given. Deliberately not the
    newer per-account layout the owner's runs moved to: this function exists to
    make two doors agree, and moving everybody's files while doing it would be
    a migration nobody asked for, riding along inside a bug fix. Visitor data
    still living under the older path is a real thing to settle, and it is a
    separate piece of work with its own before-and-after.

    A recorded path outside this account's own root is refused rather than
    honoured: the landing spot decides what the run may write, so a value that
    walked out of the account's tree is the one thing it must never be.
    """
    from frago.recipes.app_state import read as read_slot
    from frago.recipes.app_state import user_data_dir, user_root

    fallback = user_data_dir(identity, recipe_name)
    recorded = ""
    try:
        state = read_slot(recipe_name, identity, identity=True) or {}
        recorded = str(state.get("dataDir") or "").strip()
    except Exception:
        recorded = ""

    spot = fallback
    if recorded:
        try:
            candidate = Path(recorded).expanduser().resolve()
            if candidate.is_relative_to(user_root(identity).resolve()):
                spot = candidate
        except (OSError, ValueError):
            spot = fallback

    return InvocationContext(
        caller=VISITOR,
        slot=identity,
        data_dir=spot,
        # Shared data is machine-level and read-only, so a visitor's run gets
        # the same door the owner's does — it is the one thing here that is not
        # per person. Which producers this recipe may read is its own declaration.
        common_dir=common_dirs_for(recipe_name),
    )


def is_visitor(env: Mapping[str, str] | None = None) -> bool:
    """Whether this process is running on someone else's behalf."""
    return current(env).is_visitor


def data_dir(fallback: str | Path, env: Mapping[str, str] | None = None) -> Path:
    """The directory this run should write, or ``fallback`` on an owner run.

    Platform-side, like everything else here. A recipe reads the variable
    itself in one line (see the module docstring) rather than importing this,
    because most recipes cannot import frago at all.
    """
    ctx = current(env)
    return ctx.data_dir if ctx.data_dir is not None else Path(fallback).expanduser()


def working_dir(recipe_name: str, ctx: InvocationContext | None = None) -> Path:
    """Where this run should stand while it works.

    Every run gets one, owner runs included, and the platform creates it before
    the process starts. That is the whole point: a recipe that writes
    ``open("ledger.json", "w")`` lands somewhere correct on any machine without
    reading a variable, knowing whose run this is, or asking whether it is on a
    server. There is nothing to remember and therefore nothing to misspell —
    which matters more than it sounds, because the previous shape (read this
    variable, fall back to your own default) fails *silently* when the name is
    typed wrong: the recipe keeps working on its author's machine and writes the
    wrong place everywhere else.

    A visitor stands in the directory the platform already computed for that
    account. An owner stands in their own slot under the same root, so the two
    are one rule rather than two.

    **This is not the same as the data-directory variable.** An owner run still
    carries no ``FRAGO_RECIPE_DATA_DIR``: recipes that read it have their own
    default behind it, and setting it here would quietly relocate output that
    has been landing in the same place for months. Changing where a process
    stands moves only the recipes that never named a place at all.
    """
    if ctx is not None and ctx.data_dir is not None:
        return ctx.data_dir
    return Path.home() / ".frago" / "users" / OWNER_SLOT / "data" / recipe_name


def prepare_working_dir(recipe_name: str, ctx: InvocationContext | None = None) -> Path:
    """``working_dir`` with the directory made, ready to be a process's cwd.

    Creating it here rather than leaving it to the recipe is deliberate: a
    recipe that has to create its own directory before writing is a recipe with
    one more chance to create a different one.
    """
    target = working_dir(recipe_name, ctx)
    target.mkdir(parents=True, exist_ok=True)
    return target


def apply_to_env(env: dict[str, str], ctx: InvocationContext | None = None) -> None:
    """Stamp a context onto an environment about to start a recipe.

    Two rules, both of which have a specific accident behind them:

    Overwrite, never "set only if absent". The nearby ``FRAGO_CURRENT_RUN``
    injection is written the second way on purpose — it defers to whatever an
    outer agent already chose. Copying that shape here would mean one line of
    ``FRAGO_RECIPE_CALLER=visitor`` in ``~/.frago/.env`` outranks the platform,
    and the isolation is off with nothing to show for it.

    An owner run *deletes* the three keys rather than declining to write them.
    The environment handed to a recipe starts life as ``dict(os.environ)``, so a
    server process that inherited these variables — or a ``.env`` that sets
    them — passes them straight through to every recipe it starts. "We did not
    write it" is not the same as "it is not there".
    """
    if ctx is None or (not ctx.is_visitor and not ctx.slot):
        for key in CONTEXT_ENV_KEYS:
            env.pop(key, None)
        return

    if not ctx.is_visitor:
        # An owner run that knows whose it is. Written rather than left blank so
        # that the recipe has nowhere left to fall back to — the fallback is the
        # entrance every one of these accidents came through.
        for key in CONTEXT_ENV_KEYS:
            env.pop(key, None)
        env[CALLER_ENV] = OWNER
        env[SLOT_ENV] = ctx.slot
        if ctx.data_dir is not None:
            env[DATA_DIR_ENV] = str(ctx.data_dir)
        if ctx.common_dir is not None:
            env[COMMON_DIR_ENV] = str(ctx.common_dir)
        return

    # A visitor context that reached here without a slot or a directory would
    # write the recipe's own slot, which is the owner's page.
    if not ctx.slot or ctx.data_dir is None:
        raise InvalidInvocationContext(
            "a visitor context needs both a slot and a data directory before a "
            "recipe can be started with it"
        )
    env[CALLER_ENV] = VISITOR
    env[SLOT_ENV] = ctx.slot
    env[DATA_DIR_ENV] = str(ctx.data_dir)
    if ctx.common_dir is not None:
        env[COMMON_DIR_ENV] = str(ctx.common_dir)
