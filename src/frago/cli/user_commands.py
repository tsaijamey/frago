"""Who has been here, and what the owner can do about it.

The server's fourth zone lets strangers sign in and get their own slot of a
recipe's data. That is a table of people the owner never met, on a machine the
owner is responsible for — so there has to be a way to look at it, reset a
password, suspend someone, and cut a session short. That is this module, and
nothing else: identities exist to pick a slot, so there are no roles to grant
and no permissions to edit.

Three "user"-shaped things live in this CLI and they are not the same thing:

    frago whoami          this frago's own frago-cloud account (outbound)
    frago session …       agent transcripts on this machine (nothing to do with logins)
    frago user …          people who signed in to *this server's* published pages

The third one is here. Login sessions hang under ``frago user session``
deliberately: ``frago session`` is taken, and click's ``add_command`` replaces a
same-named command without a word, so mounting them there would delete the
agent-transcript commands silently. ``tests/unit/cli/test_no_command_shadowing.py``
holds that line.

Everything that writes goes through ``frago.server.identity`` rather than
touching the JSON, because the daemon is serving logins into the same table at
the same time and the lock lives in that module.
"""

from __future__ import annotations

import json

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup


def _identity():
    """Import late: this module is imported at CLI start-up, the server is not."""
    from frago.server import identity

    return identity


@click.group(name="user", cls=AgentFriendlyGroup)
def user_group() -> None:
    """People who signed in to this server's published pages.

    Not `frago whoami` (that is this frago's own cloud account) and not
    `frago session` (that is agent transcripts). These accounts exist only so a
    published page can hand each visitor their own slot of data.
    """


# ---------------------------------------------------------------------------
# finding the person the operator meant
# ---------------------------------------------------------------------------


def _resolve_user(ref: str):
    """Turn what the operator typed into one account, or fail loudly.

    An id is 32 hex characters that nobody memorises, so an email address and a
    leading chunk of the id both work. An ambiguous prefix is an error rather
    than a pick: `frago user disable` on the wrong person is not recoverable by
    re-running it.
    """
    ident = _identity()
    if "@" in ref:
        user = ident.find_user_by_email(ref)
        if user is None:
            raise click.ClickException(f"No account for {ref}")
        return user

    exact = ident.find_user_by_id(ref)
    if exact is not None:
        return exact

    matches = [u for u in ident.list_users() if u.id.startswith(ref)]
    if not matches:
        raise click.ClickException(
            f"No account matching '{ref}'. `frago user list` shows ids and emails."
        )
    if len(matches) > 1:
        shown = ", ".join(f"{u.id} ({u.email})" for u in matches[:5])
        raise click.ClickException(f"'{ref}' matches {len(matches)} accounts: {shown}")
    return matches[0]


def _resolve_session(ref: str):
    ident = _identity()
    matches = [s for s in ident.list_sessions() if s.sid == ref or s.sid.startswith(ref)]
    if not matches:
        raise click.ClickException(
            f"No live session matching '{ref}'. `frago user session list` shows the ids."
        )
    if len(matches) > 1:
        raise click.ClickException(f"'{ref}' matches {len(matches)} sessions; give more of the id")
    return matches[0]


def _ask_for_password() -> str:
    """Read a new password without it ever being an argument.

    A password passed on the command line is readable by every other account on
    the machine for as long as the process lives (`ps -ww`), and then sits in
    the shell history. There is deliberately no `--password` option to fall back
    to: unlike `frago remote add --token`, nothing here is scripted often enough
    to be worth the exposure.
    """
    return click.prompt("New password", hide_input=True, confirmation_prompt=True)


def _activity(sessions: list, user_id: str) -> str:
    seen = [s.last_seen for s in sessions if s.identity == user_id and s.last_seen]
    return max(seen) if seen else ""


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


@user_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--recent", is_flag=True,
              help="Order by last seen instead of by signup, and show when that was")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def user_list(recent: bool, output_format: str) -> None:
    """Show every account: id ↔ email, whether it is suspended, whether it has data.

    Every address is printed as `unverified`, and that is not decoration. There
    is no verification step anywhere in this design, so the table records who
    *claimed* an address first, not who owns it. Anything that would need the
    stronger claim — mailing these people, matching them against another system
    — must not be built on this output.

    Password material never appears here.

    \b
    Examples:
        frago user list
        frago user list --recent
        frago user list --format json
    """
    ident = _identity()
    users = ident.list_users()
    sessions = ident.list_sessions()

    rows = [{
        "id": user.id,
        "email": user.email,
        "email_verified": False,
        "disabled": user.disabled,
        "created": user.created,
        "has_data": ident.has_data(user.id),
        "sessions": sum(1 for s in sessions if s.identity == user.id),
        "last_seen": _activity(sessions, user.id),
    } for user in users]

    if recent:
        rows.sort(key=lambda row: (row["last_seen"] or "", row["created"]), reverse=True)

    if output_format == "json":
        click.echo(json.dumps({"users": rows}, ensure_ascii=False, indent=2))
        return

    if not rows:
        click.echo("No accounts yet. One is created the first time somebody signs in.")
        return

    for row in rows:
        marks = ["unverified"]
        if row["disabled"]:
            marks.append("disabled")
        marks.append("has-data" if row["has_data"] else "no-data")
        if row["sessions"]:
            marks.append(f"{row['sessions']} session(s)")
        when = row["last_seen"] if recent else row["created"]
        label = "seen" if recent else "since"
        click.echo(f"{row['id']}  {row['email']:<32}  {label} {when or '-':<26}  {' '.join(marks)}")

    click.echo(
        f"\n{len(rows)} account(s). Addresses are unverified — whoever signed in with "
        "one first holds it here.",
        err=True,
    )


