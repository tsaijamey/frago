"""Timeline CLI commands (spec 20260418-timeline-event-coverage Phase 6).

Agent-facing surface for timeline queries. Agents MUST use these instead of
reading ~/.frago/traces/ directly so the underlying JSONL schema can evolve.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from frago.server.services.trace import (
    TRACE_DIR,
    TimelineEntry,
    latest_entry_for_task,
)
from frago.server.services.trace import (
    trace_entry as _trace_entry,
)


def _emit(payload, *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        click.echo(json.dumps(payload, ensure_ascii=False, default=str))


def _fail(message: str, *, hint: str | None = None, exit_code: int = 1) -> None:
    payload = {"error": message}
    if hint:
        payload["hint"] = hint
    click.echo(json.dumps(payload, ensure_ascii=False), err=True)
    raise SystemExit(exit_code)


def _iter_entries(lookback_days: int = 7):
    """Yield entries from trace files, newest-file first, newest-line first."""
    today = datetime.now().date()
    for days_ago in range(lookback_days):
        date = today - timedelta(days=days_ago)
        path = TRACE_DIR / f"trace-{date.strftime('%Y-%m-%d')}.jsonl"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


@click.group(name="timeline", cls=AgentFriendlyGroup)
def timeline_group():
    """Query and append to the unified timeline."""
    pass


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@timeline_group.command(name="tail", cls=AgentFriendlyCommand)
@click.option("--thread", "thread_id", default=None, help="Filter by thread_id")
@click.option("--task-id", "task_id", default=None, help="Filter by task_id")
@click.option("--data-type", "data_type", default=None, help="Filter by data_type (message/thought/task_state/...)")
@click.option("--origin", default=None, help="Filter by origin (external/internal)")
@click.option("--limit", type=int, default=20, help="Max entries (default 20)")
@click.option("--lookback-days", type=int, default=3, help="Look back N days (default 3)")
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_tail(thread_id, task_id, data_type, origin, limit, lookback_days, as_json):
    """Show the most recent timeline entries (newest first).

    Examples:
      frago timeline tail --thread 01HW001 --limit 20
      frago timeline tail --data-type task_state --task-id t_abc
      frago timeline tail --origin internal --limit 50
    """
    out: list[dict] = []
    for entry in _iter_entries(lookback_days=lookback_days):
        if thread_id and entry.get("thread_id") != thread_id:
            continue
        if task_id and entry.get("task_id") != task_id:
            continue
        if data_type and entry.get("data_type") != data_type:
            continue
        if origin and entry.get("origin") != origin:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    _emit({"entries": out, "count": len(out)}, as_json=as_json)


@timeline_group.command(name="trace", cls=AgentFriendlyCommand)
@click.argument("entry_id", required=True)
@click.option("--lookback-days", type=int, default=7)
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_trace(entry_id, lookback_days, as_json):
    """Walk parent_id chain from the given entry up to its thread root.

    Examples:
      frago timeline trace 01HW_ENTRY_XYZ
    """
    # Build id→entry index on demand (limited lookback)
    index: dict[str, dict] = {}
    for entry in _iter_entries(lookback_days=lookback_days):
        eid = entry.get("id")
        if eid:
            index[eid] = entry
    if entry_id not in index:
        _fail(f"entry not found: {entry_id}",
              hint="entry may be older than lookback window; increase --lookback-days")

    chain: list[dict] = []
    cur = entry_id
    while cur and cur in index and len(chain) < 500:
        entry = index[cur]
        chain.append(entry)
        parent = entry.get("parent_id")
        if not parent or parent == cur:
            break
        cur = parent
    _emit({"chain": chain, "length": len(chain)}, as_json=as_json)


@timeline_group.command(name="search", cls=AgentFriendlyCommand)
@click.option("--task-id", "task_id", default=None)
@click.option("--data-type", "data_type", default=None)
@click.option("--origin", default=None)
@click.option("--subkind", default=None)
@click.option("--limit", type=int, default=50)
@click.option("--lookback-days", type=int, default=7)
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_search(task_id, data_type, origin, subkind, limit, lookback_days, as_json):
    """Search timeline entries by structured filters.

    Examples:
      frago timeline search --task-id t_abc --data-type task_state
      frago timeline search --subkind reflection --lookback-days 1
    """
    if not any([task_id, data_type, origin, subkind]):
        _fail("at least one filter is required",
              hint="use --task-id / --data-type / --origin / --subkind")
    out: list[dict] = []
    for entry in _iter_entries(lookback_days=lookback_days):
        if task_id and entry.get("task_id") != task_id:
            continue
        if data_type and entry.get("data_type") != data_type:
            continue
        if origin and entry.get("origin") != origin:
            continue
        if subkind and entry.get("subkind") != subkind:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    _emit({"entries": out, "count": len(out)}, as_json=as_json)


@timeline_group.command(name="view", cls=AgentFriendlyCommand)
@click.option("--recent", default="24h", help="Window: e.g. 1h, 24h, 7d (default 24h)")
@click.option("--collapsed/--full", default=True,
              help="Collapsed: group by thread; full: raw entries")
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_view(recent, collapsed, as_json):
    """High-level timeline view for the given window.

    Collapsed mode groups entries by thread and shows a thread-level summary
    (active threads sorted by last activity).

    Examples:
      frago timeline view --recent 1h
      frago timeline view --recent 7d --full
    """
    # Parse window spec
    unit = recent[-1]
    try:
        amount = int(recent[:-1])
    except (ValueError, IndexError):
        _fail(f"invalid --recent {recent!r}",
              hint="format: <number><h|d>, e.g. 1h, 24h, 7d")
    if unit == "h":
        cutoff = datetime.now() - timedelta(hours=amount)
        lookback_days = max(1, (amount // 24) + 1)
    elif unit == "d":
        cutoff = datetime.now() - timedelta(days=amount)
        lookback_days = amount + 1
    else:
        _fail(f"invalid --recent unit {unit!r}", hint="use 'h' (hours) or 'd' (days)")

    entries: list[dict] = []
    for entry in _iter_entries(lookback_days=lookback_days):
        try:
            ts = datetime.fromisoformat(entry.get("ts", ""))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        entries.append(entry)

    if not collapsed:
        _emit({"entries": entries, "count": len(entries),
               "window": recent}, as_json=as_json)
        return

    # Group by thread, take per-thread summary
    by_thread: dict[str, dict] = {}
    for entry in entries:
        tid = entry.get("thread_id") or "(no-thread)"
        meta = by_thread.setdefault(tid, {
            "thread_id": tid,
            "first_ts": entry.get("ts"),
            "last_ts": entry.get("ts"),
            "entry_count": 0,
            "data_types": {},
            "latest_event": None,
            "origin": entry.get("origin"),
            "subkind": entry.get("subkind"),
        })
        meta["entry_count"] += 1
        ts = entry.get("ts", "")
        if ts > meta["last_ts"]:
            meta["last_ts"] = ts
            meta["latest_event"] = entry.get("event") or entry.get("data_type")
        if ts < meta["first_ts"]:
            meta["first_ts"] = ts
        dtype = entry.get("data_type") or "unknown"
        meta["data_types"][dtype] = meta["data_types"].get(dtype, 0) + 1

    threads = sorted(by_thread.values(), key=lambda m: m["last_ts"], reverse=True)
    _emit({
        "window": recent,
        "thread_count": len(threads),
        "entry_count": len(entries),
        "threads": threads,
    }, as_json=as_json)


@timeline_group.command(name="task-status", cls=AgentFriendlyCommand)
@click.argument("task_id", required=True)
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_task_status(task_id, as_json):
    """Show the current status of a task (reconstructed from timeline).

    Single source: board.timeline.jsonl (spec 20260512 v1.2 freeze — no
    secondary persistence remains).

    Examples:
      frago timeline task-status t_abc123
    """
    entry = latest_entry_for_task(task_id, data_type="task_state")
    if not entry:
        _fail(f"no task_state entry found for task {task_id}",
              hint="verify task_id or check if task was created before timeline schema upgrade")
    data = entry.get("data") or {}
    _emit({
        "task_id": task_id,
        "current_status": data.get("status"),
        "prev_status": data.get("prev_status"),
        "last_update_ts": entry.get("ts"),
        "thread_id": entry.get("thread_id"),
        "error": data.get("error"),
    }, as_json=as_json)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

@timeline_group.command(name="append", cls=AgentFriendlyCommand)
@click.option("--origin", required=True, type=click.Choice(["external", "internal"]))
@click.option("--subkind", required=True, help="Channel name or trigger type")
@click.option("--data-type", "data_type", required=True,
              help="message | thought | task_state | tool_call | result | os_event | ...")
@click.option("--thread", "thread_id", default=None,
              help="Thread to append to; omit to create new root")
@click.option("--parent", "parent_id", default=None,
              help="Parent entry id (must share thread_id)")
@click.option("--task-id", "task_id", default=None)
@click.option("--data", "data_json", default=None, help="JSON payload")
@click.option("--event", default=None, help="Human-readable event description")
def timeline_append(origin, subkind, data_type, thread_id, parent_id, task_id, data_json, event):
    """Append an entry to the timeline (agent-initiated).

    Typical use: record an agent thought, tool_call, or observation that is
    not auto-traced by existing producers.

    Examples:
      frago timeline append --origin internal --subkind pa --data-type thought --thread 01HW001 --event "considering next step"
      frago timeline append --origin internal --subkind observation --data-type os_event --data '{"kind":"state_change"}'
    """
    data: dict | None = None
    if data_json:
        try:
            data = json.loads(data_json)
        except json.JSONDecodeError as e:
            _fail(f"invalid JSON in --data: {e}",
                  hint='use proper JSON, e.g. --data \'{"key":"value"}\'')
        if not isinstance(data, dict):
            _fail("--data must be a JSON object",
                  hint='e.g. --data \'{"key":"value"}\'')

    entry: TimelineEntry = _trace_entry(
        origin=origin,
        subkind=subkind,
        data_type=data_type,
        thread_id=thread_id,
        parent_id=parent_id,
        task_id=task_id,
        data=data,
        event=event,
    )
    click.echo(json.dumps({
        "id": entry.id,
        "thread_id": entry.thread_id,
        "parent_id": entry.parent_id,
        "ts": entry.ts,
    }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Maintenance (Phase 2: taskboard timeline.jsonl vacuum + fold)
# ---------------------------------------------------------------------------


def _frago_home() -> Path:
    import os as _os

    custom = _os.environ.get("FRAGO_HOME")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".frago"


def _run_vacuum(max_markers: int, as_json: bool) -> None:
    """Shared implementation for ``frago timeline vacuum`` and ``frago task vacuum``."""
    from frago.server.services.taskboard import vacuum as vac

    home = _frago_home()
    report = vac.run_bounded_vacuum(home, max_markers=max_markers)
    payload = {
        "processed": report.processed,
        "archived_thread_ids": list(report.archived_thread_ids),
        "max_markers": max_markers,
    }
    _emit(payload, as_json=as_json)


@timeline_group.command(name="vacuum", cls=AgentFriendlyCommand)
@click.option("--max-markers", type=int, default=100,
              help="Bounded-progress cap on archived threads processed per run (default 100, Yi #92 lock)")
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_vacuum(max_markers, as_json):
    """Run bounded-progress vacuum: archive retired threads into archive/<tid>.jsonl.

    Scans ~/.frago/timeline/timeline.jsonl for `thread_archived` markers (data_type),
    moves all entries belonging to archived threads into separate per-thread files
    under ~/.frago/timeline/archive/, and atomically rewrites the main timeline.

    Equivalent to triggering an offline server restart for vacuum purposes only.

    Examples:
      frago timeline vacuum
      frago timeline vacuum --max-markers 200 --json
    """
    _run_vacuum(max_markers, as_json)


@timeline_group.command(name="fold", cls=AgentFriendlyCommand)
@click.option("--thread", "thread_id", required=True,
              help="Thread id to compact (e.g. T_ABC). Required.")
@click.option("--json", "as_json", is_flag=True, default=False)
def timeline_fold(thread_id, as_json):
    """Fold redundant entries inside a thread into a single summary entry.

    Currently compacts `duplicate_msg_ingest` entries (grouped by msg_id + channel)
    into one `duplicate_msg_ingest_summary` entry per group containing the count,
    first/last entry_id, and first/last ts. Reduces PA context noise for high-churn
    threads where the same message id is repeatedly seen by the ingestor.

    Operates in-place via two-pass scan + atomic replace.

    Examples:
      frago timeline fold --thread T_ABC
      frago timeline fold --thread T_ABC --json
    """
    from frago.server.services.taskboard import vacuum as vac

    home = _frago_home()
    report = vac.fold_thread_duplicates(home, thread_id)
    payload = {
        "thread_id": report.thread_id,
        "folded_count": report.folded_count,
        "summary_entries_written": report.summary_entries_written,
        "bytes_before": report.bytes_before,
        "bytes_after": report.bytes_after,
    }
    _emit(payload, as_json=as_json)


# Silence Path import ruff warning (used for future extension)
_ = Path
