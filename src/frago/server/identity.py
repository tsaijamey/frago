"""Who the visitor is, when the visitor is not the owner.

The three zones in ``security.py`` answer "may this request happen at all".
They have no notion of *who* is asking: a published page serves the same bytes
to everyone, because anonymous is the only kind of visitor that exists. This
module adds the fourth kind — someone who logged in — so that the server has a
basis for handing two different visitors two different slots of the same
recipe's data.

An identity here is an email address and a password, and nothing else:

    first visit    email + a password they choose → account created on the spot
    later visits   the same email must come back with the same password
    the receipt    a random cookie; the server keeps only its hash

**The email is a handle, not proof.** There is no verification step, so this
module makes no claim that an address belongs to the person using it. Anything
that would need that claim — password recovery, notifications, reconciling
against another system — is deliberately absent, and must stay absent until
verification exists. Whoever logs in with an address first owns it here.

Two tables, deliberately different shapes:

    users.json          one file, whole-table read-modify-write, so every write
                        happens under an in-process lock *and* ``flock`` — the
                        global account cap is a load-bearing limit and two
                        concurrent signups must not both read "499 accounts,
                        room for one more".

    login-sessions/     one file per session. Issuing is ``O_EXCL``, revoking is
                        ``unlink``, resolving is one small read. There is no
                        whole-table rewrite anywhere, so there is no lost update
                        to lose sleep over, and a request costs a stat instead of
                        a scan.

The session directory is **not** ``~/.frago/sessions/`` — that is where agent
session records live (``frago.session.storage``, ``FRAGO_SESSION_DIR``). Note
how close ``FRAGO_SESSION_DIR`` and this module's ``FRAGO_SESSIONS_DIR`` are:
one letter. The directories are kept apart precisely because the names are not.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:  # POSIX only; on Windows the cross-process half of the lock is unavailable
    import fcntl
except ImportError:  # pragma: no cover - frago targets macOS and Linux
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

USERS_PATH = Path.home() / ".frago" / "users.json"
SESSIONS_DIR = Path.home() / ".frago" / "login-sessions"
# Identity data lives under its own root, so a recipe writing a slot of its own
# can never land on a file that belongs to a person. See the spec's
# "身份数据与配方数据物理分开".
#
# One directory per account — `users/<id>/state/<recipe>.json` for the slots,
# `users/<id>/data/<recipe>/` for that account's output — because the questions
# that get asked in anger are per-account: delete everything this person has,
# and does this account have any data at all. `frago.recipes.app_state` resolves
# the same root by the same rule and the two definitions must move together;
# pointing them at different directories would leave the server reading a
# directory nothing writes.
USER_STATE_DIR = Path.home() / ".frago" / "users"

# Where those slots lived before the per-account root: `<recipe>/<id>.json`.
# Kept only so `migrate_user_state()` can find and empty it.
LEGACY_USER_STATE_DIR = Path.home() / ".frago" / "app-state-users"

COOKIE_NAME = "frago_sid"

# scrypt at n=2^14 costs ~34ms here. That is the whole budget: it must be slow
# enough that a stolen table is not a wordlist away from plaintext, and cheap
# enough that a public endpoint calling it is not an amplifier. Rate limiting
# runs *before* this, never after.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024

DEFAULT_SESSION_TTL = 7 * 24 * 3600
DEFAULT_TOTAL_CAP = 500
DEFAULT_UNUSED_CAP = 200
DEFAULT_SESSIONS_PER_USER = 10
DEFAULT_TOTAL_SESSIONS = 5000

# How long a session file is allowed to be unreadable before the purge treats it
# as rubbish rather than as one being written right now. Any value comfortably
# longer than a write takes will do; the point is that it is not zero.
_WRITE_GRACE = 60

MIN_PASSWORD_LENGTH = 10
# scrypt runs over whatever it is given, so an unbounded password is an
# unbounded amount of work on an anonymous endpoint.
MAX_PASSWORD_LENGTH = 256
# RFC 5321 caps an address at 320 bytes. The raw input is capped lower still
# before NFKC touches it: normalising a megabyte of text is itself the attack.
MAX_EMAIL_LENGTH = 320
MAX_RAW_EMAIL_LENGTH = 512

_WEAK_PASSWORDS = frozenset({
    "password", "password1", "password123", "passw0rd", "123456", "1234567",
    "12345678", "123456789", "1234567890", "qwertyuiop", "letmein", "welcome",
    "iloveyou", "admin", "administrator", "changeme", "abc123", "monkey",
    "dragon", "sunshine", "princess", "football", "baseball", "trustno1",
    "qwerty123", "1q2w3e4r", "zaq12wsx", "asdfghjkl", "000000", "111111",
})

_EMAIL_SHAPE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Same alphabet as ``app_state._SAFE_NAME``, restated rather than imported: the
# migration walks names that came off the filesystem, and this module answers
# questions about identity without pulling the recipe layer into the server.
_SLOT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class IdentityError(Exception):
    """Something the caller asked for cannot be done. Carries a stable reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