@user_group.command(name="passwd", cls=AgentFriendlyCommand)
@click.argument("who")
def user_passwd(who: str) -> None:
    """Set someone's password. Every device they were signed in on is logged out.

    WHO is an account id (or a unique leading part of one) or the email address.
    The password is typed at a hidden prompt and is never an argument.

    Dropping the old sessions is the point, not a side effect: the owner resets
    a password when the previous one — or a cookie made with it — should stop
    working, and a reset that left live sessions alone would not do that.

    \b
    Examples:
        frago user passwd a@example.com
        frago user passwd 3f9c
    """
    ident = _identity()
    user = _resolve_user(who)
    password = _ask_for_password()
    try:
        ident.set_password(user.id, password)
    except ident.IdentityError as exc:
        raise click.ClickException(exc.detail) from exc
    click.echo(f"✓ password set for {user.email} ({user.id}); all their sessions are now invalid")


@user_group.command(name="disable", cls=AgentFriendlyCommand)
@click.argument("who")
def user_disable(who: str) -> None:
    """Suspend an account. It stops working on the next request, not at expiry.

    Suspending rather than deleting: the account id is also the name of that
    person's data slot, so removing the row would leave the data behind with
    nothing pointing at it, and the next visitor using that address would
    inherit it.

    \b
    Examples:
        frago user disable a@example.com
    """
    ident = _identity()
    user = _resolve_user(who)
    if user.disabled:
        click.echo(f"{user.email} ({user.id}) is already disabled")
        return
    try:
        ident.set_disabled(user.id, True)
    except ident.IdentityError as exc:
        raise click.ClickException(exc.detail) from exc
    click.echo(f"✓ disabled {user.email} ({user.id}); their sessions are cut and login is refused")


@user_group.command(name="enable", cls=AgentFriendlyCommand)
@click.argument("who")
def user_enable(who: str) -> None:
    """Reinstate a suspended account. Its data is untouched; it must sign in again.

    \b
    Examples:
        frago user enable a@example.com
    """
    ident = _identity()
    user = _resolve_user(who)
    if not user.disabled:
        click.echo(f"{user.email} ({user.id}) is already enabled")
        return
    try:
        ident.set_disabled(user.id, False)
    except ident.IdentityError as exc:
        raise click.ClickException(exc.detail) from exc
    click.echo(f"✓ enabled {user.email} ({user.id}); they can sign in again")


# ---------------------------------------------------------------------------
# login sessions
# ---------------------------------------------------------------------------


@user_group.group(name="session", cls=AgentFriendlyGroup)
def user_session_group() -> None:
    """Live logins on this server.

    Not `frago session` — that group is the agent transcript store and has
    nothing to do with who is signed in to a page.
    """


@user_session_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def session_list(output_format: str) -> None:
    """Show the logins that are currently good, newest first.

    The id shown is what the server stores — the hash of the cookie, not the
    cookie. Printing it cannot hand anyone a way in, and it is what
    `frago user session revoke` takes.

    \b
    Examples:
        frago user session list
        frago user session list --format json
    """
    ident = _identity()
    sessions = ident.list_sessions()
    emails = {user.id: user.email for user in ident.list_users()}

    if output_format == "json":
        click.echo(json.dumps({"sessions": [{
            "id": s.sid,
            "identity": s.identity,
            "email": emails.get(s.identity, ""),
            "created": s.created,
            "expires": s.expires,
            "last_seen": s.last_seen,
        } for s in sessions]}, ensure_ascii=False, indent=2))
        return

    if not sessions:
        click.echo("Nobody is signed in.")
        return

    for s in sessions:
        who = emails.get(s.identity) or f"{s.identity} (no such account)"
        click.echo(f"{s.sid}  {who:<32}  since {s.created}  expires {s.expires}")

    click.echo(f"\n{len(sessions)} live session(s).", err=True)


@user_session_group.command(name="revoke", cls=AgentFriendlyCommand)
@click.argument("session_id")
def session_revoke(session_id: str) -> None:
    """Cut one login short. That cookie fails on its next request.

    SESSION_ID is the id from `frago user session list`, or a unique leading
    part of it. To log somebody out everywhere, change their password instead
    (`frago user passwd`) — that drops all of their sessions at once.

    \b
    Examples:
        frago user session revoke 4b1f
    """
    ident = _identity()
    session = _resolve_session(session_id)
    emails = {user.id: user.email for user in ident.list_users()}
    if not ident.revoke_session_id(session.sid):
        raise click.ClickException(f"Could not revoke {session.sid}")
    who = emails.get(session.identity, session.identity)
    click.echo(f"✓ revoked {session.sid} ({who}); that cookie is dead on its next request")
