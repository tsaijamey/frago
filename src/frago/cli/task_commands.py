"""Task management CLI (surgical state adjustments).

Correct way to hand-edit a task's status: go through this CLI so the timeline
records a task_state entry. Directly editing ingested_tasks.json loses a round
trip with TaskStore.rebuild_status_cache — the rebuild sees no matching entry
in the timeline and reverts your edit.

Spec ref: 2026-04-20 audit item P2 #3.
"""

from __future__ import annotations

import json

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup


@click.group(name="task", cls=AgentFriendlyGroup)
def task_group():
    """Task state management (emits timeline task_state entry)."""
    pass


@task_group.command(name="history", cls=AgentFriendlyCommand)
@click.argument("task_id", required=True)
@click.option("--limit", type=int, default=50,
              help="Max timeline entries to return (newest first, default 50)")
def task_history(task_id: str, limit: int):
    """Show the full timeline of a task across resume / restart boundaries.

    Reads ~/.frago/timeline/timeline.jsonl and filters entries whose task_id
    matches (or whose data contains the task_id). Output is JSON for agent
    consumption — one object per entry, ordered newest first.

    spec v1.2 A5: Task→Session 0..1, history walks back over multiple
    Sessions (resume can mint a new run_id + CSID; history stitches them
    via task_id).

    Examples:
      frago task history 01HW00ABC
      frago task history 01HW00ABC --limit 200
    """
    from pathlib import Path as _Path

    timeline_path = _Path.home() / ".frago" / "timeline" / "timeline.jsonl"
    if not timeline_path.exists():
        click.echo(json.dumps(
            {"task_id": task_id, "entries": [], "note": "no timeline.jsonl yet"},
            ensure_ascii=False, indent=2,
        ))
        return

    matched: list[dict] = []
    for line in timeline_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("task_id") == task_id:
            matched.append(entry)
            continue
        data = entry.get("data") or {}
        if isinstance(data, dict) and (
            data.get("task_id") == task_id or data.get("run_id") == task_id
        ):
            matched.append(entry)

    matched.reverse()
    click.echo(json.dumps(
        {"task_id": task_id, "count": len(matched[:limit]), "entries": matched[:limit]},
        ensure_ascii=False, indent=2,
    ))


@task_group.command(name="mark", cls=AgentFriendlyCommand)
@click.argument("task_id", required=True)
@click.argument(
    "status", required=True,
    type=click.Choice(["pending", "queued", "executing", "completed", "failed"]),
)
@click.option("--reason", default="manual-override",
              help="Reason recorded in the task_state entry")
@click.option("--error", default=None,
              help="Error text (only used when status=failed)")
@click.option("--result-summary", default=None,
              help="Result summary (only used when status=completed)")
def task_mark(task_id, status, reason, error, result_summary):
    """Override a task's status and emit a task_state timeline entry.

    This is the ONLY correct way to hand-adjust a task's state while preserving
    the timeline source-of-truth invariant (TaskStore.rebuild_status_cache uses
    timeline as ground truth; a direct JSON edit would be reverted on restart).

    Examples:
      frago task mark 5cf89f19 completed --reason "stuck-executing manual cleanup"
      frago task mark abc123 failed --error "zombie process killed at midnight"
    """
    from frago.server.services.ingestion.models import TaskStatus
    from frago.server.services.ingestion.store import TaskStore

    store = TaskStore()
    task = store.get(task_id)
    if not task:
        click.echo(json.dumps({
            "error": f"task not found: {task_id}",
            "hint": "list tasks: curl http://127.0.0.1:8093/api/pa/tasks | jq",
        }, ensure_ascii=False), err=True)
        raise SystemExit(1)

    try:
        target_status = TaskStatus(status)
    except ValueError as e:
        click.echo(json.dumps({"error": f"invalid status {status!r}"},
                              ensure_ascii=False), err=True)
        raise SystemExit(1) from e

    prev_status = task.status.value
    # update_status internally emits the task_state timeline entry
    # (spec 20260418-timeline-event-coverage Phase 4).
    store.update_status(
        task.id, target_status,
        error=error, result_summary=result_summary,
    )

    click.echo(json.dumps({
        "task_id": task.id,
        "prev_status": prev_status,
        "new_status": status,
        "reason": reason,
        "note": "task_state entry emitted — safe against rebuild_status_cache reversion",
    }, ensure_ascii=False))
