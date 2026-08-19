"""Who is allowed to reach which part of this server.

frago's HTTP surface was built for a machine where the only caller is the human
who owns it: ``/api/file`` reads and writes any absolute path, ``/api/agent``
starts an agent, ``/api/recipes/{name}/run`` executes a script. On loopback that
is the point — it is what makes the suit fit. Reachable from anywhere else it is
a shell without a password.

The moment a frago is deployed on a server, three kinds of caller show up that
the original design never had: the owner's *other* frago driving this one over
the network, members of the public reading a recipe's page, and — since the
identity spec — people who signed in to see their own copy of one. They need
opposite things, so every request is sorted into exactly one zone:

    local           the caller is a process on this machine, not something a
                    proxy forwarded here — the existing local CLI, the desktop
                    client, recipes calling back in. Allowed, unconditionally,
                    so that installing this middleware changes nothing about how
                    a personal frago behaves.

    public          GET of ``/app/<recipe>/…`` for a recipe that has been
                    explicitly published (``frago recipe publish``), plus the one
                    anonymous POST there is: ``/api/auth/login``. Read-only
                    otherwise, and the page's own config is filtered on the way
                    out (see ``routes/app_pages.py``).

    identity        the caller presented a session cookie that resolves to a
                    live account. Reaches a short, explicitly listed set of
                    endpoints — not "public plus a bit of the API". A signed-in
                    visitor is *not* a weakened owner: ``/api/file``,
                    ``/api/agent`` and ``/api/recipes/<n>/run`` amount to running
                    code on this machine, and only the token gets those.

    token           everything else — the whole ``/api`` surface, ``/ws``, the
                    viewer, the SPA. Requires the server token.

The answer is one value, ``scope["state"]["frago_zone"]``, not a handful of
booleans. The critical bug this middleware was rewritten for came from two
predicates parsing the same request separately; adding "…and is it the identity
zone?" as a second boolean would drop the new zone silently into the ``else``
branch of every ``if is_public`` in the codebase. A route that meets a zone it
does not know about must raise, not guess.

A request is "trusted local" only when its peer is loopback *and* it carries no
proxy forwarding headers. That second half matters: a reverse proxy on the same
box also connects from 127.0.0.1, and without the header check every proxied
request from the internet would inherit the owner's trust. The rule can only
ever move a caller from trusted to untrusted — a forged ``X-Forwarded-For``
costs an attacker their own privileges, never gains them any.

The token lives in ``~/.frago/server-token`` (0600), generated on first use.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import logging
import os
import re
import secrets
from pathlib import Path

# Starlette's, not FastAPI's: this module is imported by the ASGI gate, which
# runs before anything FastAPI-shaped exists, and FastAPI's own subclasses this
# one anyway.
from starlette.exceptions import HTTPException as _HTTPException

logger = logging.getLogger(__name__)

TOKEN_PATH = Path.home() / ".frago" / "server-token"

# Headers a reverse proxy adds. Their presence means "this did not originate on
# this machine", whatever the socket says. The list is best-effort by nature —
# it is a heuristic over other people's software — which is exactly why it is
# not what a deployment relies on; see `peer_trust_disabled`.
_FORWARDING_HEADERS = (
    b"x-forwarded-for",
    b"x-forwarded-host",
    b"x-forwarded-proto",
    b"x-real-ip",
    b"forwarded",
    b"cf-connecting-ip",       # Cloudflare
    b"true-client-ip",         # Cloudflare Enterprise, Akamai
    b"x-client-ip",
    b"x-envoy-external-address",
    b"x-original-forwarded-for",
    b"via",                    # RFC 9110, set by Squid and others
    b"x-forwarded-server",     # Apache mod_proxy
    b"x-forwarded-port",
    b"x-forwarded-prefix",
    b"fly-client-ip",
    b"fastly-client-ip",
    b"x-azure-clientip",
    b"x-appengine-user-ip",
)

_LOOPBACK = ("127.", "::1", "::ffff:127.")

# /app/<name> and /app/<name>/<anything>
_APP_PATH = re.compile(r"^/app/(?P<name>[^/?#]+)(?P<rest>/.*)?$")

# A published page is a reading of data already on disk, so these are the only
# methods it needs. One consequence is deliberate and worth knowing: the gate
# sits outside CORSMiddleware, so a cross-origin preflight (OPTIONS) is refused
# with 401 and never reaches CORS at all. Published pages load same-origin and
# do not care; a third party trying to embed one or call the API from their own
# front end will see an auth error rather than a CORS error, which is honest —
# there is no cross-origin access to negotiate.
_PUBLIC_METHODS = frozenset({"GET", "HEAD"})

# The four zones. A value outside this set is a bug, and the readers below raise
# on one rather than falling back to the most permissive reading.
ZONES = ("local", "public", "identity", "token")

# The only thing an anonymous caller may POST. Matched as (method, exact path)
# pairs, never by prefix: a prefix would silently enrol every future
# ``/api/auth/<something>`` into the anonymous surface, which is how a public
# entry point gets added by accident rather than by decision.
#
# OPTIONS is deliberately absent. A cross-origin preflight is refused with 401
# and never reaches CORS, so a browser cannot be talked into sending a
# non-simple cross-site request here at all.
_ANON_POST = frozenset({("POST", "/api/auth/login")})

# What a signed-in visitor may reach beyond published pages. A closed list: a
# new endpoint lands in the token zone by default and gets in here only by
# editing this line, with the spec changed to match.
_IDENTITY_ENDPOINTS = frozenset({
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/password"),
    ("GET", "/api/auth/me"),
    ("HEAD", "/api/auth/me"),
    # What this caller may open. Read-only, and scoped to the caller by the
    # route itself — it answers "which pages are mine to see", never "who else
    # may see them".
    ("GET", "/api/auth/pages"),
    ("HEAD", "/api/auth/pages"),
})


# The page that serves as this server's front door. A visitor who lands on an
# identity-mode page without a session has nothing to act on — the JSON refusal
# below is written for a machine — so the gate sends them here instead, with
# ``?next=<recipe>`` so the portal can hand them back afterwards.
#
# Named rather than inferred: "the one page published in public mode" would be a
# guess that silently picks a different door the day a second public page is
# exposed. ``FRAGO_LOGIN_PORTAL=`` (empty) turns the redirect off entirely and
# restores the plain 401.
DEFAULT_LOGIN_PORTAL = "frago_login_portal"


def login_portal() -> str | None:
    """Which exposed page is the sign-in door, or None if there is not one."""
    raw = os.environ.get("FRAGO_LOGIN_PORTAL")
    name = DEFAULT_LOGIN_PORTAL if raw is None else raw.strip()
    return name or None


def token_path() -> Path:
    """Where the server token lives. ``FRAGO_TOKEN_FILE`` overrides, for tests."""
    override = os.environ.get("FRAGO_TOKEN_FILE")
    return Path(override).expanduser() if override else TOKEN_PATH


def read_token() -> str | None:
    """The current token, or None if this server has never minted one."""
    path = token_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def ensure_token() -> str:
    """Return the server token, creating it on first call.

    Written with 0600 before any content goes in, so the secret is never briefly
    world-readable on disk.

    Two callers racing must come away with the same token. The server mints one
    at startup while a person runs ``frago server token`` to read it — that race
    is the normal case, not a corner one, and its old failure mode was a person
    holding a token that had never reached disk, seeing 401s, and having no
    reason to suspect the mint.

    Written in full to a temporary file and then *linked* into place. ``O_EXCL``
    on the real path is not enough on its own: it makes the file exist while it
    is still empty, so the loser of the race reads nothing back. ``os.link``
    publishes a file that already has its contents, and fails outright if
    another caller published first.
    """
    existing = read_token()
    if existing:
        return existing

    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)

    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
        try:
            os.link(str(tmp), str(path))
        except FileExistsError:
            # Someone else published first; theirs is the real one.
            return read_token() or token
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()

    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    return token


def rotate_token() -> str:
    """Throw the current token away and mint a new one."""
    path = token_path()
    if path.exists():
        path.unlink()
    return ensure_token()


def _headers(scope: dict) -> dict[bytes, bytes]:
    return {k.lower(): v for k, v in scope.get("headers") or []}


def _is_proxied(headers: dict[bytes, bytes]) -> bool:
    return any(h in headers for h in _FORWARDING_HEADERS)


_NEGATIVE = frozenset({"", "0", "false", "no", "off"})


def _enabled(name: str, *, default: bool) -> bool:
    """Read a boolean switch so that typos fail towards the safer answer.

    A whitelist of accepted spellings is the wrong shape for a security switch:
    ``FRAGO_BEHIND_PROXY=on`` would parse as "not set" and silently restore the
    hole it exists to close (found by audit 20260817). Only the explicit
    negatives turn something off; everything else the operator bothered to type
    counts as on.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _NEGATIVE