@dataclass(frozen=True)
class User:
    """A person who can sign in. Created on their first successful login."""

    id: str          # sha256(normalised email)[:32]; also their slot name
    email: str       # an unverified handle, not an identity document
    disabled: bool
    created: str


@dataclass(frozen=True)
class LoginSession:
    """One login's lifetime.

    Deliberately not called ``Session``: ``frago.session`` is the agent
    transcript store, and confusing the two is how a login cookie ends up in an
    agent's session ledger.
    """

    sid: str
    identity: str
    created: str
    expires: str
    last_seen: str


# ---------------------------------------------------------------------------
# where things live
# ---------------------------------------------------------------------------


def users_path() -> Path:
    """The account table. ``FRAGO_USERS_FILE`` overrides, for tests and staging."""
    override = os.environ.get("FRAGO_USERS_FILE")
    return Path(override).expanduser() if override else USERS_PATH


def sessions_dir() -> Path:
    """The login-session directory. ``FRAGO_SESSIONS_DIR`` overrides."""
    override = os.environ.get("FRAGO_SESSIONS_DIR")
    return Path(override).expanduser() if override else SESSIONS_DIR


def user_state_dir() -> Path:
    """Root of the per-account subtrees. ``FRAGO_USER_STATE_DIR`` overrides.

    Not to be confused with ``users.json`` next door, which is the account
    table. One letter of difference and two entirely different things: this is
    what each account *has*, that is who each account *is*.
    """
    override = os.environ.get("FRAGO_USER_STATE_DIR")
    return Path(override).expanduser() if override else USER_STATE_DIR


def legacy_user_state_dir() -> Path:
    """The pre-migration root, `<recipe>/<account-id>.json`.

    ``FRAGO_LEGACY_USER_STATE_DIR`` overrides it directly. Failing that it
    follows ``FRAGO_USER_STATE_DIR`` as a sibling: a test or a staging instance
    that redirected only the new root would otherwise have the migration reach
    into the real home and move the live server's files into a temp directory.
    """
    override = os.environ.get("FRAGO_LEGACY_USER_STATE_DIR")
    if override:
        return Path(override).expanduser()
    new_root = os.environ.get("FRAGO_USER_STATE_DIR")
    if new_root:
        return Path(new_root).expanduser().parent / LEGACY_USER_STATE_DIR.name
    return LEGACY_USER_STATE_DIR


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("%s=%r is not a number; using %d", name, raw, default)
        return default
    return value if value > 0 else default


def session_ttl() -> int:
    """Seconds a login is good for. Absolute — there is no sliding renewal.

    This number *is* the exposure window of a stolen cookie, which is why it is
    a declared default rather than something each deployment discovers.
    """
    return _int_env("FRAGO_SESSION_TTL", DEFAULT_SESSION_TTL)


# ---------------------------------------------------------------------------
# email → id
# ---------------------------------------------------------------------------


def normalize_email(raw: str) -> str:
    """The one and only normalisation. NEVER write ``lower()`` on an email again.

    ``str.lower()`` and ``str.casefold()`` disagree on characters like ``İ``
    (U+0130), so two call sites using different methods would derive two ids for
    one person — half their data under each. One entry point removes the
    possibility rather than documenting it.
    """
    return unicodedata.normalize("NFKC", raw.strip()).casefold()


def derive_id(email: str) -> str:
    """The account id, which is also the person's slot name.

    A hash rather than a readable slug, for three reasons that are each a class
    of accident: ``a+b@x.com`` and ``a_b@x.com`` must not collapse into one
    directory; a 320-byte address must not overrun a 255-byte filename (and
    truncating is worse — truncation *is* collision, i.e. one person reading
    another's data); and the id must match ``app_state._SAFE_NAME``
    (``^[A-Za-z0-9._-]+$``), which arbitrary addresses do not.

    Readability is recovered by ``frago user list`` printing id ↔ email. That is
    an operator view; it does not have to be the directory name.
    """
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:32]


def email_problem(raw: str) -> str | None:
    """Why this address cannot be used, or None if it can."""
    if not raw or not raw.strip():
        return "email is required"
    if len(raw) > MAX_RAW_EMAIL_LENGTH:
        return "email is too long"
    normalized = normalize_email(raw)
    if len(normalized.encode("utf-8")) > MAX_EMAIL_LENGTH:
        return "email is too long"
    if not _EMAIL_SHAPE.match(normalized):
        return "that does not look like an email address"
    return None


def password_problem(password: str) -> str | None:
    """Why this password will not be accepted for a new account, or None.

    Only new accounts are checked. Tightening the rule later must not lock out
    people whose existing password no longer passes it — that would be a denial
    of service delivered by a policy change.
    """
    if not password:
        return "password is required"
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"password must be at least {MIN_PASSWORD_LENGTH} characters"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"password must be at most {MAX_PASSWORD_LENGTH} characters"
    if password.strip().casefold() in _WEAK_PASSWORDS:
        return "that password is on every guessing list; pick another"
    return None


