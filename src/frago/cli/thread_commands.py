"""Thread management commands (spec 20260418-thread-organization Phase 4).

`frago thread` exposes the ThreadStore to agents in a stable, agent-friendly
interface. Agents MUST use these commands instead of reading ~/.frago/threads/
directly, so the underlying storage can evolve without breaking PA workflows.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from frago.server.services.thread_service import (
    STATUS_ARCHIVED,
    STATUS_IDLE,
    VALID_STATUSES,
    get_thread_store,
)


def _emit(payload: dict, *, as_json: bool) -> None:
    """Print payload; JSON by default for agent consumption."""
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))


def _fail(message: str, *, hint: str | None = None, exit_code: int = 1) -> None:
    """Emit a structured error and exit. Message always includes a correction hint when possible."""
    payload = {"error": message}
    if hint:
        payload["hint"] = hint
    click.echo(json.dumps(payload, ensure_ascii=False), err=True)
    raise SystemExit(exit_code)


@click.group(name="thread", cls=AgentFriendlyGroup)
def thread_group():
    """Manage thread organization over the timeline."""
    pass


# ---------------------------------------------------------------------------
# Read commands
# ---------------------------------------------------------------------------

@thread_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--status", default=None, help="Filter by status: active | idle | archived")
@click.option("--origin", default=None, help="Filter by origin: external | internal")
@click.option("--subkind", default=None, help="Filter by subkind (e.g. feishu, reflection)")
@click.option("--limit", type=int, default=20, help="Max threads to return (default 20)")
@click.option("--json", "as_json", is_flag=True, default=False, help="Pretty-print JSON")
def thread_list(
    status: str | None,
    origin: str | None,
    subkind: str | None,
    limit: int,
    as_json: bool,
):
    """List threads sorted by last activity (most recent first).

    Examples:
      frago thread list
      frago thread list --status active --limit 10
      frago thread list --origin internal --subkind reflection
    """
    if status and status not in VALID_STATUSES:
        _fail(
            f"invalid --status {status!r}",
            hint=f"one of: {', '.join(sorted(VALID_STATUSES))}",
        )
    store = get_thread_store()
    threads = store.search(status=status, origin=origin, subkind=subkind)[:limit]
    _emit({
        "threads": [asdict(t) for t in threads],
        "count": len(threads),
        "total_in_store": store.count(),
    }, as_json=as_json)


@thread_group.command(name="search", cls=AgentFriendlyCommand)
@click.argument("query", required=True)
@click.option("--status", default=None)
@click.option("--origin", default=None)
@click.option("--subkind", default=None)
@click.option("--task-id", "task_id", default=None, help="Only threads containing this task_id")
@click.option("--limit", type=int, default=20)
@click.option("--json", "as_json", is_flag=True, default=False)
def thread_search(
    query: str,
    status: str | None,
    origin: str | None,
    subkind: str | None,
    task_id: str | None,
    limit: int,
    as_json: bool,
):
    """Search threads by substring match on thread_id / root_summary / tags.

    Examples:
      frago thread search 报销
      frago thread search weekly --subkind feishu
      frago thread search "" --task-id t_123
    """
    store = get_thread_store()
    results = store.search(
        query=query or None,
        status=status,
        origin=origin,
        subkind=subkind,
        task_id=task_id,
    )[:limit]
    _emit({
        "threads": [asdict(t) for t in results],
        "count": len(results),
        "query": query,
    }, as_json=as_json)


@thread_group.command(name="info", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
@click.option("--json", "as_json", is_flag=True, default=False)
def thread_info(thread_id: str, as_json: bool):
    """Show full index record for a thread.

    Examples:
      frago thread info 01HW001
    """
    idx = get_thread_store().get(thread_id)
    if idx is None:
        _fail(
            f"thread not found: {thread_id}",
            hint="list existing threads: frago thread list",
        )
    _emit(asdict(idx), as_json=as_json)


@thread_group.command(name="peek", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
@click.option("--json", "as_json", is_flag=True, default=False)
def thread_peek(thread_id: str, as_json: bool):
    """Show summary of a thread (index + last_active only).

    This is the cheap view. Use `frago thread hydrate` for full entries (TODO: Spec 2 Phase 6).

    Examples:
      frago thread peek 01HW001
    """
    idx = get_thread_store().get(thread_id)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    _emit({
        "thread_id": idx.thread_id,
        "origin": idx.origin,
        "subkind": idx.subkind,
        "status": idx.status,
        "root_summary": idx.root_summary,
        "last_active_ts": idx.last_active_ts,
        "created_at": idx.created_at,
        "task_count": len(idx.task_ids),
        "tag_count": len(idx.tags),
        "has_run_instance": idx.run_instance_id is not None,
    }, as_json=as_json)


# ---------------------------------------------------------------------------
# Mutation commands
# ---------------------------------------------------------------------------

@thread_group.command(name="close", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
def thread_close(thread_id: str):
    """Mark a thread as archived (soft close, data preserved).

    Examples:
      frago thread close 01HW001
    """
    store = get_thread_store()
    idx = store.set_status(thread_id, STATUS_ARCHIVED)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    click.echo(json.dumps({"thread_id": idx.thread_id, "status": idx.status}, ensure_ascii=False))


@thread_group.command(name="open", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
def thread_open(thread_id: str):
    """Reopen an archived thread (sets status to idle; activity touch revives to active).

    Examples:
      frago thread open 01HW001
    """
    store = get_thread_store()
    idx = store.set_status(thread_id, STATUS_IDLE)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    click.echo(json.dumps({"thread_id": idx.thread_id, "status": idx.status}, ensure_ascii=False))


@thread_group.command(name="bind-run", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
@click.argument("run_instance_id", required=True)
def thread_bind_run(thread_id: str, run_instance_id: str):
    """Manually bind a run instance to a thread (rescue / repair).

    Examples:
      frago thread bind-run 01HW001 run_abc123
    """
    store = get_thread_store()
    idx = store.bind_run(thread_id, run_instance_id)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    click.echo(json.dumps(
        {"thread_id": idx.thread_id, "run_instance_id": idx.run_instance_id},
        ensure_ascii=False,
    ))


@thread_group.command(name="tag", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
@click.argument("tag", required=True)
def thread_tag(thread_id: str, tag: str):
    """Add a tag to a thread.

    Examples:
      frago thread tag 01HW001 urgent
    """
    store = get_thread_store()
    idx = store.add_tag(thread_id, tag)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    click.echo(json.dumps({"thread_id": idx.thread_id, "tags": idx.tags}, ensure_ascii=False))


@thread_group.command(name="set-summary", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
@click.argument("summary", required=True)
def thread_set_summary(thread_id: str, summary: str):
    """Update a thread's one-line root summary.

    Examples:
      frago thread set-summary 01HW001 "用户咨询报销流程"
    """
    store = get_thread_store()
    idx = store.set_summary(thread_id, summary)
    if idx is None:
        _fail(f"thread not found: {thread_id}", hint="list existing: frago thread list")
    click.echo(json.dumps(
        {"thread_id": idx.thread_id, "root_summary": idx.root_summary},
        ensure_ascii=False,
    ))


# Placeholder: `hydrate` and `follow` are in Spec 2 Phase 5/6; add stubs so
# calling them gives a clear "not yet implemented" rather than "unknown command".

@thread_group.command(name="hydrate", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
def thread_hydrate(thread_id: str):  # noqa: ARG001 — placeholder
    """Load full entries for a thread (Spec 2 Phase 6, not yet implemented)."""
    _fail(
        "thread hydrate not yet implemented (Spec 2 Phase 6 pending)",
        hint="use `frago thread info <id>` for index data for now",
        exit_code=2,
    )


@thread_group.command(name="follow", cls=AgentFriendlyCommand)
@click.argument("thread_id", required=True)
def thread_follow(thread_id: str):  # noqa: ARG001 — placeholder
    """Attach subsequent PA actions to this thread (Spec 2 Phase 5, not yet implemented)."""
    _fail(
        "thread follow not yet implemented (Spec 2 Phase 5 pending)",
        hint="use `frago thread bind-run` to associate a run_instance for now",
        exit_code=2,
    )
