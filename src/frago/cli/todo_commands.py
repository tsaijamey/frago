"""frago todo — local todo management commands.

  frago todo add/list/show/edit/log/done/rm/schema/next

A thin CLI over ``frago.todo.store``; one JSON file per todo under
``~/.frago/todo/`` (``FRAGO_TODO_DIR`` overrides). Bare ``frago todo`` shows
the list, mirroring how ``frago def`` bare-invokes to a domain listing.

``frago todo --how-to`` prints the handover playbook: what belongs in a todo
written at the end of a session so that a *different* agent, weeks later, can
pick the thread up — and how the session id recorded on each todo leads back to
the raw conversation. The list and store know the shape of a todo; that page is
the only place that says what makes one worth writing.

That page lives in the knowledge book (``frago book session-handoff``), not in a
second copy here: the book index is what an agent sees at session start, so that
is where the practice gets discovered; this flag is the entrance from the other
side, at the moment a todo is actually being written.
"""

import json
from dataclasses import asdict
from importlib.resources import files as pkg_files

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

_STATUS_CHOICE = click.Choice(["todo", "doing", "done", "dropped"])
_PRIORITY_CHOICE = click.Choice(["low", "normal", "high"])

HOWTO_PATH = pkg_files("frago.resources") / "book" / "session-handoff.md"


@click.group(name="todo", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.option("--how-to", "how_to", is_flag=True,
              help="How to write a todo that hands this session's leftovers to the next one")
@click.pass_context
def todo_group(ctx, how_to):
    """Manage local todos (~/.frago/todo/, one JSON per todo)."""
    if how_to:
        _print_how_to()
        ctx.exit()
    if ctx.invoked_subcommand is not None:
        return
    _print_list()


def _print_how_to():
    """Print the handover playbook shipped with frago."""
    if not HOWTO_PATH.is_file():
        raise click.ClickException(
            "how-to page missing; frago installation may be incomplete"
        )
    click.echo(HOWTO_PATH.read_text(encoding="utf-8"))


@todo_group.command(name="how-to", cls=AgentFriendlyCommand)
def todo_how_to():
    """Print the handover playbook (same as `frago todo --how-to`)."""
    _print_how_to()


def _current_session_id() -> tuple[str | None, str | None]:
    """Resolve the session this command runs in: ``(session_id, warning)``.

    Only a *declared* id is recorded automatically. The fallback guess (freshest
    transcript of this directory) is deliberately refused here: a silently wrong
    session id sends the next agent off to read an unrelated conversation, which
    is worse than recording none. The warning tells the caller how to supply it.
    """
    try:
        from frago.session.self_id import resolve_self

        found = resolve_self()
    except Exception as e:  # noqa: BLE001 - provenance is a nice-to-have, never fatal
        return None, f"session id not resolved ({e})"

    if found is None:
        return None, "session id not resolved (no $FRAGO_SESSION_ID / $CLAUDE_CODE_SESSION_ID)"
    if not found.certain:
        return None, f"session id not recorded — {found.note}"
    return found.session_id, None


def _print_list(status=None, priority=None, tag=None):
    from frago.todo import store

    todos = store.list_todos(status=status, priority=priority, tag=tag)
    if not todos:
        click.echo("No todos.")
        click.echo('  frago todo add "..."')
        click.echo("  frago todo --how-to    # 会话尾声怎么把剩下的事交接出去")
        return

    click.echo(f"\n{'ID':<36s} {'STATUS':<8s} {'PRI':<7s} TITLE")
    click.echo("-" * 92)
    for t in todos:
        click.echo(f"{t.id:<36s} {t.status:<8s} {t.priority:<7s} {t.title}")
    click.echo(f"\n({len(todos)} todos)")
    click.echo("会话尾声要把剩下的事交接给下一场：frago todo --how-to")


@todo_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("title_arg", required=False)
@click.option("--title", "title_opt", default=None, help="Todo title (or pass it positionally)")
@click.option("--summary", default=None, help="Shorter summary")
@click.option("--priority", type=_PRIORITY_CHOICE, default="normal", help="Priority (default normal)")
@click.option("--status", type=_STATUS_CHOICE, default="todo", help="Initial status (default todo)")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable)")
@click.option("--context", default=None, help="Background / why")
@click.option("--step", "steps", multiple=True, help="Step (repeatable)")
@click.option("--done-when", "done_when", multiple=True, help="Completion condition (repeatable)")
@click.option("--link", "links", multiple=True, help="Related URL (repeatable)")
@click.option("--session", "sessions", multiple=True,
              help="Session id this came out of (repeatable; the current one is recorded anyway)")
