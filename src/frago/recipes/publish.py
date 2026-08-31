"""Which recipe pages are reachable by someone other than the owner, and on what terms.

``/app/<recipe>/`` has always been a real address, but on a personal machine it
is an address only the owner can reach. On a deployed frago the same route is
the one thing worth exposing — a recipe's page is the finished product, and the
whole point of putting frago on a server is to let other people look at it.

Exposure is per recipe and opt-in. Nothing is reachable until someone runs

    frago recipe expose <name> --public | --signed-in | --allow <id>

which writes an entry here. The server's access middleware reads this list to
decide who may pass; nothing else about a recipe changes.

**Two independent questions, and keeping them apart is the point of this file.**

    who may open it        mode + allow    the audience
    whose data they read   reads           the source

They used to be one. ``identity`` meant both "sign in first" and "you read a
slot named after yourself", so the most ordinary request there is — *a few named
people looking at the same numbers I computed* — had no spelling at all. People
reached for machine-level shared data (which is a data-layer mechanism, for a
different problem) or gave up and made the page public. ``reads`` is that missing
third rung: ``own`` is the old per-person behaviour, ``owner`` serves everyone on
the list the same slot of the owner's, read-only.

**What a page may do is not stored here at all.** There used to be a ``runnable``
flag beside the allow list, which said that whoever could see the page could also
push its buttons — and those buttons run on the owner's machine with the owner's
credentials. Visibility and capability are two different facts about two
different things: who is looking, and what the recipe agreed a page may ask for.
So capability moved onto the recipe's own methods (``@action`` on the mode
that may be pressed) and this file no longer has an opinion. A legacy entry's
``runnable`` key is read only to be reported, never to grant anything.

Publishing one slot does not publish the others. A recipe that keeps a public
dashboard in ``default`` and a client's working set in ``acme`` stays safe.

No server imports: recipes and the CLI both read this, and neither should have
to pull in FastAPI to answer "who may open this page?".
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.recipes.app_state import DEFAULT_SLOT, InvalidSlotName, _validate

PUBLISHED_PATH = Path.home() / ".frago" / "published.json"

# Who may open the page. Two answers, and the difference is whether signing in
# is required at all:
#
#   public     anyone, with no sign-in.
#   identity   only a signed-in account, narrowed further by ``allow``.
#
# Which one a request is judged by is the gate's business (`security.py`);
# this module only says what the operator asked for.
MODE_PUBLIC = "public"
MODE_IDENTITY = "identity"
MODES = (MODE_PUBLIC, MODE_IDENTITY)

# Which of the two state roots the page is served from. Orthogonal to the mode —
# that says who is let in, this says where what they read comes from. The roots
# are the ones ``app_state`` has always had, and they are physically separate:
#
#   own      ~/.frago/users/<account-id>/state/<recipe>.json — the reader's own,
#            one per account, and their runs write their own directory. The
#            original identity behaviour and still its default.
#   recipe   ~/.frago/app-state/<recipe>/<slot>.json — the recipe's own, with no
#            account anywhere in the path. Everybody let in reads that one copy.
#            Read-only by construction: nobody has a directory of their own here,
#            so a page exposed this way accepts no actions.
#
# Named after the root rather than after a person on purpose. The first version
# of this called the second one ``owner``, which was wrong three times over: the
# word already means something else in this system (a request origin — ``local``
# or a token, never an account), the slot it names is filed under no account at
# all, and it invites the next reader to go looking for who the owner is when the
# answer is that there isn't one.
#
# A public page is always ``recipe`` — an anonymous reader has no account and so
# no copy of their own.
READS_OWN = "own"
READS_RECIPE = "recipe"
READS = (READS_OWN, READS_RECIPE)

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


def _reads_of(entry: dict[str, Any], mode: str) -> str:
    """Whose data this page serves.

    A public page always comes from the recipe's own root: an anonymous reader
    has no account, so the question does not arise and the answer cannot be
    anything else.

    For an identity page, an absent key is an entry written before this field
    existed, and every one of those served each account its own slot — so absent
    reads as ``own``. An unreadable value reads as ``own`` too, and here the
    closed direction and the compatible direction happen to be the same one:
    ``own`` shows a reader nothing but their own, while a misread ``recipe``
    would hand a stranger a copy that was never filed under them.
    """
    if mode != MODE_IDENTITY:
        return READS_RECIPE
    raw = entry.get("reads")
    if isinstance(raw, str) and raw in READS:
        return raw
    return READS_OWN


def _portal_of(entry: dict[str, Any]) -> bool:
    """Whether this page is the sign-in door.

    ``is True`` rather than truthiness, like every other switch here: the values
    that are merely truthy (``"false"``, ``1``, ``"no"``) are all hand-edits that
    meant the opposite.
    """
    return entry.get("portal") is True


def legacy_runnable(entry: dict[str, Any] | None) -> bool:
    """Whether a stored entry still carries the retired ``runnable`` flag.

    Read for one purpose only: telling the owner that an entry written by an
    older frago is claiming something this one no longer honours. It grants
    nothing. What a page may trigger now comes from the ``@action`` marks on
    the recipe's own mode methods — see ``frago book recipe-expose``.
    """
    return isinstance(entry, dict) and entry.get("runnable") is True


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

    Returns a normalised copy — every field is present and sane — so that no
    caller has to repeat the defaulting rules and get one of them subtly
    different.
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
        "reads": _reads_of(entry, mode),
        "portal": _portal_of(entry),
    }


def serves_recipe_slot(entry: dict[str, Any] | None) -> bool:
    """Whether this page is served from the recipe's own root rather than the reader's.

    Asked by the gate and by three routes, so it lives here for the same reason
    ``allows`` does: one comparison, one answer. A page nobody has exposed is
    neither — it is not anything.
    """
    if not isinstance(entry, dict):
        return False
    return _reads_of(entry, _mode_of(entry)) == READS_RECIPE


def portal_name() -> str | None:
    """The exposed page registered as this server's sign-in door, if any.

    Read from the registry rather than a constant in the gate so that "which
    page is the door" is visible in ``frago recipe exposed`` alongside every
    other decision about who may open what. The gate keeps a fallback for
    deployments that never registered one; see ``security.login_portal``.
    """
    for name, entry in load().items():
        if _portal_of(entry) and isinstance(name, str):
            return name
    return None


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
    reads: str | None = None,
    portal: bool = False,
) -> dict[str, Any]:
    """Write one recipe's whole exposure record. Returns the entry.

    Callers changing an existing exposure should go through ``amend`` instead:
    this function states the entry in full, so anything it is not told is set to
    that field's default rather than left as it was.

    ``mode=MODE_IDENTITY`` requires a sign-in. ``reads`` then decides which root
    those signed-in readers are served from: ``own`` gives each of them the slot
    named after their own account, ``recipe`` gives all of them the recipe's own
    slot named in ``slot``.

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

    if reads is None:
        reads = READS_RECIPE if mode == MODE_PUBLIC else READS_OWN
    if reads not in READS:
        raise ValueError(f"unknown reads {reads!r}; expected one of {READS}")
    if mode == MODE_PUBLIC and reads != READS_RECIPE:
        raise ValueError(
            "a public page is always served from the recipe's own slot: an anonymous "
            "reader has no account and therefore no copy of their own"
        )

    if portal:
        # One door. Two pages both claiming to be it is a coin flip the gate
        # would have to make on every refused request, and the wrong side of it
        # is a redirect loop for everybody who is not signed in.
        holder = portal_name()
        if holder is not None and holder != name:
            raise ValueError(
                f"'{holder}' is already registered as this server's sign-in door. "
                f"Take that one off first: frago recipe expose {holder} --no-portal"
            )
        if mode != MODE_PUBLIC:
            raise ValueError(
                "the sign-in door has to be readable by someone who is not signed in; "
                "expose it with --public"
            )

    entries = load()
    entry = {
        "slot": slot,
        "mode": mode,
        "since": datetime.now().astimezone().isoformat(timespec="seconds"),
        # Written even when they carry the defaults: a reader of this file should
        # see who the page is open to without having to know which frago version
        # wrote the entry.
        "allow": list(allow) if allow is not None else None,
        "reads": reads,
        "portal": bool(portal),
    }
    entries[name] = entry
    _save(entries)
    return entry


