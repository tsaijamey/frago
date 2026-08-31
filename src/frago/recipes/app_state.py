"""State a recipe publishes for its own web page.

A recipe with a UI needs to hand the page some things it can only know at run
time: which directory holds this run's data, which files to show, which
sub-recipes the page may call. The old way was to write a `config.json` next to
a freshly copied set of assets, which welded the page's address to a single run
and left the copies on disk forever.

Now the recipe publishes that state to a named slot:

    ~/.frago/app-state/<recipe-name>/<slot>.json

and the server serves it at `/app/<recipe-name>/config.json`, adding `apiBase`
and friends on the way out. The page's address stays the same across runs.

Most recipes need exactly one slot and can ignore the argument: running the
recipe again replaces what the page shows, which is what a person expects from
a dashboard. Slots exist for the recipes that genuinely hold several things
open at once — one video project per slot, one blind-test game per slot — and
those pass `?key=<slot>` in the page address.

Since the identity spec there is a second root. A signed-in visitor's slot is
named after their account and lives under

    ~/.frago/users/<account-id>/state/<recipe-name>.json

so that two people opening the same page see their own data. The recipe's own
slots and people's slots are separate directories rather than separate names in
one directory: a recipe can write any slot name at any time without going
through the server, so nothing could keep the two from colliding by convention.

That root is filed by account rather than by recipe because of the shape of the
operational move that actually happens: "delete everything this person has" is
one directory, and "has this account any data" is one stat. The opposite
question — everyone who ever used a given recipe — is a walk across accounts,
and it is a question nobody asks in a hurry. Below the account sits `state/`
for the slots and `data/` for that account's own output, so one person's whole
footprint is one subtree.

This module deliberately has no server imports: recipes run as their own
processes and should not need to pull in FastAPI to publish a dict.
"""

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

from . import context

APP_STATE_DIR = Path.home() / ".frago" / "app-state"

# The root that belongs to signed-in people rather than to recipes. Kept apart
# from the recipe's own so the two can never collide: a recipe may call
# `publish()` with any slot name it likes, at any moment, without asking the
# server — so "check for a clash when the account is created" is a check that
# cannot hold. It would run before the recipe writes, and the two would end up
# sharing one file. Two roots make the collision impossible on disk instead of
# unlikely.
#
# ``frago.server.identity`` resolves the same root by the same rule (constant,
# ``FRAGO_USER_STATE_DIR`` override) to answer "has this account any data"; it
# cannot import this module's answer without dragging recipes into the server.
# The two definitions must therefore move together — pointing them at different
# directories is a bug with no symptom until a visitor reads an empty page.
USER_STATE_DIR = Path.home() / ".frago" / "users"

DEFAULT_SLOT = "default"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidSlotName(ValueError):
    """Raised when a recipe or slot name would escape the state directory."""


def _validate(recipe_name: str, slot: str) -> None:
    for label, value in (("recipe name", recipe_name), ("slot", slot)):
        if not value or not _SAFE_NAME.match(value) or value in {".", ".."}:
            raise InvalidSlotName(
                f"Invalid {label}: {value!r} (letters, digits, dot, dash, underscore only)"
            )


def user_state_dir() -> Path:
    """Root of the per-account subtrees. ``FRAGO_USER_STATE_DIR`` overrides.

    An account root, not a slot root: `state/` and `data/` both hang off
    `<root>/<account-id>/`. The variable keeps its name so that the deployments
    and tests already setting it do not have to be found and changed.
    """
    override = os.environ.get("FRAGO_USER_STATE_DIR")
    return Path(override).expanduser() if override else USER_STATE_DIR


def state_root(identity: bool = False) -> Path:
    """Which of the two roots a slot lives under."""
    return user_state_dir() if identity else APP_STATE_DIR


def user_root(account_id: str) -> Path:
    """Everything one account owns, in one directory."""
    _validate(DEFAULT_SLOT, account_id)
    return user_state_dir() / account_id


def user_data_dir(account_id: str, recipe_name: str) -> Path:
    """Where a recipe's output for one account goes.

    The platform decides this, hands it over as ``FRAGO_RECIPE_DATA_DIR``, and
    republishes it into the account's slot on every write, so a recipe that
    hard-codes a directory of its own can still not get that directory served
    to the visitor.
    """
    _validate(recipe_name, account_id)
    return user_root(account_id) / "data" / recipe_name


#: The one directory name a recipe may not use for its own files. The platform
#: writes the page's note here, inside the directory it describes, so that "which
#: body of work is this note about" is answered by the structure rather than by
#: two indexes agreeing. See ``frago book must-recipe-data``.
STATE_FILE = "state.json"

#: Where a multi-project recipe keeps its projects. Spelled out rather than
#: hung straight off the recipe directory so that a project called ``cache`` or
#: ``share`` cannot collide with the recipe's own cross-project files.
PROJECTS_DIR = "projects"

#: Cross-user data, machine-level, under nobody's tree.
SHARE_DIR = "share"
SEED_DIR = "seed"
COMMON_DIR = "common"

