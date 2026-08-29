"""Which recipes the owner has allowed to read which other recipes' shared data.

A recipe that reads another recipe's directory is a dependency nobody wrote
down: the recipe holding the data has no idea anyone is reading it, so it moves
its own files and breaks a page it has never heard of. ``reads_common`` in
``recipe.md`` fixed half of that — the dependency is at least stated — but only
half, because the statement is made by the side that benefits from it. A recipe
declaring "I read the ledger" and then being handed the ledger is a recipe
authorising itself, which is fine on a laptop with one author and meaningless
the moment recipes come from anywhere else.

So the declaration stays a *request* and the grant lives here, on the owner's
side:

    frago recipe grant <consumer> --read <producer>
    frago recipe grants

A run is handed only what it both **declared** and **was granted**. Declaring
without a grant gets nothing (and ``frago recipe validate`` says so); granting
without a declaration gets nothing either, because the dependency still has to
be visible to the person reading the consumer's own metadata.

Machine-level, like the shared data it governs: the directories under
``~/.frago/recipe-data/<producer>/share/`` belong to no account, are written by
exactly one recipe and read by everyone. Who may read them is therefore one
answer per machine, not one per person.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

GRANTS_PATH = Path.home() / ".frago" / "recipe-grants.json"


def grants_path() -> Path:
    """Where the grants live. ``FRAGO_RECIPE_GRANTS_FILE`` overrides, for tests."""
    override = os.environ.get("FRAGO_RECIPE_GRANTS_FILE")
    return Path(override).expanduser() if override else GRANTS_PATH


def load() -> dict[str, dict[str, Any]]:
    """Every grant, keyed by the recipe doing the reading.

    An unreadable file reads as no grants at all. That is the closed direction:
    a damaged registry hands nothing over, and a recipe that finds nothing is a
    recipe whose page says it has no data — loud, and fixable. The other
    direction would be a damaged file that grants everything.
    """
    path = grants_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        name: entry
        for name, entry in loaded.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }


def _save(entries: dict[str, dict[str, Any]]) -> None:
    path = grants_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def granted_to(consumer: str) -> list[str]:
    """The producers this recipe has been allowed to read, in the order granted."""
    entry = load().get(consumer) or {}
    raw = entry.get("read")
    if not isinstance(raw, list):
        return []
    return [one for one in raw if isinstance(one, str) and one]


def grant(consumer: str, producer: str) -> list[str]:
    """Allow one recipe to read another's shared data. Returns the new list."""
    if consumer == producer:
        raise ValueError(
            f"'{consumer}' does not need a grant to read its own data — the "
            f"platform hands a recipe its own directory on every run."
        )
    entries = load()
    entry = entries.setdefault(consumer, {})
    current = [one for one in (entry.get("read") or []) if isinstance(one, str)]
    if producer not in current:
        current.append(producer)
    entry["read"] = current
    entry["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _save(entries)
    return current


def revoke(consumer: str, producer: str) -> list[str]:
    """Take one grant back. Returns what is left."""
    entries = load()
    entry = entries.get(consumer)
    if not entry:
        return []
    current = [one for one in (entry.get("read") or [])
               if isinstance(one, str) and one != producer]
    if current:
        entry["read"] = current
        entry["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    else:
        # An empty grant record and no record at all mean the same thing, and
        # keeping the empty one only gives a later reader something to wonder
        # about.
        entries.pop(consumer, None)
    _save(entries)
    return current


def readable_producers(consumer: str, declared: list[str]) -> list[str]:
    """What a run of ``consumer`` may actually reach: declared **and** granted.

    Both halves are load-bearing and they fail in opposite directions, which is
    why neither is enough on its own. A declaration without a grant is a recipe
    helping itself. A grant without a declaration is a door the owner opened
    onto a recipe that never said it wanted one — nothing would break, but the
    dependency would exist without appearing in the metadata anybody reads.
    """
    allowed = set(granted_to(consumer))
    return [one for one in declared if one in allowed]