def amend(
    name: str,
    *,
    slot: str | None = None,
    mode: str | None = None,
    allow_add: list[str] | None = None,
    allow_remove: list[str] | None = None,
    allow_set: list[str] | None = None,
    open_to_all_signed_in: bool = False,
    reads: str | None = None,
    portal: bool | None = None,
) -> dict[str, Any]:
    """Change parts of an existing exposure, leaving the rest alone.

    This is the shape the command has because of what the previous one cost.
    Every ``expose`` used to write the whole entry, so a flag left off was a flag
    turned off — and exactly one field made that dangerous: a page open to four
    named accounts, re-exposed to change something else, silently reopened to
    every account on the server. The guard was a ``--force`` flag that had to be
    remembered in the one case nobody remembers, and on 2026-08-28 the accident
    it exists to stop happened anyway, in the other direction: a five-person list
    copied onto a page that should have had one.

    A widening now has to be *said*: ``allow_remove`` names who goes,
    ``open_to_all_signed_in`` is the whole-list drop spelled out loud, and
    ``mode`` only changes when it is passed. Nothing widens by omission, so there
    is no longer anything for a force flag to guard.

    Raises ``KeyError`` if the page is not exposed at all — amending something
    that does not exist is a different act from exposing it, and quietly turning
    one into the other is how a page gets published with defaults nobody chose.
    """
    entries = load()
    if name not in entries:
        raise KeyError(name)
    current = published_entry(name) or {}

    next_mode = mode or current.get("mode") or MODE_PUBLIC
    next_slot = slot or current.get("slot") or DEFAULT_SLOT
    next_reads = reads or current.get("reads") or (
        READS_RECIPE if next_mode == MODE_PUBLIC else READS_OWN
    )
    if next_mode == MODE_PUBLIC:
        next_reads = READS_RECIPE

    if allow_set is not None:
        next_allow: list[str] | None = list(allow_set)
    elif open_to_all_signed_in:
        next_allow = None
    else:
        held = current.get("allow")
        next_allow = list(held) if isinstance(held, list) else None
        if allow_add:
            if next_allow is None:
                # Naming somebody on a page that was open to everyone signed in
                # is a narrowing, and it is the reading the operator meant: they
                # said who, so the answer stops being "anyone".
                next_allow = []
            for who in allow_add:
                if who not in next_allow:
                    next_allow.append(who)
        if allow_remove and next_allow is not None:
            next_allow = [who for who in next_allow if who not in allow_remove]

    if next_allow is not None and not next_allow:
        raise ValueError(
            "that would leave nobody on the list, and a page nobody may open is "
            "not a configuration — close it with `frago recipe unexpose` instead."
        )
    if next_allow is not None and next_mode != MODE_IDENTITY:
        # A named list only means anything against an account, so keeping both
        # would store a restriction the gate can never apply.
        raise ValueError(
            "a public page cannot have an allow list: there is no account to "
            "compare. Drop the names, or keep the page signed-in."
        )

    next_portal = current.get("portal", False) if portal is None else portal

    return publish(
        name,
        next_slot,
        next_mode,
        allow=next_allow,
        reads=next_reads,
        portal=bool(next_portal),
    )


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