#: The name of the tree under each root. Not "caches": a person's ledger lives
#: here and losing it loses it for good, while anything called a cache reads as
#: safe to delete — to a recipe author and to whoever writes the disk-cleanup job.
RECIPE_DATA = "recipe-data"


def recipe_data_root(identity: str) -> Path:
    """Everything one account's recipes have written, in one directory.

    The same shape on a laptop and on a server, differing only in which id it
    is. A personal install has one of these and its owner never has to know.
    """
    _validate(DEFAULT_SLOT, identity)
    return user_root(identity) / RECIPE_DATA


def recipe_data_dir(identity: str, recipe_name: str, project: str | None = None) -> Path:
    """Where one run's data belongs. The platform decides this, never the recipe.

    ``project`` is for a recipe whose every run is a separate body of work — ten
    videos, ten directories. Leave it out for a recipe that maintains one thing
    forever; running it again updates that thing rather than starting a second.

    Which of the two a recipe is must be declared by the recipe rather than
    inferred: a backtest recipe on this machine has two named bodies of work
    whose directories are the same path, so the platform believes there are two
    and the disk holds one, each overwriting the other without a word.
    """
    _validate(recipe_name, identity)
    base = recipe_data_root(identity) / recipe_name
    if project is None:
        return base
    _validate(recipe_name, project)
    return base / PROJECTS_DIR / project


def recipe_state_path(identity: str, recipe_name: str, project: str | None = None) -> Path:
    """The page's note for one body of work, inside the directory it describes."""
    return recipe_data_dir(identity, recipe_name, project) / STATE_FILE


#: The one directory under a recipe's own machine-level tree that holds nothing
#: of its own: the view, built for this module, of the blocks other modules
#: opened to it. Named here because two rules depend on it — the staging
#: rebuilds it, and a module may not declare it as the block it shares, which
#: would pass its own dependencies on to whoever reads it.
READS_DIR = "reads"


class InvalidShare(ValueError):
    """A ``shares:`` declaration that does not name a bounded block.

    Raised rather than trimmed into something workable. The whole value of the
    declaration is that it is bounded — a machine can hand over a bounded thing
    without a person signing for it — so a declaration whose bounds have to be
    guessed at is not a smaller version of the same statement.
    """


def machine_root(recipe_name: str) -> Path:
    """Everything one recipe keeps outside any account, in one directory."""
    _validate(recipe_name, DEFAULT_SLOT)
    return Path.home() / ".frago" / RECIPE_DATA / recipe_name


def shared_subtree(recipe_name: str, declared: str) -> Path:
    """The directory a recipe's ``shares:`` names, or a refusal.

    ``declared`` is relative to the recipe's own machine-level root, so a
    producer says ``share/common`` and means the block it has always written
    there. Nothing about this walks outside that root, and the three ways of
    trying are refused by name rather than by resolving to something safe:

    * an absolute path, or one climbing out with ``..`` — that is not "part of
      my data", it is somebody else's;
    * the root itself — it contains ``reads/``, the view of what other modules
      opened to *this* one, so sharing the root would quietly pass a producer's
      own dependencies through to everyone reading it;
    * ``reads`` itself, for the same reason said directly.
    """
    root = machine_root(recipe_name)
    raw = (declared or "").strip()
    if not raw:
        raise InvalidShare(
            f"{recipe_name} 没有写 shares，也就没有对外开放任何一块数据。"
        )
    if raw.startswith(("/", "~")) or "\\" in raw:
        raise InvalidShare(
            f"shares 写的是 {raw!r}：它必须是相对本模块数据根的一小块，"
            f"例如 share/common，不是一条绝对路径。"
        )
    parts = [one for one in raw.split("/") if one not in ("", ".")]
    if not parts:
        raise InvalidShare(
            f"{recipe_name} 的 shares 指向自己的数据根。那里面有 {READS_DIR}/——"
            f"别人共享给本模块的东西，转手全给出去了。点名一块，比如 share/common。"
        )
    if ".." in parts:
        raise InvalidShare(f"shares 写的是 {raw!r}：不允许 ..，它会走出本模块的数据。")
    if parts[0] == READS_DIR:
        raise InvalidShare(
            f"{READS_DIR}/ 装的是别人共享给本模块的数据，不是本模块的。"
            f"把它再共享出去，等于替别人做了他没做的决定。"
        )
    for one in parts:
        if not _SAFE_NAME.match(one) or one in {".", ".."}:
            raise InvalidShare(
                f"shares 里的 {one!r} 不是一个目录名（只能是字母、数字、点、横线、下划线）。"
            )
    return root.joinpath(*parts)


def share_root(recipe_name: str) -> Path:
    """One recipe's cross-user data. Machine-level, under nobody's account."""
    _validate(recipe_name, DEFAULT_SLOT)
    return machine_root(recipe_name) / SHARE_DIR


def seed_dir(recipe_name: str) -> Path:
    """Starting data, copied to a person on their first run and theirs from then on.

    Copying is only ever right when the original stops mattering to the copy.
    Anything the original keeps updating must be read in place instead — see
    ``common_dir`` — because a copy of a moving thing is a copy that goes stale
    silently, in as many directions as there are people.
    """
    return share_root(recipe_name) / SEED_DIR


