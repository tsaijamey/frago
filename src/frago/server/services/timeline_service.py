"""Timeline aggregation service.

Merges events from multiple data sources into a unified timeline:
1. IngestedTask (ingestion events)
2. Pipeline trace (trace JSONL — decision, reply, agent lifecycle)

Returns TimelineAggEvent list sorted by timestamp, with humanized title/subtitle.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime

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
    detail: dict | None = None
    raw_data: dict | None = None
    children: list | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def _humanize_pa_event(event_type: str, data: dict) -> tuple[str, str | None]:
    """Generate human-readable title/subtitle for a PA event."""
    if event_type == "pa_ingestion":
        channel = data.get("channel", "")
        prompt = data.get("prompt", "")
        # Extract instruction tag if present
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


def get_timeline(since: str | None = None, limit: int = 50) -> list[dict]:
    """Get aggregated timeline events.

    Args:
        since: ISO timestamp — only return events after this time
        limit: Max number of events to return

    Returns:
        List of TimelineAggEvent dicts, sorted by timestamp (oldest first)
    """
    since_dt = datetime.fromisoformat(since) if since else None
    all_events: list[TimelineAggEvent] = []

    # Source 1: IngestedTask → ingestion events
    try:
        from frago.server.services.ingestion.store import TaskStore
        store = TaskStore()
        tasks = store.get_recent(limit=limit)
        for t in tasks:
            title, subtitle = _humanize_pa_event("pa_ingestion", {
                "channel": t.channel,
                "prompt": t.prompt,
            })
            all_events.append(TimelineAggEvent(
                id=f"task-{t.id}",
                timestamp=t.created_at if isinstance(t.created_at, str) else t.created_at.isoformat(),
                event_type="ingestion",
                source="task",
                title=title,
                subtitle=subtitle,
                task_id=t.id,
                raw_data={"channel": t.channel, "prompt": t.prompt, "status": t.status.value if hasattr(t.status, 'value') else str(t.status)},
            ))
    except Exception as e:
        logger.debug("Failed to load ingested tasks for timeline: %s", e)

    # Source 2: Pipeline trace events (from trace JSONL files)
    try:
        from frago.server.services.trace import load_trace_events
        trace_events = load_trace_events(since=since_dt, limit=limit)
    except Exception as e:
        logger.debug("Failed to load trace events: %s", e)
        trace_events = []

    for entry in trace_events:
        et = entry.get("event_type", "")
        data = entry.get("data", {})
        ts = entry.get("timestamp", "")
        title, subtitle = _humanize_pa_event(et, data)

        # Map PA event types to timeline event types
        type_map = {
            "pa_ingestion": "ingestion",
            "pa_decision": "pa_decision",
            "pa_agent_launched": "agent_launched",
            "pa_agent_exited": "agent_exited",
            "pa_reply": "pa_reply",
        }

        all_events.append(TimelineAggEvent(
            id=f"pa-{et}-{ts}",
            timestamp=ts,
            event_type=type_map.get(et, et),
            source="pa",
            title=title,
            subtitle=subtitle,
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
            raw_data=data,
        ))

    # Sort by timestamp, oldest first
    all_events.sort(key=lambda e: e.timestamp)

    # Apply since filter
    if since_dt:
        all_events = [e for e in all_events if e.timestamp > since]

    # Deduplicate: prefer PA source over task source for same event
    seen_tasks = set()
    deduped = []
    for e in all_events:
        if e.source == "pa" and e.event_type == "ingestion" and e.task_id:
            seen_tasks.add(e.task_id)
        if e.source == "task" and e.task_id in seen_tasks:
            continue
        deduped.append(e)

    return [e.to_dict() for e in deduped[-limit:]]
