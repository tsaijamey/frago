"""Which recipe pages are allowed to face the public internet.

``/app/<recipe>/`` has always been a real address, but on a personal machine it
is an address only the owner can reach. On a deployed frago the same route is
the one thing worth exposing — a recipe's page is the finished product, and the
whole point of putting frago on a server is to let other people look at it.

Exposure is per recipe and opt-in. Nothing is public until someone runs

    frago recipe expose <name> [--slot <slot>]

which appends an entry here. The server's access middleware reads this list to
decide whether an anonymous GET may pass; nothing else about a recipe changes.

Publishing one slot does not publish the others. A recipe that keeps a public
dashboard in ``default`` and a client's working set in ``acme`` stays safe.

There are two ways to be exposed, and the entry says which. ``public`` is the
original one: anyone may read the named slot. ``identity`` publishes the address
without publishing any data — the page is reachable only after signing in, and
each visitor reads the slot named after their own account. An entry whose mode
cannot be read is treated as ``identity``, i.e. anonymous visitors are refused;
see ``_mode_of``.

No server imports: recipes and the CLI both read this, and neither should have
to pull in FastAPI to answer "is this page public?".
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName, _validate

PUBLISHED_PATH = Path.home() / ".frago" / "published.json"

# How a page is exposed. Two ways, and the difference is who may read it:
#
#   public     anyone, with no sign-in, from the one slot named in the entry.
#   identity   only a signed-in visitor, each from the slot named after their
#              own account. The whole reason this mode exists is that the page
#              must NOT be readable anonymously.
#
# Which one a request is judged by is the gate's business (`security.py`);
# this module only says what the operator asked for.
MODE_PUBLIC = "public"
MODE_IDENTITY = "identity"
MODES = (MODE_PUBLIC, MODE_IDENTITY)

# ``allow`` narrows an identity-mode page from "anyone signed in" to "these
# accounts". Three states, and telling them apart matters because their security
# meanings are opposite:
#
#   key absent   an entry written before this field existed. Behaves as it did:
#                everyone the mode already admits.
#   None         someone said "all signed-in users" out loud. Same behaviour.
#   [...]        only these accounts.
#   []           nobody. The CLI never writes this — it is where a hand-edited
#                or corrupted entry lands, and landing at "nobody" is the only
#                safe reading of an instruction that can no longer be read.
#
# The list holds account ids, never email addresses. An email here would mean
# "whoever claims this address first is authorised", because nothing in this
# system verifies one — see ``frago book recipe-expose``.

# The published list is consulted on every anonymous request. Re-reading a small
# JSON file each time is wasteful but re-reading it *never* is a footgun: a
# recipe unpublished at 2am has to stop serving at 2am. Cache on mtime+size.
_cache: tuple[tuple[float, int], dict[str, dict[str, Any]]] | None = None


def published_path() -> Path:
    """Where the list lives. ``FRAGO_PUBLISHED_FILE`` overrides, for tests."""
    override = os.environ.get("FRAGO_PUBLISHED_FILE")
    return Path(override).expanduser() if override else PUBLISHED_PATH


def load() -> dict[str, dict[str, Any]]:
    """Every published recipe, keyed by name."""
    global _cache
    path = published_path()
    try:
        stat = path.stat()
    except OSError:
        _cache = None
        return {}

    stamp = (stat.st_mtime, stat.st_size)
    if _cache is not None and _cache[0] == stamp:
        return _cache[1]

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}

    entries = {
        name: entry
        for name, entry in loaded.items()
        if isinstance(name, str) and isinstance(entry, dict)
    }
    _cache = (stamp, entries)
    return entries


def _save(entries: dict[str, dict[str, Any]]) -> None:
    global _cache
    path = published_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    _cache = None


def _mode_of(entry: dict[str, Any]) -> str:
    """Read an entry's mode so that every way of getting it wrong ends up shut.

    Two different failures, two different answers, and the asymmetry is the
    point:

    * **No ``mode`` key at all** is an entry written before this field existed.
      It was published for anonymous readers and must keep serving them, so it
      reads as ``public``.
    * **A ``mode`` nobody recognises** — a typo, a hand-edit, an explicit
      ``null``, a file from a newer frago — reads as ``identity``, i.e.
      anonymous readers are refused. Such an entry has already lost the
      operator's intent, and the only safe reading of an unknown intent is the
      one that shows nobody anything. The previous audit's D-F1 was exactly this
      shape failing the other way.

    Absent and ``null`` are told apart deliberately (``in`` rather than
    ``get``): the first is a version of frago that never had an opinion, the
    second is something that had one and lost it.
    """
    if "mode" not in entry:
        return MODE_PUBLIC
    raw = entry["mode"]
    if isinstance(raw, str) and raw in MODES:
        return raw
    return MODE_IDENTITY


def _allow_of(entry: dict[str, Any]) -> list[str] | None:
    """Which accounts an entry opens to. None means "everyone in this mode".

    Same asymmetry as ``_mode_of``, for the same reason — and here the two
    failure directions are further apart, because this field decides *people*:

    * **No ``allow`` key at all** is an entry written before this field existed.
      Its operator asked for "everyone who can sign in" and never said otherwise,
      so it keeps meaning that: None.
    * **``null``** is that same answer, stated on purpose by a newer CLI.
    * **A list of account ids** is the narrow case: only those accounts.
    * **Anything else** — a string, a number, a list with a dict in it, a list
      with an empty string in it — is an entry that has lost its operator's
      intent. It reads as ``[]``: nobody. NEVER salvage the recognisable
      elements of a broken list; a half-read list is a list whose remaining
      half might have been the restriction that mattered.

    ``[]`` written by hand means the same thing and is preserved as-is. It is
    the safe landing point of a corrupt config, not a state the CLI can produce
    — a page nobody may open is spelled ``frago recipe unexpose``.
    """
    if "allow" not in entry:
        return None
    raw = entry["allow"]
    if raw is None:
        return None
    if isinstance(raw, list) and all(isinstance(x, str) and x for x in raw):
        return list(raw)
    return []


def _runnable_of(entry: dict[str, Any], mode: str) -> bool:
    """Whether visitors may trigger a run. Absent, unreadable, or contradicted
    by the mode all read as False.

    ``runnable`` implies ``mode == identity``: a run happens *for somebody*, and
    a public page has nobody to run as. An entry claiming both — only reachable
    by hand-editing — is the config contradicting itself, and the strict side of
    that contradiction is False.

    ``is True`` rather than truthiness on purpose: ``"false"``, ``1`` and
    ``"no"`` are all truthy, and every one of them is a hand-edit that meant the
    opposite.
    """
    return entry.get("runnable") is True and mode == MODE_IDENTITY


def allows(entry: dict[str, Any] | None, identity: str | None) -> bool:
    """Whether this signed-in account may open this page. The only comparison.

    Every caller asks *here* rather than reading ``allow`` and comparing for
    itself: the gate, the run endpoint and the page listing must agree to the
    letter, and three hand-written comparisons of a four-state field is three
    chances for one of them to read absent-and-empty the same way.

    Mode is part of the judgement, not a separate step the caller may forget.
    A ``public`` entry answers False here — not because such a page is closed,
    but because it is not opened by *identity*; anonymous readability is
    ``classify_public``'s question and is decided elsewhere entirely.

    Accepts a raw or a normalised entry: both ``_mode_of`` and ``_allow_of`` are
    idempotent, so re-reading a normalised copy gives the same answer.
    """
    if not isinstance(entry, dict):
        return False
    if _mode_of(entry) != MODE_IDENTITY:
        return False
    if not isinstance(identity, str) or not identity:
        return False
    allow = _allow_of(entry)
    if allow is None:
        return True
    return identity in allow


def published_entry(name: str) -> dict[str, Any] | None:
    """The whole exposure record for one recipe, or None if it has none.

    Name validation happens here rather than at the call site: this function is
    reached straight from a URL path, so a name like ``../../etc`` must be a
    plain "not published" rather than an exception in the middleware.

    Returns a normalised copy — ``slot`` and ``mode`` are always present and
    always sane — so that no caller has to repeat the defaulting rules and get
    one of them subtly different.
    """
    try:
        _validate(name, DEFAULT_SLOT)
    except InvalidSlotName:
        return None
    entry = load().get(name)
    if not entry:
        return None
    slot = entry.get("slot")
    mode = _mode_of(entry)
    return {
        "slot": slot if isinstance(slot, str) and slot else DEFAULT_SLOT,
        "mode": mode,
        "since": entry.get("since"),
        "allow": _allow_of(entry),
        "runnable": _runnable_of(entry, mode),
    }


def published_slot(name: str) -> str | None:
    """The slot an *anonymous* visitor may read, or None if there is none.

    None for an identity-mode page, which is not a slot lookup failing but the
    answer to the question actually asked: nothing is served to nobody here.
    Callers deciding what a *signed-in* visitor may reach must use
    ``published_entry`` — this function returning None does not mean the page
    is unpublished.
    """
    entry = published_entry(name)
    if entry is None or entry["mode"] != MODE_PUBLIC:
        return None
    return str(entry["slot"])


def is_published(name: str, slot: str = DEFAULT_SLOT) -> bool:
    return published_slot(name) == slot


def publish(
    name: str,
    slot: str = DEFAULT_SLOT,
    mode: str = MODE_PUBLIC,
    *,
    allow: list[str] | None = None,
    runnable: bool = False,
) -> dict[str, Any]:
    """Expose one recipe's page. Returns the entry.

    ``mode=MODE_IDENTITY`` publishes the *address* rather than the data: the
    page is reachable only to someone signed in, and each of them reads the slot
    named after their own account instead of ``slot``.

    ``allow=None`` opens the page to everyone who can sign in; a list narrows it
    to those account ids. An empty list is refused rather than written: it would
    leave an entry no living account can open, and the way to close a page is to
    take it off the list, not to leave a locked one behind for the next reader
    to puzzle over.
    """
    _validate(name, slot)
    if mode not in MODES:
        raise ValueError(f"unknown publish mode {mode!r}; expected one of {MODES}")
    if allow is not None:
        if not isinstance(allow, list) or not all(isinstance(x, str) and x for x in allow):
            raise ValueError("allow must be a list of non-empty account ids, or None")
        if not allow:
            raise ValueError(
                "refusing to publish with an empty allow list: nobody could open the "
                "page. Use `frago recipe unexpose` to close it instead."
            )
        if mode != MODE_IDENTITY:
            raise ValueError("an allow list needs identity mode; there is nobody to compare in public mode")
    if runnable and mode != MODE_IDENTITY:
        raise ValueError("a runnable page needs identity mode; a run happens for somebody")
    entries = load()
    entry = {
        "slot": slot,
        "mode": mode,
        "since": datetime.now().astimezone().isoformat(timespec="seconds"),
        # Written even when they carry the defaults: a reader of this file should
        # see who the page is open to without having to know which frago version
        # wrote the entry.
        "allow": list(allow) if allow is not None else None,
        "runnable": bool(runnable),
    }
    entries[name] = entry
    _save(entries)
    return entry


def unpublish(name: str) -> bool:
    """Take a page back off the public internet. True if it was published."""
    entries = load()
    if name not in entries:
        return False
    del entries[name]
    _save(entries)
    return True


def public_view(state: dict[str, Any]) -> dict[str, Any]:
    """The part of a recipe's slot state an anonymous visitor may see.

    Slot state is written for a page running on the owner's own machine, so it
    routinely carries absolute paths (``dataDir``), and nothing stops a recipe
    from parking an API key in there. Guessing which keys are safe by their
    names is the kind of filter that works until the day it doesn't, so the
    contract is inverted: a recipe declares what is public, and nothing else
    leaves the box.

        publish("my_recipe", {
            "dataDir": "/Users/me/.frago/data/…",   # stays private
            "public": {"title": "Weekly numbers"},  # this is what visitors get
        })

    Files under ``dataDir`` remain readable through ``/app/<name>/data/…`` —
    that is the payload the page exists to show — but the path itself never
    reaches the client, so a visitor cannot learn the layout of the disk.
    """
    public = state.get("public")
    return dict(public) if isinstance(public, dict) else {}