def common_dir(recipe_name: str) -> Path:
    """Data everyone reads and one recipe writes. NEVER copied per person.

    Handed to a recipe as a directory it may read, rather than linked into each
    person's tree: a link says where something is and cannot say who may write
    it, which is the whole of what this directory needs to express.
    """
    return share_root(recipe_name) / COMMON_DIR


def slot_path(recipe_name: str, slot: str = DEFAULT_SLOT, *, identity: bool = False) -> Path:
    """Where one slot's state lives on disk.

    ``identity=True`` addresses the slot of a signed-in visitor, whose name is
    their account id. The server passes it; a recipe writing its own state does
    not, and therefore cannot reach a person's file even by naming one.
    """
    _validate(recipe_name, slot)
    if identity:
        return user_root(slot) / "state" / f"{recipe_name}.json"
    return APP_STATE_DIR / recipe_name / f"{slot}.json"


def publish(
    recipe_name: str,
    state: dict[str, Any],
    slot: str = DEFAULT_SLOT,
    *,
    identity: bool = False,
) -> Path:
    """Publish this run's state to a slot, replacing whatever was there.

    Written to a temporary file and moved into place so a page reloading at the
    wrong moment never sees a half-written file.

    On a visitor run the recipe does not get a say in three of these arguments.
    That is not the same as filling in a default when the recipe passed nothing:
    a default means "the recipe wins if it passes something", which hands the
    key back to the very code the isolation is meant to survive. `dataDir` in
    particular must be replaced rather than filled in — a recipe that hard-codes
    the owner's directory (most of them do; it was the correct thing to write
    before this existed) would otherwise publish that path into a visitor's
    slot, and `/app/<name>/data/…` would then serve the owner's files to that
    visitor, rendering perfectly and silently.

    Owner-only on disk. Slot state is where a recipe parks the absolute paths it
    is working with, and often a key or an internal identifier alongside them —
    that is the whole reason a published page is served a filtered copy rather
    than this document. On a personal machine the permission bits are moot; on a
    server, where a deploy user, a web user and a CI runner share the box, a
    world-readable copy hands all of it over without going near the HTTP gate.
    The temp file is created 0600 rather than chmod'ed afterwards, so there is no
    moment when it is readable by anyone else.
    """
    ctx = context.current()
    if ctx.is_visitor:
        slot = ctx.slot or ""
        identity = True
        state = {**state, "dataDir": str(ctx.data_dir)}

    path = slot_path(recipe_name, slot, identity=identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Three levels, not two. `mkdir(parents=True)` builds the middle one —
    # `users/<account-id>/` — under the umask, i.e. 0755: the files inside are
    # 0600, but a second unix account on the same machine can still list the
    # directory and walk away with every account id on the server. On the
    # recipe's own root the middle level and the root are the same directory,
    # so this chmods it twice and changes nothing.
    for directory in (state_root(identity), path.parent.parent, path.parent):
        with contextlib.suppress(OSError):
            directory.chmod(0o700)

    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(state, ensure_ascii=False))
    tmp.replace(path)
    # Catches slots written by an older frago, which followed the umask.
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return path


def read(recipe_name: str, slot: str = DEFAULT_SLOT, *, identity: bool = False) -> dict[str, Any]:
    """Read a slot's state. A slot that was never published reads as empty.

    Empty is the right answer for an identity that has never used the page:
    the front end renders nothing rather than the server raising.
    """
    path = slot_path(recipe_name, slot, identity=identity)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def list_slots(recipe_name: str, *, identity: bool = False) -> list[str]:
    """Slot names this recipe has published, newest first.

    The two roots are listed separately on purpose: `frago recipe expose` shows
    the owner which of *their* slots the page holds, and a list of account ids
    is neither useful there nor theirs to print.

    The identity side walks every account, because that root is filed by account
    and this is the one question that cuts across it. It is also the question
    nobody asks in a hurry — the trade the layout deliberately makes.
    """
    _validate(recipe_name, DEFAULT_SLOT)
    if identity:
        root = user_state_dir()
        if not root.is_dir():
            return []
        try:
            found = [
                (child.name, child / "state" / f"{recipe_name}.json")
                for child in root.iterdir()
                if child.is_dir()
            ]
        except OSError:
            return []
        live = [(name, path) for name, path in found if path.is_file()]
        live.sort(key=lambda pair: pair[1].stat().st_mtime, reverse=True)
        return [name for name, _ in live]

    directory = APP_STATE_DIR / recipe_name
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files]


def page_url(recipe_name: str, slot: str = DEFAULT_SLOT, port: int = 8093) -> str:
    """The address a person can read, type, and bookmark.

    The default slot needs no query string, so the common case is just
    `http://localhost:8093/app/<recipe-name>`.
    """
    _validate(recipe_name, slot)
    base = f"http://localhost:{port}/app/{recipe_name}"
    return base if slot == DEFAULT_SLOT else f"{base}?key={slot}"