# ---------------------------------------------------------------------------
# password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str, *, n: int = _SCRYPT_N, r: int = _SCRYPT_R,
                  p: int = _SCRYPT_P) -> str:
    """``scrypt$n$r$p$salt$hash``, both tails base64.

    The parameters travel inside the string so that raising them later leaves
    every existing record verifiable — a record written at n=2^14 is checked at
    n=2^14 no matter what the constant says today, and ``needs_rehash`` marks it
    for a free upgrade on the next successful login.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
        dklen=_SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM,
    )
    return "scrypt${}${}${}${}${}".format(
        n, r, p,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Whether this password produced that hash. False on anything malformed."""
    if not encoded or len(password) > MAX_PASSWORD_LENGTH:
        return False
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = (int(parts[1]), int(parts[2]), int(parts[3]))
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
    except (ValueError, TypeError):
        return False
    # A record claiming absurd parameters would turn one login into a
    # denial of service against the whole process.
    if not (0 < n <= 2**20 and 0 < r <= 32 and 0 < p <= 16):
        return False
    try:
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
            dklen=len(expected) or _SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM,
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest, expected)


def needs_rehash(encoded: str) -> bool:
    """Whether a verified password should be re-hashed at today's parameters."""
    parts = (encoded or "").split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return True
    try:
        return (int(parts[1]), int(parts[2]), int(parts[3])) != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# the account table
# ---------------------------------------------------------------------------

# Cached on (path, mtime_ns, size), the shape `publish.load()` already proved
# out. NEVER a time-based TTL: `frago user disable` runs in *another process*,
# and a TTL would turn "the next request fails" into "some seconds from now the
# next request fails", which is not what disabling an account promises.
# The path is part of the key so that a test pointing the table somewhere else
# cannot be served the previous test's table.
_users_cache: tuple[Path, tuple[int, int], dict[str, dict[str, Any]]] | None = None

# flock is held per file descriptor, so two threads in this process each opening
# the lock file would each get their own lock and neither would wait. The
# in-process lock is what makes threads queue; flock is what makes the daemon and
# a CLI process queue. Both are needed; neither is sufficient.
_WRITE_LOCK = threading.RLock()


def _invalidate_users_cache() -> None:
    global _users_cache
    _users_cache = None


def _read_users_file() -> dict[str, dict[str, Any]]:
    path = users_path()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {
        uid: rec for uid, rec in loaded.items()
        if isinstance(uid, str) and isinstance(rec, dict)
    }


def load_users() -> dict[str, dict[str, Any]]:
    """Every account, keyed by id. Cached until the file changes."""
    global _users_cache
    path = users_path()
    try:
        stat = path.stat()
    except OSError:
        _users_cache = None
        return {}

    stamp = (stat.st_mtime_ns, stat.st_size)
    if _users_cache is not None and _users_cache[0] == path and _users_cache[1] == stamp:
        return _users_cache[2]

    entries = _read_users_file()
    _users_cache = (path, stamp, entries)
    return entries


def _write_users(entries: dict[str, dict[str, Any]]) -> None:
    """Replace the table. 0600 from creation — it holds password hashes."""
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)
        os.replace(str(tmp), str(path))
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    _invalidate_users_cache()


@contextmanager
def _users_locked() -> Iterator[dict[str, dict[str, Any]]]:
    """Read-modify-write the table with nobody else in the middle.

    Yields the current table; mutate it in place and it is written on exit. The
    lock is a sidecar file rather than ``users.json`` itself: publishing a new
    table with ``os.replace`` swaps the inode, so a waiter blocked on the old
    inode's lock would wake up holding a lock on a file that is no longer the
    table, read stale contents, and write them back over the winner's.
    """
    with _WRITE_LOCK:
        path = users_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            entries = _read_users_file()
            before = json.dumps(entries, sort_keys=True)
            yield entries
            if json.dumps(entries, sort_keys=True) != before:
                _write_users(entries)
        finally:
            if fcntl is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _now() -> datetime:
    return datetime.now().astimezone()


