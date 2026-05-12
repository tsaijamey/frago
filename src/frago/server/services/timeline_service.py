"""Timeline aggregation service.

Merges events from multiple data sources into a unified timeline:
1. Pipeline trace (trace JSONL — decision, reply, agent lifecycle)

Returns TimelineAggEvent list sorted by timestamp, with humanized title/subtitle.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TimelineAggEvent:
    """Aggregated timeline event for frontend consumption."""
    id: str
    timestamp: str
    event_type: str
    source: str
    title: str
    subtitle: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    msg_id: str | None = None
    detail: dict | None = None
    raw_data: dict | None = None
    children: list | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def _humanize_pa_event(event_type: str, data: dict) -> tuple[str, str | None]:
    """Generate human-readable title/subtitle for a PA event.

    Returns:
        (title, subtitle)
    """
    if event_type == "pa_ingestion":
        channel = data.get("channel", "")
        prompt = data.get("prompt", "")
        import re
        match = re.search(r'<instruction>\s*([\s\S]*?)\s*</instruction>', prompt)
        instruction = match.group(1).strip() if match else prompt
        return f"收到 {channel} 消息", instruction

    elif event_type == "pa_decision":
        action = data.get("action", "")
        details = data.get("details", {})
        desc = details.get("description", "") or details.get("recipe_name", "") or details.get("prompt", "")
        titles = {
            "run": "分配任务给 Agent",
            "reply": "回复消息",
            "resume": "继续执行",
            "recipe": "执行配方",
            "update": "更新任务状态",
        }
        title = titles.get(action, action)
        return title, str(desc) if desc else None

    elif event_type == "pa_agent_launched":
        desc = data.get("description", "")
        return "Agent 开始执行", desc or None

    elif event_type == "pa_agent_exited":
        has_completion = data.get("has_completion", False)
        duration = data.get("duration_seconds")
        title = "Agent 执行完毕" if has_completion else "Agent 异常退出"
        subtitle = f"耗时 {duration}s" if duration else None
        return title, subtitle

    elif event_type == "pa_reply":
        channel = data.get("channel", "")
        text = data.get("reply_text", "")
        return f"已回复 {channel}", text if text else None

    return event_type, None


# Type mapping from trace event_type to timeline event_type
_TYPE_MAP = {
    "pa_ingestion": "ingestion",
    "pa_decision": "pa_decision",
    "pa_agent_launched": "agent_launched",
    "pa_agent_exited": "agent_exited",
    "pa_reply": "pa_reply",
}


def humanize_event(event_type: str, data: dict) -> dict:
    """Public API for WS broadcast — returns humanized fields dict."""
    title, subtitle = _humanize_pa_event(event_type, data)
    return {
        "event_type": _TYPE_MAP.get(event_type, event_type),
        "title": title,
        "subtitle": subtitle,
    }


def get_timeline(since: str | None = None, limit: int = 50) -> list[dict]:
    """Get aggregated timeline events from trace JSONL.

    Args:
        since: ISO timestamp — only return events after this time
        limit: Max number of events to return

    Returns:
        List of TimelineAggEvent dicts, sorted by timestamp (oldest first)
    """
    since_dt = datetime.fromisoformat(since) if since else None

    try:
        from frago.server.services.trace import load_trace_events
        trace_events = load_trace_events(since=since_dt, limit=limit)
    except Exception as e:
        logger.debug("Failed to load trace events: %s", e)
        trace_events = []

    all_events: list[TimelineAggEvent] = []
    for entry in trace_events:
        et = entry.get("event_type", "")
        data = entry.get("data", {})
        ts = entry.get("timestamp", "")
        title, subtitle = _humanize_pa_event(et, data)

        all_events.append(TimelineAggEvent(
            id=f"pa-{et}-{ts}",
            timestamp=ts,
            event_type=_TYPE_MAP.get(et, et),
            source="trace",
            title=title,
            subtitle=subtitle,
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
            msg_id=data.get("msg_id"),
            raw_data=data,
        ))

    all_events.sort(key=lambda e: e.timestamp)

    if since_dt:
        all_events = [e for e in all_events if e.timestamp > since]

    return [e.to_dict() for e in all_events[-limit:]]


# ---------------------------------------------------------------------------
# Thread-aware folded view (spec 20260418-timeline-consumer-unification Phase 1)
# ---------------------------------------------------------------------------

HOT_WINDOW_HOURS = 24
WARM_WINDOW_DAYS = 7


@dataclass
class ThreadDigest:
    """Compressed summary of a thread (used for warm tier)."""

    thread_id: str
    origin: str
    subkind: str
    root_summary: str
    status: str
    last_active_ts: str
    entry_count: int = 0
    task_status_summary: dict[str, str] = field(default_factory=dict)
    latest_event: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ThreadExpanded:
    """Full-detail view of a hot thread: digest + recent entries."""

    digest: ThreadDigest
    entries: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"digest": self.digest.to_dict(), "entries": self.entries}


def _iter_trace_entries(lookback_days: int):
    """Yield raw trace entries within lookback_days (newest day first, lines in file order)."""
    from frago.server.services.trace import TRACE_DIR

    today = datetime.now().date()
    for days_ago in range(lookback_days):
        date = today - timedelta(days=days_ago)
        path = TRACE_DIR / f"trace-{date.strftime('%Y-%m-%d')}.jsonl"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue


def _collect_entries_by_thread(lookback_days: int) -> dict[str, list[dict]]:
    """Group trace entries by thread_id within the lookback window."""
    by_thread: dict[str, list[dict]] = {}
    for entry in _iter_trace_entries(lookback_days):
        tid = entry.get("thread_id")
        if not tid:
            continue
        by_thread.setdefault(tid, []).append(entry)
    # Sort each thread's entries by ts asc
    for tid in by_thread:
        by_thread[tid].sort(key=lambda e: e.get("ts", ""))
    return by_thread


def _build_digest(thread_dict: dict, entries: list[dict]) -> ThreadDigest:
    """Compose a ThreadDigest from board.get_thread() dict + its trace entries.

    B-2b: thread_dict 是 board.get_thread / list_threads 返回的 dict
    (Yi #94 b' dict 风格), 不再是 ThreadIndex dataclass.
    """
    latest = entries[-1] if entries else None
    latest_event = None
    if latest:
        latest_event = latest.get("event") or latest.get("data_type")

    # Reconstruct per-task latest status from task_state entries
    task_status_summary: dict[str, str] = {}
    for e in entries:
        if e.get("data_type") != "task_state":
            continue
        tid = e.get("task_id")
        if not tid:
            continue
        status = (e.get("data") or {}).get("status")
        if status:
            task_status_summary[tid] = status

    return ThreadDigest(
        thread_id=thread_dict["thread_id"],
        origin=thread_dict.get("origin", ""),
        subkind=thread_dict.get("subkind", ""),
        root_summary=thread_dict.get("root_summary", ""),
        status=thread_dict.get("status", "active"),
        last_active_ts=thread_dict.get("last_active_at", ""),
        entry_count=len(entries),
        task_status_summary=task_status_summary,
        latest_event=latest_event,
    )


def get_thread_context(
    *,
    hot_limit: int = 10,
    warm_limit: int = 20,
    hot_window_hours: int = HOT_WINDOW_HOURS,
    warm_window_days: int = WARM_WINDOW_DAYS,
    entries_per_hot: int = 30,
) -> dict:
    """Folded view of recent threads for PA context injection.

    hot threads: last_active within `hot_window_hours` — include ThreadExpanded
                 with up to `entries_per_hot` most recent entries.
    warm threads: last_active within [hot, warm_window_days] — include ThreadDigest only.
    Threads older than `warm_window_days` are not included (agent must hydrate explicitly).
    """
    # B-2b: 改读 TaskBoard. status 投射:
    # board "active" ≡ STATUS_ACTIVE; board "dormant" ≡ STATUS_IDLE.
    # closed/archived 不出现在 hot/warm (与 visible_statuses 对齐).
    from frago.server.services.taskboard import get_board

    board = get_board()
    now = datetime.now()
    hot_cutoff = now - timedelta(hours=hot_window_hours)
    warm_cutoff = now - timedelta(days=warm_window_days)

    threads_by_id = _collect_entries_by_thread(lookback_days=warm_window_days + 1)

    hot: list[ThreadExpanded] = []
    warm: list[ThreadDigest] = []
    threads = board.list_threads(statuses={"active", "dormant"})
    total_known = len(board.list_threads())

    for tdict in threads:
        last_raw = tdict.get("last_active_at", "")
        try:
            last_active = datetime.fromisoformat(last_raw)
        except ValueError:
            continue
        # Strip tz to compare with naive now if needed
        if last_active.tzinfo and not now.tzinfo:
            last_active = last_active.replace(tzinfo=None)
        if last_active < warm_cutoff:
            continue
        entries = threads_by_id.get(tdict["thread_id"], [])
        digest = _build_digest(tdict, entries)

        if last_active >= hot_cutoff:
            recent_entries = entries[-entries_per_hot:] if entries else []
            hot.append(ThreadExpanded(digest=digest, entries=recent_entries))
        else:
            warm.append(digest)

    hot.sort(key=lambda h: h.digest.last_active_ts, reverse=True)
    warm.sort(key=lambda d: d.last_active_ts, reverse=True)

    hot = hot[:hot_limit]
    warm = warm[:warm_limit]

    return {
        "hot": [h.to_dict() for h in hot],
        "warm": [d.to_dict() for d in warm],
        "cold_hint": (
            "Older threads are not loaded. Use `frago thread search <query>` "
            "to find them and `frago thread hydrate <id>` to load."
        ),
        "counts": {
            "hot": len(hot),
            "warm": len(warm),
            "total_known": total_known,
        },
    }


# Silence "imported but unused" — Path is re-exported for future extension
_ = Path
