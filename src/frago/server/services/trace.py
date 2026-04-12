"""Pipeline trace logger.

Writes one JSONL entry per pipeline hop: role + event + timestamp.
Daily file rotation with automatic cleanup of old files.

File location: ~/.frago/traces/trace-YYYY-MM-DD.jsonl
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRACE_DIR = Path.home() / ".frago" / "traces"
RETENTION_DAYS = 30


def _trace_file_for_today() -> Path:
    return TRACE_DIR / f"trace-{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def trace(
    msg_id: str,
    task_id: str | None,
    role: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Append one trace entry. Fire-and-forget — never raises."""
    try:
        path = _trace_file_for_today()
        path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "msg_id": msg_id,
            "task_id": task_id,
            "role": role,
            "event": event,
            "ts": datetime.now().isoformat(),
        }
        if data:
            entry["data"] = data
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def cleanup_old_traces() -> None:
    """Delete trace files older than RETENTION_DAYS. Called on server startup."""
    if not TRACE_DIR.exists():
        return
    cutoff = datetime.now().date() - timedelta(days=RETENTION_DAYS)
    for f in TRACE_DIR.glob("trace-*.jsonl"):
        try:
            date_str = f.stem.replace("trace-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if file_date < cutoff:
                f.unlink()
                logger.debug("Cleaned up old trace file: %s", f.name)
        except (ValueError, OSError):
            pass


def load_trace_events(
    since: datetime | None = None,
    limit: int = 100,
    lookback_days: int = 7,
) -> list[dict[str, Any]]:
    """Load trace entries that have data (timeline-worthy events).

    Returns entries in pa_events-compatible format for timeline_service consumption:
    [{"timestamp": ..., "event_type": ..., "data": {...}}, ...]
    """
    # Pass 1: scan ALL entries (including no-data ones) to build task_id → msg_id map.
    # Agent-completed replies lose msg_id at top level, but the earlier task creation
    # entry for the same task_id does have it.
    task_msg_map: dict[str, str] = {}
    today = datetime.now().date()
    raw_lines: list[tuple[datetime, dict[str, Any]]] = []

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
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    ts = datetime.fromisoformat(entry.get("ts", ""))
                    if since and ts < since:
                        continue
                    # Build task_id → msg_id from entries that have both
                    tid = entry.get("task_id", "")
                    mid = entry.get("msg_id", "")
                    if tid and mid:
                        task_msg_map.setdefault(tid, mid)
                    raw_lines.append((ts, entry))
        except Exception:
            continue

    # Pass 2: filter to data-bearing entries and resolve msg_id
    entries: list[dict[str, Any]] = []
    for _ts, entry in raw_lines:
        if not entry.get("data"):
            continue
        raw_data = entry["data"]
        event_type = raw_data.pop("event_type", "")

        # Resolve msg_id: data field > top-level > task_id lookup
        if "msg_id" not in raw_data or not raw_data.get("msg_id"):
            mid = entry.get("msg_id", "")
            if not mid:
                tid = entry.get("task_id", "") or raw_data.get("task_id", "")
                mid = task_msg_map.get(tid, "")
            if mid:
                raw_data["msg_id"] = mid

        if "task_id" not in raw_data and entry.get("task_id"):
            raw_data["task_id"] = entry["task_id"]

        entries.append({
            "timestamp": entry["ts"],
            "event_type": event_type,
            "data": raw_data,
        })

    return entries[-limit:]


# ---------------------------------------------------------------------------
# Conversation turn extraction for PA reborn context injection
# ---------------------------------------------------------------------------

@dataclass
class ConversationTurn:
    """One conversation round: user message + PA response."""

    timestamp: str
    channel: str
    user_message: str
    pa_response: str | None
    task_id: str | None
    action: str  # "reply" | "dispatch" | "pending"


def _extract_instruction(prompt: str) -> str:
    """Extract user instruction from prompt, stripping XML tags and context."""
    m = re.search(r"<instruction>\s*(.*?)\s*</instruction>", prompt, re.DOTALL)
    if m:
        text = m.group(1)
        text = re.sub(r"<quoted_message>.*?</quoted_message>\s*", "", text, flags=re.DOTALL)
        return text.strip()
    return prompt.strip()


def _truncate(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _parse_all_conversation_turns() -> list[ConversationTurn]:
    """Parse today + yesterday trace files into conversation turns (oldest → newest)."""
    today = datetime.now().date()
    entries: list[dict[str, Any]] = []

    for days_ago in range(2):
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
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    role = entry.get("role", "")
                    if role not in ("scheduler", "pa"):
                        continue
                    entries.append(entry)
        except Exception:
            continue

    entries.sort(key=lambda e: e.get("ts", ""))

    # Phase 1: collect user messages (scheduler ingestion events)
    user_messages: dict[str, dict[str, Any]] = {}  # msg_id -> entry
    for entry in entries:
        if entry.get("role") != "scheduler":
            continue
        event = entry.get("event", "")
        if not event.startswith("收到 "):
            continue
        msg_id = entry.get("msg_id", "")
        if not msg_id:
            continue
        user_messages[msg_id] = entry

    # Phase 2: collect PA responses (first decision per msg_id)
    pa_responses: dict[str, dict[str, Any]] = {}  # msg_id -> entry
    for entry in entries:
        if entry.get("role") != "pa":
            continue
        event = entry.get("event", "")
        if not event.startswith("决策 "):
            continue
        msg_id = entry.get("msg_id", "")
        if not msg_id:
            continue
        if msg_id not in pa_responses:
            pa_responses[msg_id] = entry

    # Phase 3: pair into ConversationTurns
    turns: list[ConversationTurn] = []
    for msg_id, user_entry in user_messages.items():
        data = user_entry.get("data") or {}
        prompt_text = data.get("prompt", "")
        user_text = _extract_instruction(prompt_text) if prompt_text else ""
        if not user_text:
            continue

        channel = data.get("channel", "unknown")

        pa_entry = pa_responses.get(msg_id)
        pa_text: str | None = None
        action = "pending"
        task_id: str | None = None

        if pa_entry:
            pa_data = pa_entry.get("data") or {}
            pa_action = pa_data.get("action", "")
            details = pa_data.get("details") or {}

            if pa_action == "reply":
                pa_text = details.get("text", "")
                action = "reply"
            elif pa_action == "run":
                pa_text = f"派发任务: {details.get('description', '')}"
                action = "dispatch"
            task_id = pa_entry.get("task_id") or pa_data.get("task_id") or None

        turns.append(ConversationTurn(
            timestamp=user_entry.get("ts", ""),
            channel=channel,
            user_message=_truncate(user_text),
            pa_response=_truncate(pa_text) if pa_text else None,
            task_id=task_id,
            action=action,
        ))

    return turns


def load_conversation_turns(limit: int = 20) -> list[ConversationTurn]:
    """Extract recent user↔PA conversation turns from trace JSONL.

    Reads today + yesterday trace files, pairs scheduler ingestion events
    with PA decision/reply events by msg_id.
    """
    return _parse_all_conversation_turns()[-limit:]


def load_conversation_turns_by_channel(
    per_channel_limit: int = 10,
) -> dict[str, list[ConversationTurn]]:
    """Group recent conversation turns by channel, keeping the latest N per channel.

    Returned dict iteration order matches first-seen order; callers that need
    "most recently active first" should sort by the last turn's timestamp.
    """
    by_channel: dict[str, list[ConversationTurn]] = {}
    for turn in _parse_all_conversation_turns():
        by_channel.setdefault(turn.channel, []).append(turn)
    return {ch: turns[-per_channel_limit:] for ch, turns in by_channel.items()}


def get_last_active_channel() -> str | None:
    """Return the channel of the most recent user message from trace, or None."""
    turns = load_conversation_turns(limit=1)
    if turns:
        ch = turns[-1].channel
        if ch and ch != "unknown":
            return ch
    return None
