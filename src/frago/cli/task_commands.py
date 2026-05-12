"""Task management CLI (surgical state adjustments).

Correct way to hand-edit a task's status: go through this CLI so the timeline
records a task_state entry. board.timeline.jsonl is the single source of
truth — spec 20260512 v1.2 freeze: no other persistence layer exists.

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

    Reads/writes through board public methods so the single-source
    timeline.jsonl reflects the change.

    Examples:
      frago task mark 5cf89f19 completed --reason "stuck-executing manual cleanup"
      frago task mark abc123 failed --error "zombie process killed at midnight"
    """
    from frago.server.services.taskboard import get_board

    board = get_board()
    task = board.get_task(task_id)
    if not task:
        click.echo(json.dumps({
            "error": f"task not found: {task_id}",
            "hint": "list tasks: curl http://127.0.0.1:8093/api/pa/tasks | jq",
        }, ensure_ascii=False), err=True)
        raise SystemExit(1)

    prev_status = task.status
    by = f"cli:task_mark({reason})"
    if status == "completed":
        board.mark_task_completed(task.task_id, summary=result_summary or "", by=by)
    elif status == "failed":
        board.mark_task_failed(task.task_id, error=error or "", by=by)
    elif status == "executing":
        board.mark_task_executing(task.task_id, by=by)
    else:
        # pending / queued are not reachable transitions on the new board.
        click.echo(json.dumps({
            "error": f"unsupported manual transition to {status!r}",
            "hint": "valid: completed | failed | executing",
        }, ensure_ascii=False), err=True)
        raise SystemExit(1)

    click.echo(json.dumps({
        "task_id": task.task_id,
        "prev_status": prev_status,
        "new_status": status,
        "reason": reason,
        "note": "task_state entry emitted to board.timeline.jsonl",
    }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Phase finish (spec line 11): list / awaiting / active / stats subcommands
# ---------------------------------------------------------------------------
# These commands read ~/.frago/timeline/timeline.jsonl via TaskBoard.fold so
# they work offline (server not required). Agents use them for ground-truth
# board state inspection without going through the server's HTTP API.


def _fold_board_offline():
    """Boot a fresh TaskBoard by folding ~/.frago/timeline/timeline.jsonl.

    Returns (board, timeline_path). Returns (None, path) when timeline is
    absent — callers should treat that as an empty board.
    """
    from pathlib import Path as _Path

    from frago.server.services.taskboard.board import TaskBoard

    timeline_path = _Path.home() / ".frago" / "timeline" / "timeline.jsonl"
    if not timeline_path.exists():
        return None, timeline_path
    return TaskBoard.fold(timeline_path), timeline_path


@task_group.command(name="list", cls=AgentFriendlyCommand)
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit raw JSON (default: human-readable)")
def task_list(as_json: bool):
    """List the current board snapshot — threads, msgs, tasks.

    Reads ~/.frago/timeline/timeline.jsonl by folding offline (no server
    required). Output groups msgs under their thread and tasks under each msg.

    Examples:
      frago task list
      frago task list --json | jq '.threads[] | select(.status=="active")'
    """
    board, timeline_path = _fold_board_offline()
    if board is None:
        payload = {
            "threads": [],
            "note": f"timeline.jsonl missing at {timeline_path}",
        }
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    view = board.view_for_pa()
    payload = {
        "thread_count": len(view.get("threads", [])),
        "threads": view.get("threads", []),
    }

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    threads = view.get("threads", [])
    if not threads:
        click.echo("(no threads on board)")
        return
    for t in threads:
        click.echo(
            f"thread {t['id']} [{t.get('status', '?')}] subkind={t.get('subkind', '?')} "
            f"msgs={len(t.get('msgs', []))}"
        )
        for m in t.get("msgs", []):
            click.echo(
                f"  msg {m['id']} [{m.get('status', '?')}] "
                f"tasks={len(m.get('tasks', []))}"
            )
            for tk in m.get("tasks", []):
                click.echo(
                    f"    task {tk['id']} type={tk.get('type', '?')} "
                    f"status={tk.get('status', '?')}"
                )


@task_group.command(name="awaiting", cls=AgentFriendlyCommand)
@click.option("--json", "as_json", is_flag=True, default=False)
def task_awaiting(as_json: bool):
    """List Msgs in status=awaiting_decision (PA has not decided yet).

    Helps diagnose PA stalled / queue backlog.

    Examples:
      frago task awaiting
      frago task awaiting --json
    """
    board, timeline_path = _fold_board_offline()
    rows: list[dict] = []
    if board is not None:
        for t in board.view_for_pa().get("threads", []):
            for m in t.get("msgs", []):
                if m.get("status") != "awaiting_decision":
                    continue
                rows.append({
                    "thread_id": t.get("id"),
                    "subkind": t.get("subkind"),
                    "msg_id": m.get("id"),
                    "channel": m.get("channel"),
                    "sender_id": m.get("sender_id"),
                })

    payload = {"count": len(rows), "awaiting": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("(no msgs awaiting PA decision)")
        return
    for r in rows:
        click.echo(
            f"awaiting {r['msg_id']} thread={r['thread_id']} channel={r.get('channel', '?')} sender={r.get('sender_id', '?')}"
        )


@task_group.command(name="active", cls=AgentFriendlyCommand)
@click.option("--json", "as_json", is_flag=True, default=False)
def task_active(as_json: bool):
    """List Tasks in status in {queued, executing}.

    Helps diagnose sub-agent stalled / executor backlog.

    Examples:
      frago task active
      frago task active --json
    """
    board, _ = _fold_board_offline()
    rows: list[dict] = []
    active_set = {"queued", "executing"}
    if board is not None:
        for t in board.view_for_pa().get("threads", []):
            for m in t.get("msgs", []):
                for tk in m.get("tasks", []):
                    if tk.get("status") not in active_set:
                        continue
                    rows.append({
                        "thread_id": t.get("id"),
                        "msg_id": m.get("id"),
                        "task_id": tk.get("id"),
                        "type": tk.get("type"),
                        "status": tk.get("status"),
                    })

    payload = {"count": len(rows), "active": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("(no active tasks: queued or executing)")
        return
    for r in rows:
        click.echo(
            f"active {r['task_id']} type={r.get('type', '?')} status={r.get('status', '?')} "
            f"msg={r.get('msg_id', '?')}"
        )


@task_group.command(name="vacuum", cls=AgentFriendlyCommand)
@click.option("--max-markers", type=int, default=100,
              help="Bounded-progress cap on archived threads processed per run (default 100)")
@click.option("--json", "as_json", is_flag=True, default=False)
def task_vacuum(max_markers, as_json):
    """Alias for ``frago timeline vacuum``: archive retired threads.

    Spec 20260512 line 11 places this in the `tasks` command group too —
    discoverability for agents reasoning about task lifecycle.

    Examples:
      frago task vacuum
      frago task vacuum --max-markers 200 --json
    """
    from frago.cli.timeline_commands import _run_vacuum
    _run_vacuum(max_markers, as_json)


@task_group.command(name="stats", cls=AgentFriendlyCommand)
@click.option("--json", "as_json", is_flag=True, default=False)
def task_stats(as_json: bool):
    """Long-running health stats for the board.

    Reports:
      timeline_bytes       — current ~/.frago/timeline/timeline.jsonl size
      threads_count        — total threads on board (active + dormant + closed + archived)
      active_msgs          — msgs in awaiting_decision / dispatched
      queued_tasks         — tasks in queued
      executing_tasks      — tasks in executing
      archived_threads     — last vacuum cycle's archived_threads_count (from
                             most recent startup_fold_completed entry)
      last_fold_duration_ms — most recent boot fold duration

    Examples:
      frago task stats
      frago task stats --json | jq '.timeline_bytes'
    """
    from pathlib import Path as _Path

    timeline_path = _Path.home() / ".frago" / "timeline" / "timeline.jsonl"
    timeline_bytes = timeline_path.stat().st_size if timeline_path.exists() else 0

    board, _ = _fold_board_offline()
    threads_count = 0
    active_msgs = 0
    queued_tasks = 0
    executing_tasks = 0
    if board is not None:
        view = board.view_for_pa()
        threads_count = len(view.get("threads", []))
        for t in view.get("threads", []):
            for m in t.get("msgs", []):
                if m.get("status") in {"awaiting_decision", "dispatched"}:
                    active_msgs += 1
                for tk in m.get("tasks", []):
                    s = tk.get("status")
                    if s == "queued":
                        queued_tasks += 1
                    elif s == "executing":
                        executing_tasks += 1

    archived_threads = 0
    last_fold_duration_ms: int | None = None
    if timeline_path.exists():
        # walk from end backwards for the latest startup_fold_completed
        try:
            for line in reversed(timeline_path.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("data_type") == "startup_fold_completed":
                    data = entry.get("data") or {}
                    archived_threads = int(data.get("archived_threads_count", 0))
                    last_fold_duration_ms = data.get("fold_duration_ms")
                    break
        except OSError:
            pass

    payload = {
        "timeline_bytes": timeline_bytes,
        "threads_count": threads_count,
        "active_msgs": active_msgs,
        "queued_tasks": queued_tasks,
        "executing_tasks": executing_tasks,
        "archived_threads": archived_threads,
        "last_fold_duration_ms": last_fold_duration_ms,
    }

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"timeline_bytes={payload['timeline_bytes']} threads={payload['threads_count']} "
        f"active_msgs={payload['active_msgs']} queued={payload['queued_tasks']} "
        f"executing={payload['executing_tasks']} archived={payload['archived_threads']} "
        f"last_fold_ms={payload['last_fold_duration_ms']}"
    )
