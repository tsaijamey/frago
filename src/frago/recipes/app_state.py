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

    ~/.frago/app-state-users/<recipe-name>/<account-id>.json

so that two people opening the same page see their own data. The recipe's own
slots and people's slots are separate directories rather than separate names in
one directory: a recipe can write any slot name at any time without going
through the server, so nothing could keep the two from colliding by convention.

This module deliberately has no server imports: recipes run as their own
processes and should not need to pull in FastAPI to publish a dict.
"""

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

APP_STATE_DIR = Path.home() / ".frago" / "app-state"

# Slots that belong to a signed-in person, not to the recipe. Kept under a root
# of their own so the two can never collide: a recipe may call `publish()` with
# any slot name it likes, at any moment, without asking the server — so
# "check for a clash when the account is created" is a check that cannot hold.
# It would run before the recipe writes, and the two would end up sharing one
# file. Two roots make the collision impossible on disk instead of unlikely.
#
# ``frago.server.identity`` resolves the same root by the same rule (constant,
# ``FRAGO_USER_STATE_DIR`` override) to answer "has this account any data"; it
# cannot import this module's answer without dragging recipes into the server.
USER_STATE_DIR = Path.home() / ".frago" / "app-state-users"

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
    """Root of the per-identity slots. ``FRAGO_USER_STATE_DIR`` overrides."""
    override = os.environ.get("FRAGO_USER_STATE_DIR")
    return Path(override).expanduser() if override else USER_STATE_DIR


def state_root(identity: bool = False) -> Path:
    """Which of the two roots a slot lives under."""
    return user_state_dir() if identity else APP_STATE_DIR


def slot_path(recipe_name: str, slot: str = DEFAULT_SLOT, *, identity: bool = False) -> Path:
    """Where one slot's state lives on disk.

    ``identity=True`` addresses the slot of a signed-in visitor, whose name is
    their account id. The server passes it; a recipe writing its own state does
    not, and therefore cannot reach a person's file even by naming one.
    """
    _validate(recipe_name, slot)
    return state_root(identity) / recipe_name / f"{slot}.json"


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

    Owner-only on disk. Slot state is where a recipe parks the absolute paths it
    is working with, and often a key or an internal identifier alongside them —
    that is the whole reason a published page is served a filtered copy rather
    than this document. On a personal machine the permission bits are moot; on a
    server, where a deploy user, a web user and a CI runner share the box, a
    world-readable copy hands all of it over without going near the HTTP gate.
    The temp file is created 0600 rather than chmod'ed afterwards, so there is no
    moment when it is readable by anyone else.
    """
    path = slot_path(recipe_name, slot, identity=identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
        state_root(identity).chmod(0o700)

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
    """
    _validate(recipe_name, DEFAULT_SLOT)
    directory = state_root(identity) / recipe_name
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
