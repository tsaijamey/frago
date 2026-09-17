"""frago todo — local todo management commands.

  frago todo add/list/show/edit/log/done/drop/rm/schema/next
  frago todo categorize                 # 一批事务一次定分类
  frago todo category list/add/rename/move/rm

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

# 能直接设的状态，与能筛的状态是两张表。
#
# 「弃置」筛得出来（清单上要看得见被放下的是哪些），但设不进去——它必须带着理由走
# `frago todo drop`。两张表要是合成一张，`--status dropped` 就是一条绕开理由的旁路。
_STATUS_CHOICE = click.Choice(["todo", "doing", "done"])
_STATUS_FILTER_CHOICE = click.Choice(["todo", "doing", "done", "dropped"])
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


def _check_category(category_id, *, allow_none=False):
    """命令行收到的分类 id 先对一遍清单，不在就报错并列出可选项。"""
    from frago.todo import categories

    if category_id is None or (allow_none and category_id == categories.UNCATEGORIZED):
        return
    try:
        categories.require(category_id)
    except ValueError as e:
        hint = f" (or {categories.UNCATEGORIZED!r})" if allow_none else ""
        raise click.ClickException(f"{e}{hint}") from None


def _print_list(status=None, priority=None, tag=None, category=None):
    from frago.todo import categories, store

    _check_category(category, allow_none=True)
    todos = store.list_todos(status=status, priority=priority, tag=tag, category=category)
    if not todos:
        click.echo("No todos.")
        click.echo('  frago todo add "..."')
        click.echo("  frago todo --how-to    # 会话尾声怎么把剩下的事交接出去")
        return

    # 未分类与引用了已删分类的，都显示成 "-"：它们排在哪，这一栏就该怎么写。
    known = {c.id for c in categories.list_categories()}
    click.echo(f"\n{'ID':<36s} {'CATEGORY':<10s} {'STATUS':<8s} {'PRI':<7s} TITLE")
    click.echo("-" * 103)
    for t in todos:
        cat = t.category if t.category in known else "-"
        click.echo(f"{t.id:<36s} {cat:<10s} {t.status:<8s} {t.priority:<7s} {t.title}")
    click.echo(f"\n({len(todos)} todos)")
    click.echo("会话尾声要把剩下的事交接给下一场：frago todo --how-to")


@todo_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("title_arg", required=False)
@click.option("--title", "title_opt", default=None, help="Todo title (or pass it positionally)")
@click.option("--summary", default=None, help="Shorter summary")
@click.option("--priority", type=_PRIORITY_CHOICE, default="normal", help="Priority (default normal)")
@click.option("--status", type=_STATUS_CHOICE, default="todo", help="Initial status (default todo)")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable)")
@click.option("--category", default=None,
              help="Category id (see `frago todo category list`)")
@click.option("--context", default=None, help="Background / why")
@click.option("--step", "steps", multiple=True, help="Step (repeatable)")
@click.option("--done-when", "done_when", multiple=True, help="Completion condition (repeatable)")
@click.option("--link", "links", multiple=True, help="Related URL (repeatable)")
@click.option("--session", "sessions", multiple=True,
              help="Session id this came out of (repeatable; the current one is recorded anyway)")
@click.option("--no-session", is_flag=True, help="Do not record the current session id")
def todo_add(title_arg, title_opt, summary, priority, status, tags, category, context, steps,
             done_when, links, sessions, no_session):
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
    _check_category(category)

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
            category=category,
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
@click.option("--status", type=_STATUS_FILTER_CHOICE, default=None, help="Filter by status")
@click.option("--priority", type=_PRIORITY_CHOICE, default=None, help="Filter by priority")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--category", default=None,
              help="Filter by category id; `none` = uncategorized")
def todo_list(status, priority, tag, category):
    """List todos (sorted by category position, then priority, then created)."""
    _print_list(status=status, priority=priority, tag=tag, category=category)


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
@click.option("--category", default=None, help="Category id; `none` clears it")
@click.option("--context", default=None)
@click.option("--step", "steps", multiple=True, help="Replace steps (repeatable)")
@click.option("--done-when", "done_when", multiple=True, help="Replace conditions (repeatable)")
@click.option("--link", "links", multiple=True, help="Replace links (repeatable)")
@click.option("--session", "sessions", multiple=True, help="Replace session ids (repeatable)")
def todo_edit(ref, title, summary, priority, status, tags, category, context, steps, done_when,
              links, sessions):
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
    if category is not None:
        from frago.todo import categories

        _check_category(category, allow_none=True)
        # 存储层用空串表示清空——None 在那边的意思是「这一项不改」。
        changes["category"] = "" if category == categories.UNCATEGORIZED else category
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


@todo_group.command(name="drop", cls=AgentFriendlyCommand)
@click.argument("ref")
@click.option("--reason", required=True,
              help="Why it is being dropped (required, recorded verbatim)")
def todo_drop(ref, reason):
    """Drop a todo — it will not be done, and --reason says why.

    \b
    Dropping is not completing. `done` says it got finished; dropping says it was
    put down on purpose. Whoever reads this todo months from now will ask why, and
    neither the title nor the background answers that — so the reason is required
    here and nowhere else can set this status.

    \b
    A todo that is already dropped is refused rather than re-dropped: that would be
    a second verdict quietly overwriting the first one.

    \b
    Examples:
      frago todo drop 20260722-frago-agent --reason "上游换了检测方式，这条不再成立"
    """
    from frago.todo import store

    try:
        todo = store.drop(ref, reason)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Dropped {todo.id} (dropped_at={todo.dropped_at})")
    click.echo(f"Reason: {todo.drop_reason}")


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
    """Show the most urgent active todo (first active one in `list` order)."""
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


@todo_group.command(name="categorize", cls=AgentFriendlyCommand)
@click.argument("mapping", required=False)
def todo_categorize(mapping):
    """Assign categories to many todos at once, all-or-nothing.

    \b
    MAPPING is a JSON object {"<todo id or unique prefix>": "<category id>"};
    null or "none" clears a todo's category. Omit MAPPING (or pass "-") to read
    the JSON from stdin.

    \b
    Every entry is checked first. If any todo id or category id is wrong, NOTHING
    is written: the command exits non-zero and lists every bad entry. On success
    it prints "OK: ..." with the number of todos changed.

    \b
    Examples:
      frago todo categorize '{"20260901-fix-mail": "work", "20260902-buy-milk": "family"}'
      frago todo categorize < plan.json
    """
    from frago.todo import categories, store

    if mapping is None or mapping == "-":
        mapping = click.get_text_stream("stdin").read()
    try:
        data = json.loads(mapping)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"REJECTED, nothing written: mapping is not valid JSON ({e})") from None
    if not isinstance(data, dict) or not data:
        raise click.ClickException(
            'REJECTED, nothing written: mapping must be a non-empty JSON object '
            '{"<todo id>": "<category id>", ...}'
        )

    try:
        changed, unchanged = store.categorize(data)
    except store.BatchError as e:
        lines = [f"REJECTED, nothing written — {len(e.problems)} of {len(data)} entries invalid:"]
        lines += [f"  {p}" for p in e.problems]
        lines.append(f"valid categories: {categories.describe(e.categories)} "
                     f"(or null / {categories.UNCATEGORIZED!r} to clear)")
        raise click.ClickException("\n".join(lines)) from None

    click.echo(f"OK: categorized {len(changed)} todo(s), {unchanged} already as requested")
    for todo, before in changed:
        click.echo(f"  {todo.id}: {before or '-'} -> {todo.category or '-'}")


# ── 分类清单 ────────────────────────────────────────────────────────────


@todo_group.group(name="category", cls=AgentFriendlyGroup, invoke_without_command=True)
@click.pass_context
def category_group(ctx):
    """Manage the ordered category list (position = sort rank, at most 20)."""
    if ctx.invoked_subcommand is None:
        _print_categories()


def _print_categories():
    from frago.todo import categories, store

    current = categories.list_categories()
    usage = store.category_usage()
    click.echo(f"\n{'#':>2s}  {'ID':<20s} {'TODOS':>5s}  NAME")
    click.echo("-" * 50)
    for i, c in enumerate(current, 1):
        click.echo(f"{i:>2d}  {c.id:<20s} {usage.get(c.id, 0):>5d}  {c.name}")
    click.echo(f"\n({len(current)}/{categories.MAX_CATEGORIES} categories; "
               "todos sort by this order, uncategorized last)")
    orphans = {k: v for k, v in usage.items() if k not in {c.id for c in current}}
    if orphans:
        # 分类删了、事务里还留着 id 的，点出来：它们现在按未分类排。
        listed = ", ".join(f"{k}({v})" for k, v in sorted(orphans.items()))
        click.echo(f"[!] todos referencing removed categories (sorted as uncategorized): {listed}")


def _category_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (KeyError, ValueError) as e:
        raise click.ClickException(str(e.args[0] if isinstance(e, KeyError) else e)) from None


@category_group.command(name="list", cls=AgentFriendlyCommand)
def category_list():
    """Show categories in rank order, with how many todos use each."""
    _print_categories()


@category_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("category_id")
@click.argument("name")
@click.option("--position", type=int, default=None, help="1-based position (default: last)")
def category_add(category_id, name, position):
    """Add a category: ID (lowercase, stored in todo files) and display NAME."""
    from frago.todo import categories

    _category_call(categories.add_category, category_id, name, position=position)
    click.echo(f"Added category {category_id} ({name})")
    _print_categories()


@category_group.command(name="rename", cls=AgentFriendlyCommand)
@click.argument("category_id")
@click.argument("name")
def category_rename(category_id, name):
    """Change a category's display NAME (the id and the todos stay as they are)."""
    from frago.todo import categories

    _category_call(categories.rename_category, category_id, name)
    click.echo(f"Renamed {category_id} -> {name}")


@category_group.command(name="move", cls=AgentFriendlyCommand)
@click.argument("category_id")
@click.argument("position", type=int)
def category_move(category_id, position):
    """Move a category to POSITION (1 = first; out-of-range sticks to the ends)."""
    from frago.todo import categories

    _category_call(categories.move_category, category_id, position)
    click.echo(f"Moved {category_id} to position {position}")
    _print_categories()


@category_group.command(name="rm", cls=AgentFriendlyCommand)
@click.argument("category_id")
@click.option("--force", is_flag=True, help="Remove even if todos still reference it")
def category_rm(category_id, force):
    """Remove a category. Todos that used it keep the id but sort as uncategorized.

    \b
    Refuses while todos still reference it unless --force, and says how many.
    """
    from frago.todo import categories, store

    used = store.category_usage().get(category_id, 0)
    if used and not force:
        raise click.ClickException(
            f"{used} todo(s) still use category {category_id!r}. Removing it leaves their "
            f"field as is but they will sort as uncategorized. Re-run with --force, or "
            f"reassign them first: frago todo list --category {category_id}"
        )
    _category_call(categories.remove_category, category_id)
    note = f"; {used} todo(s) now sort as uncategorized" if used else ""
    click.echo(f"Removed category {category_id}{note}")
