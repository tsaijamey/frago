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

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CALLER_ENV = "FRAGO_RECIPE_CALLER"
SLOT_ENV = "FRAGO_RECIPE_SLOT"
DATA_DIR_ENV = "FRAGO_RECIPE_DATA_DIR"

#: The three keys, as one thing. Anything that writes the context writes all of
#: them and anything that clears it clears all of them: a half-applied context
#: is a visitor slot with an owner's directory, which is exactly the mix-up this
#: module exists to prevent.
CONTEXT_ENV_KEYS = (CALLER_ENV, SLOT_ENV, DATA_DIR_ENV)

OWNER = "owner"
VISITOR = "visitor"

#: The owner's own slot name under ``~/.frago/users/``. A visitor slot is an
#: account id (32 hex characters), so this word cannot collide with one, and
#: using the same root for both keeps "where does this run write" a single rule
#: instead of two that have to be remembered apart.
OWNER_SLOT = OWNER


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
        return OWNER_CONTEXT
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
    return InvocationContext(caller=VISITOR, slot=slot, data_dir=Path(raw_dir).expanduser())


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
    if ctx is None or not ctx.is_visitor:
        for key in CONTEXT_ENV_KEYS:
            env.pop(key, None)
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
