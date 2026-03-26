"""Timeline aggregation service.

Merges events from multiple data sources into a unified timeline:
1. IngestedTask (ingestion events)
2. PA events (pa_events.jsonl — decision, reply, agent lifecycle)
3. Run logs (execution.jsonl)

Returns TimelineAggEvent list sorted by timestamp, with humanized title/subtitle.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# PA events log file
PA_EVENTS_FILE = Path.home() / ".frago" / "pa_events.jsonl"


@dataclass
class TimelineAggEvent:
    """Aggregated timeline event for frontend consumption."""
    id: str
    timestamp: str
    event_type: str
    source: str
    title: str
    subtitle: Optional[str] = None
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    detail: Optional[dict] = None
    raw_data: Optional[dict] = None
    children: Optional[list] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def append_pa_event(event_type: str, data: dict) -> None:
    """Append a PA event to the persistent log file.

    Called from primary_agent_service.py alongside WebSocket broadcast.
    Fire-and-forget — failures are logged and swallowed.
    """
    try:
        PA_EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data,
        }
        with open(PA_EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug("Failed to persist PA event %s: %s", event_type, e)


def _load_pa_events(since: Optional[datetime] = None, limit: int = 100) -> list[dict]:
    """Load PA events from the JSONL log file."""
    events = []
    if not PA_EVENTS_FILE.exists():
        return events

    try:
        with open(PA_EVENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if since:
                        ts = datetime.fromisoformat(entry.get("timestamp", ""))
                        if ts < since:
                            continue
                    events.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception as e:
        logger.debug("Failed to read PA events: %s", e)

    # Return most recent entries
    return events[-limit:]


def _humanize_pa_event(event_type: str, data: dict) -> tuple[str, Optional[str]]:
    """Generate human-readable title/subtitle for a PA event."""
    if event_type == "pa_ingestion":
        channel = data.get("channel", "")
        prompt = data.get("prompt", "")
        # Extract instruction tag if present
        import re
        match = re.search(r'<instruction>\s*([\s\S]*?)\s*</instruction>', prompt)
        instruction = match.group(1).strip() if match else prompt[:80]
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
        return title, str(desc)[:80] if desc else None

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
        return f"已回复 {channel}", text[:80] if text else None

    return event_type, None


def get_timeline(since: Optional[str] = None, limit: int = 50) -> list[dict]:
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

    # Source 2: PA events (from JSONL)
    pa_events = _load_pa_events(since=since_dt, limit=limit)
    for entry in pa_events:
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
