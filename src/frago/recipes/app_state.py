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

This module deliberately has no server imports: recipes run as their own
processes and should not need to pull in FastAPI to publish a dict.
"""

import json
import re
from pathlib import Path
from typing import Any

APP_STATE_DIR = Path.home() / ".frago" / "app-state"

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


def slot_path(recipe_name: str, slot: str = DEFAULT_SLOT) -> Path:
    """Where one slot's state lives on disk."""
    _validate(recipe_name, slot)
    return APP_STATE_DIR / recipe_name / f"{slot}.json"


def publish(recipe_name: str, state: dict[str, Any], slot: str = DEFAULT_SLOT) -> Path:
    """Publish this run's state to a slot, replacing whatever was there.

    Written to a temporary file and moved into place so a page reloading at the
    wrong moment never sees a half-written file.
    """
    path = slot_path(recipe_name, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def read(recipe_name: str, slot: str = DEFAULT_SLOT) -> dict[str, Any]:
    """Read a slot's state. A slot that was never published reads as empty."""
    path = slot_path(recipe_name, slot)
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def list_slots(recipe_name: str) -> list[str]:
    """Slot names this recipe has published, newest first."""
    _validate(recipe_name, DEFAULT_SLOT)
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