def in_container() -> bool:
    """Whether this process is running inside a container.

    A container is a server by construction, and its "private network" is the
    bridge: with ``docker -p``, every forwarded request arrives from the gateway
    address, which is RFC1918. Trusting the LAN there means trusting the entire
    internet through one hop, which is why the default flips here.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "lxc"))


def lan_is_trusted() -> bool:
    """Whether other machines on this network count as "here".

    frago binds ``0.0.0.0`` by default and ``frago server status`` prints the
    LAN URLs it can be reached at — opening the workbench from your phone is a
    feature the tool advertises, and the CORS policy already declares private
    ranges trusted. Defaulting this off would silently break every install that
    uses it, to protect a deployment that the docs already tell you to bind to
    loopback.

    So it defaults on, and a server deployment turns it off:
    ``FRAGO_TRUST_LAN=0`` alongside ``FRAGO_SERVER_HOST=127.0.0.1``.

    Inside a container the default inverts. There is no home network in a
    container — the private address every request seems to come from is the
    bridge gateway, so "trust the LAN" would mean "trust whatever the port
    publish forwards", i.e. the internet.
    """
    return _enabled("FRAGO_TRUST_LAN", default=not in_container())


def _peer_zone(scope: dict) -> str:
    """Where the caller sits: ``loopback``, ``private``, ``public``, ``unknown``.

    Parsed with ``ipaddress`` rather than string prefixes, so that
    ``::ffff:127.0.0.1`` is recognised as loopback and ``127.0.0.1.evil.com`` —
    or anything else that merely starts with the right characters — is not.

    The address here is not always the socket's. uvicorn runs its own
    ``ProxyHeadersMiddleware`` by default, which rewrites ``scope["client"]``
    from ``X-Forwarded-For`` when the connection comes from a trusted hop —
    loopback, by default. That works in our favour twice over: a proxied caller
    surfaces as the public address they really are (a second, independent lock
    behind the header check), and the denial log records who was actually
    knocking instead of a wall of 127.0.0.1. It is also why a request that
    "obviously came from loopback" can be classified public; anyone debugging
    that should look at uvicorn before looking here.

    "Private" here is whatever ``ipaddress`` says, which is narrower than people
    expect in one direction and wider in another. CGNAT space (100.64.0.0/10) —
    where Tailscale addresses live — is *not* private on Python 3.13+, so a
    tailnet peer is treated as a public caller and needs the token. Link-local
    (169.254/16) *is* included, which is why it is trusted alongside RFC1918.
    """
    import ipaddress

    client = scope.get("client")
    if not client:
        # No peer information (unix socket, some ASGI transports). Refuse to
        # guess in the generous direction.
        return "unknown"
    try:
        ip = ipaddress.ip_address(str(client[0]))
    except ValueError:
        return "unknown"
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_unspecified:
        return "unknown"
    if ip.is_loopback:
        return "loopback"
    if ip.is_private or ip.is_link_local:
        return "private"
    return "public"


def peer_trust_disabled() -> bool:
    """Whether this server refuses to infer trust from the peer address at all.

    Everything else here reasons backwards from the socket: loopback means the
    owner, unless a forwarding header says a proxy put it there. That inference
    is sound on a personal machine and only as good as the header list on a
    deployed one — a proxy that sets none of them, or sets one nobody thought
    to list, hands every visitor the owner's seat. Failing open on somebody
    else's default configuration is not a risk worth carrying.

    So a deployment stops guessing and says so: ``FRAGO_BEHIND_PROXY=1``. Then
    the peer address grants nothing, the public zone is the only anonymous
    surface left, and the token is the only way into the rest — no matter which
    headers the proxy in front does or does not set.
    """
    return _enabled("FRAGO_BEHIND_PROXY", default=False)


def _peer_is_trusted(scope: dict) -> bool:
    if peer_trust_disabled():
        return False
    zone = _peer_zone(scope)
    if zone == "loopback":
        return True
    return zone == "private" and lan_is_trusted()


def _presented_token(scope: dict, headers: dict[bytes, bytes]) -> str | None:
    """Pull a token out of the request, in order of preference.

    A browser cannot set headers on a WebSocket handshake, so ``?token=`` is
    accepted there. It is deliberately *not* accepted on plain HTTP: query
    strings end up in proxy access logs, and the HTTP callers that matter (the
    CLI, another frago) can all set a header.
    """
    auth = headers.get(b"authorization")
    if auth:
        raw = auth.decode("latin-1", "replace").strip()
        if raw.lower().startswith("bearer "):
            return raw[7:].strip()
    direct = headers.get(b"x-frago-token")
    if direct:
        return direct.decode("latin-1", "replace").strip()
    if scope.get("type") == "websocket":
        from urllib.parse import parse_qs

        qs = parse_qs(scope.get("query_string", b"").decode("latin-1", "replace"))
        values = qs.get("token")
        if values:
            return values[0]
    return None


def _token_ok(presented: str | None) -> bool:
    if not presented:
        return False
    expected = read_token()
    if not expected:
        # No token file means no remote access has ever been configured. Fail
        # closed: a server with no token is a server nobody may reach remotely.
        return False
    return hmac.compare_digest(presented, expected)


def _query_values(scope: dict, key: str) -> list[str]:
    """Every value given for one query parameter.

    Deliberately Starlette's parser, the same one the route handlers use. An
    earlier version used ``urllib.parse.parse_qs`` here and took ``values[0]``
    while the route took the *last* value via ``QueryParams.get``; the two read
    ``?key=public&key=private`` as different slots, so the gate authorised one
    and the route served the other. Any authorisation that parses a request
    differently from the code it is authorising is a bypass waiting to be found.
    """
    from starlette.datastructures import QueryParams

    return QueryParams(scope.get("query_string", b"")).getlist(key)


def _path_is_safe(path: str) -> bool:
    """Whether this path is free of dot segments and dotfiles.

    uvicorn percent-decodes into ``scope["path"]`` but does not collapse dot
    segments, so ``/app/<published>/../../api/file`` matches an ``/app`` prefix
    and would be waved through — today it dies one layer later, in the route's
    ``_resolve_within``, which is one lock doing the work of two. Refusing the
    shape at the gate keeps the two independent (audit 20260817, L-1).

    No dotfiles either. A recipe's ``assets/`` is written for the owner's
    machine, and ``.env``, ``.git/`` and editor backups end up in it; the audit
    read ``sk-SENTINEL-LENDER-ENV`` straight out of a published page this way.

    Shared by every anonymous and identity path, so a new entry point cannot be
    added without this lock attached.
    """
    segments = path.split("/")
    if any(seg in ("..", ".") for seg in segments):
        return False
    return not any(seg.startswith(".") for seg in segments if seg)


def classify_public(scope: dict) -> str | None:
    """The slot an anonymous caller may be served, or None to refuse.

    Four conditions, all required: the path addresses a recipe page, the recipe
    is on the published list, that entry is in ``public`` mode, and the method
    only reads. The requested slot must also be the published one — a recipe may
    hold a public dashboard in one slot and a private working set in another.

    The mode is read *here*, not left to the identity check further down. Being
    published is no longer the same question as being anonymously readable: an
    identity-mode page exists precisely so that anonymous visitors cannot read
    it, and a version of this function that only asked "is it published?" would
    let every one of them through before the identity check ever ran.

    Returning the slot rather than a boolean is what keeps the decision honest:
    the route no longer re-derives which slot to open from the URL, it is handed
    the one that was actually authorised.
    """
    if scope.get("type") != "http":
        return None
    if (scope.get("method") or "").upper() not in _PUBLIC_METHODS:
        return None

    path = scope.get("path") or ""
    match = _APP_PATH.match(path)
    if not match:
        return None

    if not _path_is_safe(path):
        return None

    from frago.recipes.publish import MODE_PUBLIC, published_entry

    entry = published_entry(match.group("name"))
    if entry is None or entry["mode"] != MODE_PUBLIC:
        return None
    slot = str(entry["slot"])

    requested = _query_values(scope, "key")
    if len(requested) > 1:
        # Ambiguity is not something to resolve, it is something to refuse.
        return None
    # `?key=` with nothing after it is the default slot to the route
    # (`key or DEFAULT_SLOT`), so it must be the default slot here too. Any
    # reading the gate and the route do not share is a bypass in waiting.
    if requested and requested[0] and requested[0] != slot:
        return None
    return slot


def _cookie(headers: dict[bytes, bytes], name: str) -> str | None:
    """One cookie's value, parsed by hand.

    ``http.cookies.SimpleCookie`` silently drops the whole header when any pair
    in it is malformed, which would let a page set a junk cookie and log the
    visitor out for reasons nobody could reproduce.
    """
    raw = headers.get(b"cookie")
    if not raw:
        return None
    for part in raw.decode("latin-1", "replace").split(";"):
        key, _, value = part.partition("=")
        if key.strip() == name:
            return value.strip()
    return None


def _resolve_identity(headers: dict[bytes, bytes]) -> str | None:
    """The account this request's cookie belongs to, or None.

    Called once, here, for every request. Routes are told who is in front of
    them; they never read the cookie themselves. The identity spec's first
    principle is that the gate is the only place a request is interpreted —
    the critical bug it was written after came from a second reader disagreeing
    with the first.

    Resolved in every zone, not only the identity one, so that the owner's own
    browser can use ``/api/auth/me``. It is the *zone* that decides which slot a
    request opens, never the mere presence of an identity: the local and token
    zones keep ``?key=``, which is how ``frago recipe publish --slot`` and
    ``app_state.page_url()`` have always worked.
    """
    token = _cookie(headers, "frago_sid")
    if not token:
        return None
    from frago.server.identity import resolve_session

    try:
        session = resolve_session(token)
    except Exception:  # a broken table must not become a 500 on every request
        logger.exception("could not resolve a login session")
        return None
    return session.identity if session else None


def classify_identity(scope: dict, identity: str) -> tuple[bool, str | None]:
    """``(reachable, slot)`` for a signed-in visitor.

    The listed endpoints are reachable with no slot. An identity-mode page this
    visitor is allowed on is reachable with the visitor's own id as the slot —
    never a slot they asked for. Everything else is out, including the whole of
    ``/api`` beyond the four auth calls.
    """
    if scope.get("type") != "http":
        return False, None
    method = (scope.get("method") or "").upper()
    path = scope.get("path") or ""
    if not _path_is_safe(path):
        return False, None

    if (method, path) in _IDENTITY_ENDPOINTS:
        return True, None

    # The identity zone's one write entrance. It has to be judged before the
    # read-only method check below, and the suffix is pinned to exactly "/run"
    # rather than left to the `_APP_PATH` match: that regex admits any suffix,
    # and a rule shaped "POST and the regex matched" would silently enrol every
    # future `/app/<x>/<y>` POST route into the identity zone. Entrances are
    # added one at a time, visibly.
    if method == "POST":
        match = _APP_PATH.match(path)
        if match and (match.group("rest") or "") == "/run":
            return _judge_app_path(scope, match, identity)
        return False, None

    if method not in _PUBLIC_METHODS:
        return False, None
    match = _APP_PATH.match(path)
    if not match:
        return False, None
    return _judge_app_path(scope, match, identity)


def _judge_app_path(scope: dict, match, identity: str) -> tuple[bool, str | None]:
    """Whether this signed-in visitor may touch this page, and as which slot.

    Shared by the read entrance and the run entrance on purpose. They admit
    different methods, but "may this person touch this page at all" has to be
    one answer in one place — two copies of a four-state comparison is two
    chances for the write side to be more generous than the read side.
    """
    # A signed-in visitor never names a slot. `?key=` is the owner's control for
    # switching data on their own machine; honouring it here would hand the
    # decision back to the visitor, which is the exact shape of the critical
    # bug this design exists to prevent.
    if _query_values(scope, "key"):
        return False, None

    from frago.recipes.publish import MODE_IDENTITY, allows, published_entry

    # Three questions, all required: published at all, published *this* way, and
    # published to *this person*. Being published used to be the whole test here,
    # which meant an allow list could be written and have no effect — the gate
    # would never have looked at it.
    #
    # A public-mode page is not served from this branch: `classify_public` runs
    # first in the middleware and admits it as anonymous traffic. Refusing it
    # here is not a narrowing, it is saying which branch owns which mode.
    entry = published_entry(match.group("name"))
    if entry is None or entry["mode"] != MODE_IDENTITY:
        return False, None

    # Off the list is not a different answer from unpublished — it is the same
    # answer. `_reject` sends the same 401 either way, and it must stay that
    # way: a 403 here would confirm to an outsider that the page exists and that
    # somebody, somewhere, is on its list.
    if not allows(entry, identity):
        return False, None
    return True, identity


def _anon_post_allowed(scope: dict) -> bool:
    """Whether this is the one POST an anonymous caller may make.

    Until the identity spec, anonymous traffic could only make this server read
    files off disk. This single entry point is what changes that — it computes
    scrypt and writes two tables — so it is listed one endpoint at a time, with
    the same dot-segment refusal every other anonymous path carries.
    """
    if scope.get("type") != "http":
        return False
    path = scope.get("path") or ""
    if not _path_is_safe(path):
        return False
    return ((scope.get("method") or "").upper(), path) in _ANON_POST


def sign_in_redirect(scope: dict, headers: dict[bytes, bytes]) -> str | None:
    """Where to send a signed-out browser that asked for a page needing a sign-in.

    Returns None — meaning "answer with the plain 401" — for everything that is
    not a person looking at a page they could get into by signing in. Four
    conditions, each closing a way this could go wrong:

    * **Only a top-level HTML navigation.** The page's own ``fetch`` calls ask
      for JSON; bouncing one of those to the portal would hand the front end a
      login page where it expects data, and the failure would surface as a parse
      error somewhere unrelated. ``Accept: text/html`` is what separates the two.
    * **Only identity-mode pages.** A public page that refused for some other
      reason, or a path that is not a page at all, has nothing to gain from
      signing in — sending them to a login form would be a lie about why they
      were refused.
    * **Never the portal itself**, and never when the portal is not anonymously
      readable: both are redirect loops, one immediate, one dressed up as a
      second 401.
    * **The target is always this site.** The recipe name has already been
      through ``published_entry``'s validation (letters, digits, dot, dash,
      underscore), so nothing here can be talked into pointing elsewhere.
    """
    if scope.get("type") != "http":
        return None
    if (scope.get("method") or "").upper() not in _PUBLIC_METHODS:
        return None

    accept = headers.get(b"accept", b"").decode("latin-1", "replace").lower()
    if "text/html" not in accept:
        return None

    path = scope.get("path") or ""
    if not _path_is_safe(path):
        return None
    match = _APP_PATH.match(path)
    if not match:
        return None
    name = match.group("name")

    portal = login_portal()
    if not portal or name == portal:
        return None

    from frago.recipes.publish import MODE_IDENTITY, MODE_PUBLIC, published_entry

    entry = published_entry(name)
    if entry is None or entry["mode"] != MODE_IDENTITY:
        return None
    door = published_entry(portal)
    if door is None or door["mode"] != MODE_PUBLIC:
        return None
    return f"/app/{portal}/?next={name}"


async def _send_to_sign_in(scope: dict, send, target: str) -> None:
    """Move a signed-out visitor to the sign-in page.

    ``no-store`` because the answer depends on whether this particular caller
    has a session: a cached redirect would keep bouncing them to the login page
    after they had signed in.
    """
    logger.info("sending a signed-out visitor from %s to %s", scope.get("path"), target)
    await send(
        {
            "type": "http.response.start",
            "status": 302,
            "headers": [
                (b"location", target.encode("latin-1")),
                (b"content-length", b"0"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def _reject(scope: dict, send, reason: str) -> None:
    # A 256-bit token is not going to be guessed, so this line is not about
    # stopping the attempt — it is so that an attempt leaves a mark. Without it,
    # probing a deployed frago costs the prober nothing and tells the owner
    # nothing: no forensics after the fact, no signal to alert on.
    client = scope.get("client")
    logger.warning(
        "access denied: %s %s from %s",
        scope.get("method") or scope.get("type"),
        scope.get("path"),
        f"{client[0]}:{client[1]}" if client else "unknown",
    )

    if scope.get("type") == "websocket":
        await send({"type": "websocket.close", "code": 4401})
        return
    body = json.dumps(
        {
            "error": "unauthorized",
            "detail": reason,
            "hint": "send Authorization: Bearer <token>; get it with `frago server token`",
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class AccessZoneMiddleware:
    """Sort every request into local / public / identity / token.

    Written as raw ASGI rather than ``BaseHTTPMiddleware`` on purpose:
    ``BaseHTTPMiddleware`` never sees WebSocket scopes, and ``/ws`` streams the
    same session data the REST API guards.
    """

    def __init__(self, app):
        self.app = app

    def _admit(self, scope: dict, zone: str, slot: str | None, identity: str | None) -> None:
        """Record the decision. This is the only place these keys are written.

        ``frago_slot`` is the whole answer to "which slot is this request for"
        in the public and identity zones — the route is handed it rather than
        re-deriving it from the URL, because the two derivations drifting apart
        is precisely how ``?key=public&key=private`` read one slot at the gate
        and served another at the route.
        """
        state = scope.setdefault("state", {})
        state["frago_zone"] = zone
        state["frago_slot"] = slot
        state["frago_identity"] = identity
        # Kept for the routes that still ask the old question. Phase 2 removes
        # the last readers; see `is_public_request`.
        state["frago_public"] = zone == "public"
        state["frago_public_slot"] = slot if zone == "public" else None

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        proxied = _is_proxied(headers)
        identity = _resolve_identity(headers)

        if _peer_is_trusted(scope) and not proxied:
            # The owner's own machine. Their `?key=` still chooses the slot, so
            # no `frago_slot` is set here on purpose.
            self._admit(scope, "local", None, identity)
            await self.app(scope, receive, send)
            return

        slot = classify_public(scope)
        if slot is not None:
            self._admit(scope, "public", slot, identity)
            await self.app(scope, receive, send)
            return

        if identity is not None:
            reachable, identity_slot = classify_identity(scope, identity)
            if reachable:
                self._admit(scope, "identity", identity_slot, identity)
                await self.app(scope, receive, send)
                return
            # Not reachable as an identity — but a cookie must not *cost* the
            # caller anything either. Fall through to the token check: the
            # owner's browser may hold both.

        if _anon_post_allowed(scope):
            self._admit(scope, "public", None, identity)
            await self.app(scope, receive, send)
            return

        if _token_ok(_presented_token(scope, headers)):
            self._admit(scope, "token", None, identity)
            await self.app(scope, receive, send)
            return

        # Nobody may have this. If it is a person in a browser looking at a page
        # a sign-in would open, move them to the door rather than showing them a
        # refusal written for a machine.
        target = sign_in_redirect(scope, headers)
        if target is not None:
            await _send_to_sign_in(scope, send, target)
            return

        await _reject(scope, send, "this endpoint is not public")


def deployment_warning() -> str | None:
    """The one misconfiguration that quietly hands the server away, if present.

    Binding to loopback is a deliberate act — the default is ``0.0.0.0`` — and
    almost nobody does it except to put a reverse proxy in front. That is
    exactly the shape where trusting the peer address fails: a proxy connects
    from 127.0.0.1 like the owner does, and if it forwards at layer 4 (an SSH
    tunnel, ``docker -p``, socat, or an nginx ``proxy_pass`` with no
    ``proxy_set_header``) there is no header to give it away either. Verified in
    the 20260817 audit: through such a forwarder, ``POST /api/agent`` reached
    the route with no token asked for.

    Warned about rather than fixed automatically, because binding to loopback is
    also how someone says "I don't want this on my LAN" on their own laptop, and
    silently demanding a token from their own CLI would be its own bad surprise.

    The trigger is deliberately not "bound to loopback". That was the first
    version of this check and the 20260817 audit put a hole straight through it:
    a container publishes its port on 0.0.0.0, every forwarded request arrives
    from the bridge gateway, and the check stayed quiet about the one shape most
    likely to be on the internet. The question to ask is not how the socket is
    bound — it is whether this server is still deciding who to trust by looking
    at an address, in a situation where that address may not mean what it says.
    """
    from frago.server.daemon import get_server_host

    if peer_trust_disabled():
        # Saying "there is a proxy in front" without saying *which* leaves the
        # login rate limiter with no address it can trust: uvicorn rewrites the
        # peer from a header this server has not agreed to believe. The limiter
        # declares itself unavailable rather than counting wrong in either
        # direction, and the shared passphrase has to cover for it.
        from frago.server.identity import signup_gate, trusted_proxies

        if not trusted_proxies():
            missing_gate = signup_gate() is None
            return (
                "SECURITY: FRAGO_BEHIND_PROXY is set but FRAGO_TRUSTED_PROXIES is "
                "not, so no address on an incoming request can be trusted and "
                "per-IP rate limiting on /api/auth/login is switched off. Set "
                "FRAGO_TRUSTED_PROXIES to your proxy's address (and pass the same "
                "list to uvicorn's forwarded_allow_ips)"
                + (
                    ", or set FRAGO_SIGNUP_GATE — until one of the two is set, no "
                    "new accounts can be created."
                    if missing_gate
                    else "; FRAGO_SIGNUP_GATE is now mandatory and cannot be turned off."
                )
            )
        return None

    host = (get_server_host() or "").strip()
    bound_to_loopback = host in ("127.0.0.1", "localhost", "::1")
    containerised = in_container()
    # Not `lan_is_trusted()`: on a personal machine that is the documented
    # normal state, and a warning printed on every install is a warning nobody
    # reads by the time it matters.
    if not (bound_to_loopback or containerised):
        return None

    shape = (
        "this server is running in a container"
        if containerised
        else "this server is bound to loopback (a reverse-proxy setup)"
    )

    return (
        f"SECURITY: {shape} but FRAGO_BEHIND_PROXY is not set, so callers are "
        "still trusted by their address. A proxy that forwards without "
        "X-Forwarded-* headers — an SSH tunnel, docker -p, socat, or nginx "
        "proxy_pass without proxy_set_header — makes every visitor look local, "
        "and the whole API is open to them. If this machine is serving anyone "
        "but you, set FRAGO_BEHIND_PROXY=1. See docs/server-deployment.md."
    )


def harden_home() -> None:
    """Make frago's own files unreadable to other accounts on this machine.

    Doing this only at write time leaves whatever is already on disk exactly as
    it was — and the files that matter here were written by earlier versions
    that followed the umask. A server is also where a second Unix account is
    most likely to exist, so the repair belongs at startup, not in a release
    note nobody runs.

    ``server.log`` needs it on every start for a second reason: a rotating
    handler creates each new file through plain ``open()``, so every rotation
    puts the mode back to whatever the umask says.
    """
    home = Path.home() / ".frago"
    if not home.is_dir():
        return

    with contextlib.suppress(OSError):
        home.chmod(0o700)

    # config.yaml holds the frago cloud OAuth access and refresh tokens
    # (frago.cloud.config.save_tokens writes them there), so it is a credential
    # file even though its name suggests plain settings.
    for name in (
        "server.log",
        "config.json",
        "config.yaml",
        "published.json",
        "server-token",
        "remotes.json",
        # Password hashes. Written 0600, repaired here for tables that a future
        # tool, an editor, or a restore from backup left wide open.
        "users.json",
        "users.json.lock",
    ):
        with contextlib.suppress(OSError):
            target = home / name
            if target.is_file():
                target.chmod(0o600)

    # Login sessions: possession of a session file is possession of the account
    # it names, so the directory is as sensitive as the token file.
    sessions = home / "login-sessions"
    if sessions.is_dir():
        with contextlib.suppress(OSError):
            sessions.chmod(0o700)
        for path in sessions.glob("*.json"):
            if path.is_symlink():
                continue
            with contextlib.suppress(OSError):
                path.chmod(0o600)

    # "users" is the identity root: one subtree per account, holding that
    # account's slots and its own output. A recipe writing its own slot can
    # never land on a person's file, because the two roots do not intersect on
    # disk; both get the same treatment. It is listed by name, so a root added
    # later and not added here would simply never be tightened.
    #
    # "app-state-users" is that root's previous layout. It stays on the list
    # because the migration runs before this and may have left a file it could
    # not move — and an unmovable file is exactly the one still sitting there
    # world-readable.
    for state_root in ("app-state", "users", "app-state-users"):
        _harden_state_dir(home / state_root)


def _harden_state_dir(app_state: Path) -> None:
    if app_state.is_dir():
        with contextlib.suppress(OSError):
            app_state.chmod(0o700)
        for path in app_state.rglob("*"):
            # Never through a link. chmod follows symlinks, so a recipe that
            # linked a shared directory in here would have that directory's
            # permissions rewritten out from under whatever else uses it —
            # this function tightens frago's own files, not other people's.
            if path.is_symlink():
                continue
            with contextlib.suppress(OSError):
                path.chmod(0o700 if path.is_dir() else 0o600)


def _state_of(request_or_scope) -> dict:
    scope = getattr(request_or_scope, "scope", request_or_scope)
    return (scope.get("state") or {}) if isinstance(scope, dict) else {}


def zone_of(request_or_scope) -> str:
    """Which zone the gate put this request in. The single source of truth.

    Raises on a value that is not a zone. That is the point: a reader that
    quietly treats an unrecognised zone as "not public" would serve a signed-in
    visitor the owner's unfiltered view, which is how the filtering fixes get
    undone by a zone added later.

    A request that never met the middleware — a unit test calling a route
    directly, an internal call — reads as ``local``, which is what it is.
    """
    zone = _state_of(request_or_scope).get("frago_zone")
    if zone is None:
        return "local"
    if zone not in ZONES:
        raise ValueError(f"unknown access zone {zone!r}; expected one of {ZONES}")
    return str(zone)


def slot_for(request_or_scope) -> str | None:
    """The slot the gate authorised, or None when the caller picks their own.

    None in the local and token zones on purpose: there the ``?key=`` in the URL
    is a feature the owner uses, and the route reads it as it always has. In the
    public and identity zones this is the only answer, and reading the query
    string instead is the bug.
    """
    zone = zone_of(request_or_scope)
    if zone in ("public", "identity"):
        return _state_of(request_or_scope).get("frago_slot")
    return None


def identity_of(request_or_scope) -> str | None:
    """The signed-in account behind this request, if there is one.

    Present in every zone — the owner's browser can hold a cookie too — so it
    must not be used to decide which slot to open. Use ``slot_for``.
    """
    return _state_of(request_or_scope).get("frago_identity")


class VisitorSafeHTTPException(_HTTPException):
    """A refusal that was written to be read by a stranger.

    By default every 4xx served to anyone but the owner is flattened to a bare
    404, because route handlers say useful things — which absolute path was
    missing, which slot declared no data — and those describe this machine.

    A few refusals are the opposite: the visitor cannot proceed without them and
    they mention nothing but the caller's own request. "This parameter is not one
    I accept" and "you already have a run going" are the request's own shape
    reflected back. Flattening those leaves a page whose button fails with no way
    to find out why.

    Raising this type is a claim, and the claim has to hold: the message must
    name only parameters, limits and states — NEVER a path, a recipe the caller
    did not name, or the existence of anything they could not already see.
    """


def is_owner_request(request_or_scope) -> bool:
    """Whether this caller is the owner, and may see a recipe's state unfiltered.

    The question a route asks before deciding how much to reveal. Note the
    shape: "is this the owner", not "is this public" — a signed-in visitor is
    not the owner, so an unfiltered view must not reach them just because they
    are not anonymous.
    """
    return zone_of(request_or_scope) in ("local", "token")


def is_public_request(request) -> bool:
    """Deprecated. Whether the gate put this request in the anonymous zone.

    Kept because ``routes/app_pages.py`` and the 4xx scrubber in ``app.py``
    still ask it; Phase 2 of the identity spec replaces both with
    ``is_owner_request`` / ``slot_for``. Do not add callers: as a boolean it
    cannot distinguish "signed-in visitor" from "owner", and everything that
    turns on that distinction gets it wrong.
    """
    return zone_of(request) == "public"


def public_slot(request) -> str | None:
    """Deprecated. The one slot this anonymous request was authorised for.

    Superseded by ``slot_for``, which answers for the identity zone as well.
    """
    return slot_for(request) if zone_of(request) == "public" else None
