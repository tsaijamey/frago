"""What activating a profile overwrote in an agent CLI's own config.

Activating a profile means writing it into a target CLI's persistent config,
and that necessarily overwrites whatever the person had chosen there. opencode
is the clear case: its ``model`` key points at one of their own providers until
frago repoints it. Deactivating by only deleting frago's own additions would
leave them with a config that names no model at all — worse off than before
they ever activated. So the overwritten values are copied here first and put
back on the way out.

A target is recorded only the **first** time frago takes it over. On a second
activation (switching to a different profile) the "previous" value on disk is
already frago's own, and recording it again would lose the real original for
good.

The store is a small JSON file, keyed by agent type::

    {"opencode": {"model": "deepseek/deepseek-v4-flash", "small_model": null}}
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

BACKUP_PATH = Path.home() / ".frago" / "profile-target-backup.json"


def _load() -> dict[str, Any]:
    """Read the store; a missing or unreadable file is an empty one.

    A corrupted backup must not block activation — the worst case is that a
    later deactivation cannot restore a previous model, which is a smaller
    problem than being unable to switch profiles at all.
    """
    try:
        data = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to read %s: %s. Treating as empty.", BACKUP_PATH, e)
        return {}
    return data if isinstance(data, dict) else {}


def _save(doc: dict[str, Any]) -> None:
    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not doc:
        BACKUP_PATH.unlink(missing_ok=True)
        return
    BACKUP_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def remember(target: str, values: dict[str, Any]) -> None:
    """Record what this target looked like before frago took it over.

    Does nothing if the target already has an entry — see the module docstring
    for why re-recording would destroy the real original.
    """
    doc = _load()
    if target in doc:
        return
    doc[target] = values
    _save(doc)


def take(target: str) -> Optional[dict[str, Any]]:
    """Pop this target's recorded values, or None if nothing was recorded."""
    doc = _load()
    values = doc.pop(target, None)
    if values is not None:
        _save(doc)
    return values if isinstance(values, dict) else None


def has(target: str) -> bool:
    """Whether frago currently holds a pre-takeover snapshot for this target."""
    return target in _load()