@click.option("--no-session", is_flag=True, help="Do not record the current session id")
def todo_add(title_arg, title_opt, summary, priority, status, tags, context, steps, done_when,
             links, sessions, no_session):
    """Create a new todo. Title can be positional (`todo add "..."`) or via --title.

    \b
    The current session id is recorded automatically — it is the way back to the
    conversation this todo came out of. `frago todo --how-to` explains what else
    a handover todo has to carry.
    """
    from frago.todo import store

    title = title_arg or title_opt
    if not title:
        raise click.ClickException(
            'provide a title: `frago todo add "..."` or `frago todo add --title "..."`'
        )

    session_list = list(sessions)
    warning = None
    if not no_session:
        current, warning = _current_session_id()
        if current:
            session_list.append(current)

    try:
        todo = store.add(
            title,
            summary=summary,
            priority=priority,
            status=status,
            tags=list(tags),
            context=context,
            steps=list(steps),
            done_when=list(done_when),
            links=list(links),
            sessions=session_list,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from None

    click.echo(f"Created todo {todo.id}")
    click.echo(f"Path: {store.todo_dir() / (todo.id + '.json')}")
    if todo.sessions:
        click.echo(f"Sessions: {', '.join(todo.sessions)}")
    elif warning and not no_session:
        # Provenance is the whole point of a handover todo — say it is missing,
        # and say how to fill it in, instead of quietly shipping a todo that
        # leads nowhere.
        click.echo(f"[!] {warning}", err=True)
        click.echo(f"[Fix] frago todo edit {todo.id} --session <id>   # frago session self", err=True)


@todo_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--status", type=_STATUS_CHOICE, default=None, help="Filter by status")
@click.option("--priority", type=_PRIORITY_CHOICE, default=None, help="Filter by priority")
@click.option("--tag", default=None, help="Filter by tag")
def todo_list(status, priority, tag):
    """List todos (sorted by priority then created)."""
    _print_list(status=status, priority=priority, tag=tag)


@todo_group.command(name="show", cls=AgentFriendlyCommand)
@click.argument("ref")
def todo_show(ref):
    """Show a single todo as full JSON (REF = id or unique prefix)."""
    from frago.todo import store

    try:
        todo = store.get(ref)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(json.dumps(asdict(todo), ensure_ascii=False, indent=2))


@todo_group.command(name="edit", cls=AgentFriendlyCommand)
@click.argument("ref")
@click.option("--title", default=None)
@click.option("--summary", default=None)
@click.option("--priority", type=_PRIORITY_CHOICE, default=None)
@click.option("--status", type=_STATUS_CHOICE, default=None)
@click.option("--tag", "tags", multiple=True, help="Replace tags (repeatable)")
@click.option("--context", default=None)
@click.option("--step", "steps", multiple=True, help="Replace steps (repeatable)")
@click.option("--done-when", "done_when", multiple=True, help="Replace conditions (repeatable)")
@click.option("--link", "links", multiple=True, help="Replace links (repeatable)")
@click.option("--session", "sessions", multiple=True, help="Replace session ids (repeatable)")
def todo_edit(ref, title, summary, priority, status, tags, context, steps, done_when, links,
              sessions):
    """Edit fields of a todo (only provided options change).

    \b
    Every list option REPLACES. To carry a long-running todo forward without
    losing what earlier sessions concluded, use `frago todo log` — it appends.
    """
    from frago.todo import store

    changes = {}
    if title is not None:
        changes["title"] = title
    if summary is not None:
        changes["summary"] = summary
    if priority is not None:
        changes["priority"] = priority
    if status is not None:
        changes["status"] = status
    if context is not None:
        changes["context"] = context
    # Repeatable options replace the list only when supplied at least once.
    if tags:
        changes["tags"] = list(tags)
    if steps:
        changes["steps"] = list(steps)
    if done_when:
        changes["done_when"] = list(done_when)
    if links:
        changes["links"] = list(links)
    if sessions:
        changes["sessions"] = list(sessions)

    if not changes:
        raise click.ClickException("nothing to edit: pass at least one field option")

    try:
        todo = store.update(ref, **changes)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Updated {todo.id} (updated={todo.updated})")


@todo_group.command(name="log", cls=AgentFriendlyCommand)
@click.argument("ref")
@click.argument("entry")
@click.option("--status", type=_STATUS_CHOICE, default=None, help="Also move the todo to this status")
@click.option("--session", "session", default=None,
              help="Session id to stamp the entry with (default: the current session)")
@click.option("--no-session", is_flag=True, help="Stamp the entry with the date only")
def todo_log(ref, entry, status, session, no_session):
    """Append what THIS session did to a todo, stamped with date + session id.

    \b
    A long-running todo is picked up again and again by different sessions. This
    appends — the earlier entries stay, so whoever takes it next sees how the
    thinking moved, not just the last verdict.

    \b
    Examples:
      frago todo log 20260828-wind "抓到三篇年报，卡在取数口径不一致" --status doing
      frago todo log 20260828-wind "已验证，收工" --status done
    """
    from frago.todo import store

    sid = None
    if not no_session:
        sid = session
        warning = None
        if sid is None:
            sid, warning = _current_session_id()
        if sid is None and warning:
            click.echo(f"[!] {warning}", err=True)

    try:
        todo = store.log(ref, entry, session_id=sid, status=status)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None

    stamped = f" · session {sid}" if sid else ""
    click.echo(f"Logged to {todo.id} ({todo.status}){stamped}")


@todo_group.command(name="done", cls=AgentFriendlyCommand)
@click.argument("ref")
def todo_done(ref):
    """Mark a todo done (REF = id or unique prefix; idempotent)."""
    from frago.todo import store

    try:
        todo = store.mark_done(ref)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Marked done {todo.id} (done_at={todo.done_at})")


@todo_group.command(name="rm", cls=AgentFriendlyCommand)
@click.argument("ref")
def todo_rm(ref):
    """Delete a todo (REF = id or unique prefix)."""
    from frago.todo import store

    try:
        todo_id = store.remove(ref)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Removed {todo_id}")


@todo_group.command(name="schema", cls=AgentFriendlyCommand)
def todo_schema():
    """Print the todo JSON schema (field definitions)."""
    from frago.todo import store

    click.echo(json.dumps(store.TODO_SCHEMA, ensure_ascii=False, indent=2))


@todo_group.command(name="next", cls=AgentFriendlyCommand)
def todo_next():
    """Show the most urgent active todo (highest priority, oldest)."""
    from frago.todo import store

    todo = store.next_todo()
    if todo is None:
        click.echo("No active todos.")
        return
    click.echo(f"{todo.id}  [{todo.priority}]  {todo.title}")
    if todo.context:
        click.echo(f"\n{todo.context}")
    if todo.done_when:
        click.echo("\ndone when:")
        for cond in todo.done_when:
            click.echo(f"  - {cond}")
