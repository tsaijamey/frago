"""Signing in, signing out, and changing a password.

Four endpoints, and one of them — ``POST /api/auth/login`` — is the first
anonymous entry point in this server that *does* something. Everything the
public zone could reach before this file existed was a read of a file already on
disk; login computes scrypt and writes two tables. That change of character is
why the checks below are written out here rather than left to framework
defaults:

    Content-Type    all three POSTs demand ``application/json``. An HTML form
                    cannot send that content type, and a cross-site fetch that
                    sets it needs a preflight — which the gate answers with 401,
                    because OPTIONS is not on its anonymous list. Together those
                    two facts are what stop a page on another origin from
                    logging a visitor in *as the attacker* and quietly collecting
                    everything they then do.

    Origin          a login request that carries a cross-origin ``Origin`` is
                    refused outright. One line, no framework behaviour relied on.

    rate limit      spent before ``authenticate`` is called, because
                    ``authenticate`` is where scrypt happens. A limiter that runs
                    after the expensive part is a counter, not a limit.

The routes never read the session cookie. The gate resolved it once, before any
routing happened, and wrote the answer into the request scope; ``identity_of``
reads that. A second reader is exactly the shape of bug the identity spec was
written after.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request, Response

from frago.server import identity as ident
from frago.server.security import identity_of

logger = logging.getLogger(__name__)

router = APIRouter()

# What each refusal from `identity.py` means over HTTP. A closed mapping: a
# reason nobody listed becomes a 400 rather than leaking as a 500 with a
# traceback into the public zone.
_STATUS_FOR = {
    "invalid_email": 400,
    "weak_password": 400,
    "bad_credentials": 401,
    "rate_limited": 429,
    "gate_required": 403,
    "account_limit": 503,
    "no_such_user": 401,
    "session_failed": 503,
}


def _fail(status: int, reason: str, detail: str) -> Response:
    return Response(
        content=json.dumps({"error": reason, "detail": detail}),
        status_code=status,
        media_type="application/json",
    )


def _ok(payload: dict) -> Response:
    return Response(content=json.dumps(payload), media_type="application/json")


async def _json_body(request: Request) -> dict:
    """The request's JSON body, or raise the right refusal.

    ``application/json`` is required rather than merely accepted. This is the
    first of the four locks against login CSRF and it is deliberately explicit —
    a framework that starts accepting form bodies one release later would open
    the hole silently.
    """
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise _Refusal(415, "unsupported_media_type", "send this as application/json")
    raw = await request.body()
    # A body big enough to matter is not a login attempt.
    if len(raw) > 64 * 1024:
        raise _Refusal(413, "too_large", "that body is too large for a login")
    try:
        parsed = json.loads(raw or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise _Refusal(400, "bad_request", "that body is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise _Refusal(400, "bad_request", "expected a JSON object")
    return parsed


class _Refusal(Exception):
    def __init__(self, status: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.reason = reason
        self.detail = detail

    def response(self) -> Response:
        return _fail(self.status, self.reason, self.detail)


def _origin_is_foreign(request: Request) -> bool:
    """Whether this request declares an origin that is not this site.

    Absent ``Origin`` is not foreign: the CLI, curl and same-origin GETs send
    none, and treating that as hostile would break every non-browser caller
    while stopping nothing — a browser is precisely the thing that always sets
    it on a cross-site POST.
    """
    origin = (request.headers.get("origin") or "").strip()
    if not origin:
        return False
    host = (request.headers.get("host") or "").strip()
    if not host:
        return True
    scheme = (request.url.scheme or "http").lower()
    allowed = {f"{scheme}://{host}"}
    if ident.public_https():
        # The operator declared the public face is HTTPS. Behind a TLS-
        # terminating proxy the browser says https:// while this process may
        # still see http://, and that mismatch is the deployment working as
        # designed rather than an attack.
        allowed.add(f"https://{host}")
    return origin.lower().rstrip("/") not in allowed


def _issue_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        ident.COOKIE_NAME,
        token,
        max_age=ident.session_ttl(),
        path="/",
        httponly=True,
        samesite="lax",
        secure=ident.cookie_is_secure(request.scope),
    )


def _identity_payload(user_id: str) -> dict:
    user = ident.find_user_by_id(user_id)
    return {
        "identity": user_id,
        # Stated on every response that carries it, because everything downstream
        # of this API is entitled to know that nobody ever checked this address.
        "email": user.email if user else "",
        "emailVerified": False,
    }


@router.post("/auth/login")
async def login(request: Request) -> Response:
    """Sign in, creating the account if this address has never been seen.

    The only anonymous POST this server answers.
    """
    try:
        body = await _json_body(request)
    except _Refusal as refusal:
        return refusal.response()

    if _origin_is_foreign(request):
        # A cross-site page submitting a login would leave the visitor signed in
        # as the attacker, writing their session data into the attacker's slot.
        return _fail(403, "cross_origin", "cross-origin logins are refused")

    address = ident.client_ip(request.scope)
    if not ident.allow_login(address):
        return _fail(429, "rate_limited", "too many login attempts; wait a while")

    if ident.public_https() and (request.url.scheme or "").lower() not in ("https", "wss"):
        # Issuing a session here would put a working credential on a link the
        # operator has already told us is not the one visitors use. Better no
        # session than one that travels in the clear.
        return _fail(
            403,
            "https_required",
            "this server is declared HTTPS; it will not issue a session over plain HTTP",
        )

    email = str(body.get("email") or "")
    password = str(body.get("password") or "")
    gate = body.get("gate")

    try:
        with ident.acting_for(address):
            user, outcome = ident.authenticate(
                email, password, gate=str(gate) if gate is not None else None
            )
        token = ident.create_session(user.id)
    except ident.IdentityError as error:
        return _fail(_STATUS_FOR.get(error.reason, 400), error.reason, error.detail)

    payload = _identity_payload(user.id)
    payload["created"] = outcome == "created"
    response = _ok(payload)
    _issue_cookie(response, request, token)
    return response


@router.post("/auth/logout")
async def logout(request: Request) -> Response:
    """End this session. The cookie goes with it."""
    try:
        await _json_body(request)
    except _Refusal as refusal:
        return refusal.response()

    who = identity_of(request)
    if who is None:
        return _fail(401, "not_signed_in", "no session to end")

    token = request.cookies.get(ident.COOKIE_NAME)
    if token:
        ident.revoke_session(token)
    response = _ok({"ok": True})
    response.delete_cookie(ident.COOKIE_NAME, path="/")
    return response


@router.post("/auth/password")
async def change_password(request: Request) -> Response:
    """Change your own password, which logs every other device out.

    There is no recovery flow in this design, so this endpoint is the only
    self-service answer to "I think my cookie was stolen". If it left other
    sessions alive it would not be an answer at all — hence: revoke everything,
    then issue one fresh session for the request in hand, so the person doing
    the right thing is not punished by being logged out mid-action.
    """
    try:
        body = await _json_body(request)
    except _Refusal as refusal:
        return refusal.response()

    who = identity_of(request)
    if who is None:
        return _fail(401, "not_signed_in", "sign in first")

    current = str(body.get("current_password") or "")
    new_password = str(body.get("new_password") or "")

    if not ident.verify_user_password(who, current):
        return _fail(401, "bad_credentials", "your current password is wrong")

    try:
        ident.set_password(who, new_password)
        token = ident.create_session(who)
    except ident.IdentityError as error:
        return _fail(_STATUS_FOR.get(error.reason, 400), error.reason, error.detail)

    response = _ok(_identity_payload(who))
    _issue_cookie(response, request, token)
    return response


@router.get("/auth/me")
async def whoami(request: Request) -> Response:
    """Who the gate says is asking. Reads the decision, never the cookie."""
    who = identity_of(request)
    if who is None:
        return _fail(401, "not_signed_in", "no session")
    return _ok(_identity_payload(who))
