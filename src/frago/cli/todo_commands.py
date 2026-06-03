"""frago todo — local todo management commands.

  frago todo add/list/show/edit/done/rm/schema/next

A thin CLI over ``frago.todo.store``; one JSON file per todo under
``~/.frago/todo/`` (``FRAGO_TODO_DIR`` overrides). Bare ``frago todo`` shows
the list, mirroring how ``frago def`` bare-invokes to a domain listing.
"""

import json
from dataclasses import asdict

import click

from .agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

_STATUS_CHOICE = click.Choice(["todo", "doing", "done", "dropped"])
_PRIORITY_CHOICE = click.Choice(["low", "normal", "high"])


@click.group(name="todo", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.pass_context
def todo_group(ctx):
    """Manage local todos (~/.frago/todo/, one JSON per todo)."""
    if ctx.invoked_subcommand is not None:
        return
    _print_list()


def _print_list(status=None, priority=None, tag=None):
    from frago.todo import store

    todos = store.list_todos(status=status, priority=priority, tag=tag)
    if not todos:
        click.echo("No todos.")
        click.echo('  frago todo add --title "..."')
        return

    click.echo(f"\n{'ID':<36s} {'STATUS':<8s} {'PRI':<7s} TITLE")
    click.echo("-" * 92)
    for t in todos:
        click.echo(f"{t.id:<36s} {t.status:<8s} {t.priority:<7s} {t.title}")
    click.echo(f"\n({len(todos)} todos)")


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
def todo_add(title_arg, title_opt, summary, priority, status, tags, context, steps, done_when, links):
    """Create a new todo. Title can be positional (`todo add "..."`) or via --title."""
    from frago.todo import store

    title = title_arg or title_opt
    if not title:
        raise click.ClickException(
            'provide a title: `frago todo add "..."` or `frago todo add --title "..."`'
        )

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
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from None

    click.echo(f"Created todo {todo.id}")
    click.echo(f"Path: {store.todo_dir() / (todo.id + '.json')}")


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
def todo_edit(ref, title, summary, priority, status, tags, context, steps, done_when, links):
    """Edit fields of a todo (only provided options change)."""
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

    if not changes:
        raise click.ClickException("nothing to edit: pass at least one field option")

    try:
        todo = store.update(ref, **changes)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Updated {todo.id} (updated={todo.updated})")


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