def _stamp(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _as_user(record: dict[str, Any]) -> User:
    return User(
        id=str(record.get("id") or ""),
        email=str(record.get("email") or ""),
        disabled=bool(record.get("disabled")),
        created=str(record.get("created") or ""),
    )


def find_user_by_id(user_id: str) -> User | None:
    record = load_users().get(user_id)
    return _as_user(record) if record else None


def find_user_by_email(email: str) -> User | None:
    """The account this address belongs to, if any.

    Exists so that an operator typing an email never derives the id themselves:
    the derivation has exactly one implementation (``derive_id``), and a second
    one — even ``sha256(email.lower())`` in a shell — finds nobody for anyone
    whose address normalises differently.
    """
    return find_user_by_id(derive_id(email))


def list_users() -> list[User]:
    """Every account, oldest first. No password material comes out of here.

    ``User`` has no ``pwd`` field on purpose: an operator view built by hand
    from the raw table is one ``print`` away from putting a hash on a terminal
    and into a scrollback buffer, so callers outside this module never see the
    raw records.
    """
    return sorted(
        (_as_user(record) for record in load_users().values()),
        key=lambda user: (user.created, user.email),
    )


def set_disabled(user_id: str, disabled: bool) -> User:
    """Suspend or reinstate an account. Raises if there is no such account.

    Written under the same lock as every other change to the table: the daemon
    is serving logins into this file while the CLI edits it, and a read-modify-
    write outside the lock would drop whichever change lost the race — here,
    silently un-suspending an account the owner just suspended.

    Suspending also drops that account's sessions. Resolution already re-checks
    the account on every request, so this is not what makes the suspension take
    effect; it is what stops ``frago user session list`` from showing live-looking
    sessions that no longer are.
    """
    with _users_locked() as entries:
        record = entries.get(user_id)
        if record is None:
            raise IdentityError("no_such_user", "no such account")
        record["disabled"] = bool(disabled)
        updated = dict(record)
    if disabled:
        revoke_identity_sessions(user_id)
    return _as_user(updated)


def has_data(user_id: str) -> bool:
    """Whether any recipe has ever written a slot for this account.

    This is the signal that separates a real visitor from a flooded-in account:
    someone who actually used the site produced at least one slot write, a
    script that only ever hit ``/api/auth/login`` produced none. Reading it is
    free, which is why eviction can be selective instead of a flat refusal.

    Free is now literal: one account is one directory, so this is a single
    stat. Under the old by-recipe layout it had to open every recipe directory
    on the server looking for one file name — and it runs once per account on
    every signup.
    """
    if not user_id:
        return False
    try:
        return (user_state_dir() / user_id).is_dir()
    except OSError:
        return False


def _account_state_dir(account_id: str) -> Path:
    """Create ``users/<id>/state/`` with every level 0700, and return it.

    Every level, not just the last: ``mkdir(parents=True)`` builds the levels it
    invents under the umask, and a 0755 ``users/`` hands a second unix account
    on this machine the id of everyone who ever signed in.
    """
    root = user_state_dir()
    account = root / account_id
    state = account / "state"
    state.mkdir(parents=True, exist_ok=True)
    for level in (root, account, state):
        with contextlib.suppress(OSError):
            level.chmod(0o700)
    return state


def migrate_user_state() -> int:
    """Move identity slots from the by-recipe layout to the per-account one.

    ``app-state-users/<recipe>/<id>.json`` becomes ``users/<id>/state/<recipe>.json``.
    Returns how many files moved, so a caller can log a real number instead of
    "migration ran".

    Idempotent, because it has to survive being interrupted: each file is moved
    on its own by rename, which has no half-way state, and a file already at the
    destination is left alone. That last rule also settles the mixed case — a
    server that started writing the new layout before this ran keeps the newer
    file and the older one stays behind with a warning, rather than a
    migration quietly overwriting live data with a copy from before the restart.
    """
    legacy = legacy_user_state_dir()
    if not legacy.is_dir():
        return 0

    root = user_state_dir()
    moved = 0
    for recipe_dir in sorted(legacy.iterdir()):
        if recipe_dir.is_symlink() or not recipe_dir.is_dir():
            continue
        for slot_file in sorted(recipe_dir.glob("*.json")):
            if slot_file.is_symlink() or not slot_file.is_file():
                continue
            account_id = slot_file.stem
            # The account id becomes a directory name here, so it is checked
            # rather than trusted: these names come off the filesystem, and
            # `...json` would have a stem of `..`.
            if not _SLOT_NAME.match(account_id) or account_id in {".", ".."}:
                logger.warning(
                    "identity state migration: skipping %s, whose name is not an "
                    "account id", slot_file,
                )
                continue
            target = root / account_id / "state" / f"{recipe_dir.name}.json"
            if target.exists():
                logger.warning(
                    "identity state migration: %s already exists and is newer than "
                    "%s; leaving the old copy in place rather than overwriting",
                    target, slot_file,
                )
                continue
            try:
                _account_state_dir(account_id)
                shutil.move(str(slot_file), str(target))
                target.chmod(0o600)
            except OSError:
                logger.exception("identity state migration: could not move %s", slot_file)
                continue
            moved += 1
        # An empty recipe directory left behind reads as "this recipe has
        # users", which is exactly the thing that is no longer true.
        with contextlib.suppress(OSError):
            recipe_dir.rmdir()

    with contextlib.suppress(OSError):
        legacy.rmdir()
    if moved:
        logger.info("identity state migration: moved %d slot file(s) to %s", moved, root)
    return moved


def account_caps() -> tuple[int, int]:
    """``(total_cap, unused_cap)``.

    Two caps rather than one, because a single hard cap does not stop an
    attacker — it stops *everyone who has not arrived yet*, permanently, and
    500 slow requests spread over a day defeat any token bucket. The second cap
    evicts the oldest account that never produced data, so the flood costs the
    attacker their own earlier accounts instead of the feature.
    """
    total = _int_env("FRAGO_MAX_USERS", DEFAULT_TOTAL_CAP)
    unused = _int_env("FRAGO_MAX_UNUSED_USERS", DEFAULT_UNUSED_CAP)
    return total, min(unused, total)


def _make_room(entries: dict[str, dict[str, Any]]) -> None:
    """Enforce both caps. Raises when the hard cap is genuinely full."""
    total_cap, unused_cap = account_caps()
    if len(entries) >= total_cap:
        logger.warning(
            "account table is full (%d/%d) and every account has data; refusing to "
            "create another. Run `frago user list` and prune.",
            len(entries), total_cap,
        )
        raise IdentityError("account_limit", "this server is not accepting new accounts")

    unused = [rec for rec in entries.values() if not has_data(str(rec.get("id") or ""))]
    if len(unused) < unused_cap:
        return
    # Oldest first; accounts with data are not in this list at all, which is the
    # hard rule — an account that used the site is never evicted automatically.
    for victim in sorted(unused, key=lambda rec: str(rec.get("created") or ""))[
        : len(unused) - unused_cap + 1
    ]:
        vid = str(victim.get("id") or "")
        entries.pop(vid, None)
        revoke_identity_sessions(vid)
        logger.warning(
            "unused-account quota reached (%d/%d): evicted %s (%s), which never "
            "wrote any data",
            len(unused), unused_cap, vid, victim.get("email"),
        )


def create_user(email: str, password: str) -> User:
    """Create an account. Raises ``IdentityError`` rather than returning None.

    Everything that decides whether the account may exist — the caps, the
    eviction, the duplicate check — happens inside the lock. Outside it, two
    concurrent first-logins both read "there is room" and both write, and the
    loser's record disappears while its freshly issued session stays valid: a
    live cookie pointing at an account that does not exist.
    """
    problem = email_problem(email)
    if problem:
        raise IdentityError("invalid_email", problem)
    problem = password_problem(password)
    if problem:
        raise IdentityError("weak_password", problem)

    user_id = derive_id(email)
    encoded = hash_password(password)
    with _users_locked() as entries:
        existing = entries.get(user_id)
        if existing:
            return _as_user(existing)
        _make_room(entries)
        entries[user_id] = {
            "id": user_id,
            "email": normalize_email(email),
            "pwd": encoded,
            "disabled": False,
            "created": _stamp(),
        }
        record = entries[user_id]
    logger.info("new account %s (%s, unverified email)", user_id, record["email"])
    return _as_user(record)


def verify_user_password(user_id: str, password: str) -> bool:
    """Whether this is the account's current password.

    Exists so that the route changing a password never touches a hash. The
    hashes stay inside this module; a caller that could read one could log it.
    """
    record = load_users().get(user_id)
    if record is None or record.get("disabled"):
        return False
    return verify_password(password, str(record.get("pwd") or ""))


def set_password(user_id: str, password: str, *, revoke_sessions: bool = True) -> None:
    """Replace an account's password and, by default, log every device out."""
    problem = password_problem(password)
    if problem:
        raise IdentityError("weak_password", problem)
    encoded = hash_password(password)
    with _users_locked() as entries:
        record = entries.get(user_id)
        if record is None:
            raise IdentityError("no_such_user", "no such account")
        record["pwd"] = encoded
    if revoke_sessions:
        revoke_identity_sessions(user_id)


def authenticate(email: str, password: str, *, gate: str | None = None) -> tuple[User, str]:
    """Sign in, creating the account if this address has never been seen.

    Returns ``(user, "ok"|"created")``; every refusal is an ``IdentityError``
    whose ``reason`` the route maps to a status code.

    This function does **not** attempt to make a failed login indistinguishable
    from a first login. It cannot: "unknown address signs in" and "known address
    with the wrong password is refused" are different outcomes by construction,
    so user enumeration is a property of the design and is documented rather
    than pretended away.
    """
    problem = email_problem(email)
    if problem:
        raise IdentityError("invalid_email", problem)

    user_id = derive_id(email)
    record = load_users().get(user_id)

    if record is None:
        if not check_signup_gate(gate):
            raise IdentityError("gate_required", _gate_message())
        if not allow_signup(_pending_ip.get()):
            raise IdentityError("rate_limited", "too many new accounts from here; wait a while")
        return create_user(email, password), "created"

    if record.get("disabled"):
        # Deliberately the same shape as a wrong password: a suspended account
        # should not be a working probe for "this address is registered".
        raise IdentityError("bad_credentials", "email or password is wrong")

    penalty = login_backoff_remaining(user_id)
    if penalty > 0:
        raise IdentityError(
            "rate_limited",
            f"too many failed attempts; try again in {int(penalty) + 1}s",
        )

    if not verify_password(password, str(record.get("pwd") or "")):
        note_login_failure(user_id)
        raise IdentityError("bad_credentials", "email or password is wrong")

    note_login_success(user_id)
    if needs_rehash(str(record.get("pwd") or "")):
        # A free upgrade on the way past: the plaintext is in hand exactly here
        # and nowhere else. Sessions stay valid — the password did not change.
        with contextlib.suppress(IdentityError):
            set_password(user_id, password, revoke_sessions=False)
    return _as_user(record), "ok"


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


def _sid_of(token: str) -> str:
    """What is stored. The cookie itself never touches the disk."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session_path(sid: str) -> Path:
    return sessions_dir() / f"{sid}.json"


def _read_session(sid: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(_session_path(sid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _parse_time(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _session_files() -> list[Path]:
    directory = sessions_dir()
    try:
        return sorted(directory.glob("*.json"))
    except OSError:
        return []


def purge_expired_sessions() -> int:
    """Drop sessions whose time is up. Called on every issue, so the directory
    is tidied by the same traffic that fills it.

    "I could not read it" is not "it is dead". This runs on every issue, so it
    runs concurrently with other issues, and a file that cannot be parsed right
    now is far more likely to be one being written this instant than one that is
    genuinely corrupt. Deleting on a failed read logged people out at random the
    moment two of them signed in together. An unreadable file is left alone
    until it is older than a session could ever be, by which point nothing is
    still writing it.
    """
    now = _now()
    stale_after = session_ttl() + _WRITE_GRACE
    removed = 0
    for path in _session_files():
        record = _read_session(path.stem)
        if record is None:
            try:
                unreadable_for = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if unreadable_for < stale_after:
                continue
        else:
            expires = _parse_time(record.get("expires"))
            if expires is not None and expires > now:
                continue
        with contextlib.suppress(OSError):
            path.unlink()
            removed += 1
    return removed


def _enforce_session_caps(identity: str) -> None:
    per_user = _int_env("FRAGO_MAX_SESSIONS_PER_USER", DEFAULT_SESSIONS_PER_USER)
    total = _int_env("FRAGO_MAX_SESSIONS", DEFAULT_TOTAL_SESSIONS)

    live: list[tuple[str, Path, dict[str, Any]]] = []
    for path in _session_files():
        record = _read_session(path.stem)
        if record:
            live.append((str(record.get("identity") or ""), path, record))

    def evict(candidates: list[tuple[str, Path, dict[str, Any]]], keep: int) -> None:
        ordered = sorted(candidates, key=lambda item: str(item[2].get("created") or ""))
        for _, path, _record in ordered[: max(0, len(ordered) - keep + 1)]:
            with contextlib.suppress(OSError):
                path.unlink()

    mine = [item for item in live if item[0] == identity]
    if len(mine) >= per_user:
        evict(mine, per_user)
    if len(live) >= total:
        evict(live, total)


def create_session(identity: str) -> str:
    """Issue a session and return the cookie value. Only its hash is stored."""
    directory = sessions_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)

    purge_expired_sessions()
    _enforce_session_caps(identity)

    now = _now()
    record = {
        "identity": identity,
        "created": _stamp(now),
        "expires": _stamp(now + timedelta(seconds=session_ttl())),
        "last_seen": _stamp(now),
    }
    for _ in range(4):
        token = secrets.token_urlsafe(32)
        path = _session_path(_sid_of(token))
        # Written in full to a temporary name, then linked into place, so the
        # session file never exists in a half-written state. `O_EXCL` on the
        # real path is not enough: it publishes an empty file first, and a purge
        # running in another thread reads that empty file, cannot parse it, and
        # deletes a session that has already been handed to someone.
        tmp = path.with_name(f".{path.stem}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False)
            try:
                os.link(str(tmp), str(path))
            except FileExistsError:  # pragma: no cover - 256 bits do not collide
                continue
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return token
    raise IdentityError("session_failed", "could not issue a session")  # pragma: no cover


# Writing on every request would turn a page load into a write per asset, so
# last_seen is deliberately coarse. It is an operations view; nothing decides
# anything by it.
_LAST_SEEN_RESOLUTION = 300


def resolve_session(token: str | None) -> LoginSession | None:
    """The session this cookie names, or None if it is not one we honour.

    Every refusal is silent to the caller and identical in shape: expired,
    revoked, never existed, account suspended, account gone. Only the last of
    those is worth a log line, and it gets a warning rather than a pass — a
    session pointing at an account that no longer exists must not be readable as
    "not disabled, therefore fine". That is the ghost session no operator tool
    can see or stop.
    """
    if not token:
        return None
    sid = _sid_of(token)
    record = _read_session(sid)
    if record is None:
        return None

    identity = str(record.get("identity") or "")
    expires = _parse_time(record.get("expires"))
    if expires is None or expires <= _now():
        with contextlib.suppress(OSError):
            _session_path(sid).unlink()
        return None

    user = find_user_by_id(identity)
    if user is None:
        logger.warning(
            "login session %s… names account %s, which is not in the table; "
            "treating the request as signed out",
            sid[:8], identity,
        )
        return None
    if user.disabled:
        return None

    session = LoginSession(
        sid=sid,
        identity=identity,
        created=str(record.get("created") or ""),
        expires=str(record.get("expires") or ""),
        last_seen=str(record.get("last_seen") or ""),
    )
    _touch(sid, record, session)
    return session


def _touch(sid: str, record: dict[str, Any], session: LoginSession) -> None:
    seen = _parse_time(session.last_seen)
    now = _now()
    if seen is not None and (now - seen).total_seconds() < _LAST_SEEN_RESOLUTION:
        return
    record["last_seen"] = _stamp(now)
    path = _session_path(sid)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)
        os.replace(str(tmp), str(path))
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def revoke_session(token: str) -> bool:
    """Log this one cookie out."""
    try:
        _session_path(_sid_of(token)).unlink()
        return True
    except OSError:
        return False


def list_sessions() -> list[LoginSession]:
    """Every login that is still good, newest first.

    Expired files are skipped rather than deleted: this is a read-only operator
    view, and a listing that tidies up as a side effect would make "what did the
    server see" depend on whether anyone happened to look.
    """
    now = _now()
    live: list[LoginSession] = []
    for path in _session_files():
        record = _read_session(path.stem)
        if not record:
            continue
        expires = _parse_time(record.get("expires"))
        if expires is None or expires <= now:
            continue
        live.append(LoginSession(
            sid=path.stem,
            identity=str(record.get("identity") or ""),
            created=str(record.get("created") or ""),
            expires=str(record.get("expires") or ""),
            last_seen=str(record.get("last_seen") or ""),
        ))
    return sorted(live, key=lambda session: session.created, reverse=True)


def revoke_session_id(sid: str) -> bool:
    """Log out the session with this stored id.

    The operator has the *id* (the hash), never the cookie — ``revoke_session``
    takes the cookie and is for the visitor's own logout. Keeping the two apart
    is what stops a listing from having to print anything that could be replayed
    as a credential.
    """
    if not sid or "/" in sid or "\\" in sid or "." in sid:
        return False
    try:
        _session_path(sid).unlink()
        return True
    except OSError:
        return False


def revoke_identity_sessions(identity: str) -> int:
    """Log this account out everywhere.

    With no recovery flow in this design, changing your password is the *only*
    way to deal with "I think my cookie was stolen", so it has to invalidate the
    thief's copy — every copy, including the caller's own. The route then issues
    a fresh session for the request in hand, so the person changing their
    password does not get logged out of the device they are typing on. Sparing
    the current session here instead would be the same outcome with one more
    thing to get wrong.
    """
    revoked = 0
    for path in _session_files():
        record = _read_session(path.stem)
        if record and str(record.get("identity") or "") == identity:
            with contextlib.suppress(OSError):
                path.unlink()
                revoked += 1
    return revoked


# ---------------------------------------------------------------------------
# rate limiting, and the address it keys on
# ---------------------------------------------------------------------------


class RateLimiter:
    """A token bucket per key, in memory.

    Not persisted, on purpose. A restart clearing the counters is acceptable —
    a restart is not something an attacker can trigger — whereas persisting
    them would add an anonymous-triggered write path to the public surface,
    which is opening a hole while closing one.
    """

    def __init__(self, capacity: int, window: float) -> None:
        self.capacity = float(capacity)
        self.window = float(window)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str | None) -> bool:
        """Spend one token. ``None`` means this layer declared itself unusable
        (see ``client_ip``), and an unusable limiter must not pretend to limit."""
        if key is None:
            return True
        now = time.monotonic()
        with self._lock:
            tokens, updated = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - updated) * self.capacity / self.window)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


class Backoff:
    """Growing delay after consecutive failures, per key.

    Not a lockout. Locking an account after N wrong passwords means anyone who
    knows an address can lock its owner out at will — one denial of service
    traded for another. Here the delay grows, and the right password always
    works once it has elapsed.
    """

    def __init__(self, free_attempts: int = 5, base: float = 2.0, cap: float = 300.0) -> None:
        self.free_attempts = free_attempts
        self.base = base
        self.cap = cap
        self._state: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def remaining(self, key: str) -> float:
        with self._lock:
            failures, until = self._state.get(key, (0, 0.0))
        if not failures:
            return 0.0
        return max(0.0, until - time.monotonic())

    def fail(self, key: str) -> None:
        with self._lock:
            failures, _ = self._state.get(key, (0, 0.0))
            failures += 1
            delay = 0.0
            if failures > self.free_attempts:
                delay = min(self.cap, self.base ** (failures - self.free_attempts))
            self._state[key] = (failures, time.monotonic() + delay)

    def clear(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._state.clear()


LOGIN_LIMIT = RateLimiter(30, 300)       # per client address: 30 attempts / 5 min
SIGNUP_LIMIT = RateLimiter(5, 3600)      # per client address: 5 new accounts / hour
LOGIN_BACKOFF = Backoff()                # per account


def reset_rate_limits() -> None:
    """Forget every counter. For tests, and for a future ``frago user unblock``."""
    LOGIN_LIMIT.reset()
    SIGNUP_LIMIT.reset()
    LOGIN_BACKOFF.reset()


def allow_login(ip: str | None) -> bool:
    """Called *before* scrypt. A limiter that runs after the expensive part is
    a counter, not a limit."""
    return LOGIN_LIMIT.allow(ip)


def allow_signup(ip: str | None) -> bool:
    return SIGNUP_LIMIT.allow(ip)


def login_backoff_remaining(user_id: str) -> float:
    return LOGIN_BACKOFF.remaining(user_id)


def note_login_failure(user_id: str) -> None:
    LOGIN_BACKOFF.fail(user_id)


def note_login_success(user_id: str) -> None:
    LOGIN_BACKOFF.clear(user_id)


class _PendingIP(threading.local):
    """The address of the request currently being authenticated.

    ``authenticate`` decides *inside itself* whether this login is also a
    signup, so the signup limiter has to be reachable from there; threading it
    through as an argument would let a caller pass the wrong one. Thread-local
    because the server handles requests concurrently.
    """

    value: str | None = None

    def get(self) -> str | None:
        return self.value

    def set(self, ip: str | None) -> None:
        self.value = ip


_pending_ip = _PendingIP()


@contextmanager
def acting_for(ip: str | None) -> Iterator[None]:
    """Mark which client address the authentication about to happen belongs to."""
    previous = _pending_ip.get()
    _pending_ip.set(ip)
    try:
        yield
    finally:
        _pending_ip.set(previous)


def trusted_proxies() -> list[str]:
    """Addresses whose forwarding headers this server believes.

    The same list must be handed to ``uvicorn.Config(forwarded_allow_ips=...)``.
    Configuring one without the other produces a server that disagrees with
    itself about who the client is.
    """
    raw = os.environ.get("FRAGO_TRUSTED_PROXIES", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def ip_rate_limiting_available() -> bool:
    """Whether "the client's address" means anything on this deployment.

    Rate limiting is the first thing in this module that turns an
    attacker-controlled value into a security decision, and there are two
    deployments where that value is worthless in opposite directions:

    * behind a proxy that is trusted to rewrite the peer address — every request
      can carry a fresh ``X-Forwarded-For``, so every request gets its own
      bucket and the limiter counts to one forever;
    * behind a proxy that is *not* trusted — every request arrives from the same
      address, so the whole world shares one bucket and a few dozen requests
      hand the attacker a switch that 429s every real visitor.

    So the address counts only when the operator has said which proxies are
    real. When they have not, this layer says so instead of failing silently,
    and the signup passphrase becomes mandatory to cover for it.
    """
    from frago.server.security import peer_trust_disabled

    if peer_trust_disabled():
        return bool(trusted_proxies())
    # No proxy declared: the peer address is the socket's own, and uvicorn only
    # rewrites it for hops it trusts (loopback by default). A deployment that is
    # actually behind a proxy without saying so is already the misconfiguration
    # `security.deployment_warning()` shouts about.
    return True


def client_ip(scope: dict) -> str | None:
    """The address rate limiting may key on, or None when it may key on nothing.

    Never read a forwarding header here. When the proxy configuration is
    complete, uvicorn has already rewritten ``scope["client"]`` from it using
    the same trusted list; when it is not, no header on this request is worth
    reading.
    """
    if not ip_rate_limiting_available():
        return None
    client = scope.get("client")
    if not client:
        return None
    return str(client[0])


# ---------------------------------------------------------------------------
# the shared signup passphrase
# ---------------------------------------------------------------------------


def signup_gate() -> str | None:
    """The passphrase a new account must present, if the operator set one."""
    value = os.environ.get("FRAGO_SIGNUP_GATE")
    return value if value else None


def signup_gate_required() -> bool:
    """Whether the passphrase layer can be turned off at all.

    It cannot when address-based limiting is unavailable: a missing layer is
    covered by another one rather than left as a hole.
    """
    return signup_gate() is not None or not ip_rate_limiting_available()


def _gate_message() -> str:
    if signup_gate() is None:
        return (
            "this server cannot accept new accounts: it is behind a proxy but "
            "FRAGO_TRUSTED_PROXIES is unset, so rate limiting is off and "
            "FRAGO_SIGNUP_GATE must be set instead"
        )
    return "this server needs the shared passphrase to create an account"


def check_signup_gate(presented: str | None) -> bool:
    """Whether a new account may be created with this passphrase.

    Compared with ``hmac.compare_digest``: unlike a 256-bit token, a passphrase
    a human typed is short and low-entropy enough that a timing side channel is
    worth something. Accepted from the request body only — a passphrase in a URL
    ends up in proxy access logs, browser history and ``Referer``.
    """
    expected = signup_gate()
    if expected is None:
        return not signup_gate_required()
    return hmac.compare_digest((presented or "").encode("utf-8"), expected.encode("utf-8"))


def public_https() -> bool:
    """Whether the operator declared this server is HTTPS to the outside world."""
    from frago.server.security import _enabled

    return _enabled("FRAGO_PUBLIC_HTTPS", default=False)


def cookie_is_secure(scope: dict) -> bool:
    """Whether this session cookie must be marked ``Secure``.

    Decided by *this request's own scheme*, plus the operator's declaration.
    Not by ``FRAGO_BEHIND_PROXY``: that switch means "do not infer trust from
    the peer address", which is unrelated to whether this connection is TLS. A
    server bound to 0.0.0.0 on plain HTTP sets no proxy switch and would have
    issued a cookie in the clear; and the HTTPS sidecar in this repo leaves the
    plain-HTTP port up alongside it, where same-site-different-scheme is not
    cross-site and ``SameSite=Lax`` protects nothing.
    """
    return (scope.get("scheme") or "").lower() in ("https", "wss") or public_https()
