"""Pipeline trace logger.

Writes one JSONL entry per pipeline hop: role + event + timestamp.
Daily file rotation with automatic cleanup of old files.

File location: ~/.frago/traces/trace-YYYY-MM-DD.jsonl

Schema扩展 (Spec 20260418-timeline-entry-schema):
每条 entry 除了 legacy 字段（msg_id/task_id/role/event/ts/data），
还携带 timeline 元数据 (id/origin/subkind/thread_id/parent_id/data_type)。
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRACE_DIR = Path.home() / ".frago" / "traces"
RETENTION_DAYS = 30

# ---------------------------------------------------------------------------
# Broadcast hook (spec 20260418-timeline-consumer-unification Phase 3)
# Lets server broadcast new-schema entries as `timeline_event` WS messages.
# Hook receives the entry dict after it's been persisted.
# ---------------------------------------------------------------------------

from collections.abc import Callable as _Callable  # noqa: E402

_broadcast_hook: _Callable[[dict[str, Any]], None] | None = None


def register_broadcast_hook(hook: _Callable[[dict[str, Any]], None] | None) -> None:
    """Install (or clear with None) the entry broadcast hook.

    Hook signature: hook(entry_dict) -> None. Must be non-blocking and not raise.
    Typically the server wires this to asyncio.run_coroutine_threadsafe → WS broadcast.
    """
    global _broadcast_hook
    _broadcast_hook = hook


# ---------------------------------------------------------------------------
# ULID — 26-char lexicographically sortable id (Crockford base32)
# ---------------------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ulid_lock = threading.Lock()
_ulid_last_ms = 0
_ulid_last_rand = 0


def _encode_base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def ulid_new() -> str:
    """Generate a 26-char ULID (48-bit ms timestamp + 80-bit random, Crockford base32).

    Guarantees strict monotonic increase for consecutive calls even within the
    same millisecond (increments the random portion).
    """
    global _ulid_last_ms, _ulid_last_rand
    with _ulid_lock:
        now_ms = int(time.time() * 1000)
        if now_ms <= _ulid_last_ms:
            now_ms = _ulid_last_ms
            rand = _ulid_last_rand + 1
        else:
            rand = int.from_bytes(os.urandom(10), "big")
        _ulid_last_ms = now_ms
        _ulid_last_rand = rand

    ts_part = _encode_base32(now_ms, 10)
    rand_part = _encode_base32(rand, 16)
    return ts_part + rand_part


# ---------------------------------------------------------------------------
# TimelineEntry — unified schema
# ---------------------------------------------------------------------------


# data_type 软约束：常见值列举，运行时不强校验
KNOWN_DATA_TYPES = frozenset({
    "message",       # 用户/channel 消息、PA 回复
    "thought",       # PA 思考/决策
    "task_state",    # task 状态变化
    "tool_call",     # 工具调用
    "tool_result",   # 工具结果
    "result",        # sub-agent 结果
    "os_event",      # 系统事件（sync/workspace/...）
    "action_result", # PA action 执行结果（resume/reply/run/schedule 的 ok/failed）
    "legacy",        # 迁移前的老数据或无法推断的 event
})


@dataclass
class TimelineEntry:
    """Unified timeline entry. See spec 20260418-timeline-entry-schema."""

    # Core identity
    id: str
    ts: str
    origin: str          # "external" | "internal"
    subkind: str         # external: channel name; internal: trigger type; "legacy" for old path

    # Thread organization (thread_id == id when this entry is its own root)
    thread_id: str
    parent_id: str | None = None

    # Semantic
    data_type: str = "legacy"
    task_id: str | None = None
    data: dict[str, Any] | None = None

    # Backward-compat legacy fields (kept so existing consumers keep working)
    msg_id: str | None = None
    role: str | None = None
    event: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize; drop keys with None values for compactness + backward compat.

        Empty dict for data is preserved if explicitly provided, but None is dropped.
        """
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


def _trace_file_for_today() -> Path:
    return TRACE_DIR / f"trace-{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _append_entry(entry: TimelineEntry) -> None:
    """Fire-and-forget append. Never raises."""
    try:
        path = _trace_file_for_today()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

    # Broadcast to WS subscribers (additive; errors swallowed)
    hook = _broadcast_hook
    if hook is not None:
        import contextlib
        with contextlib.suppress(Exception):
            hook(entry.to_dict())


def _infer_data_type(event: str | None) -> str:
    """Map legacy event string to new data_type. Soft mapping, returns 'legacy' when unsure."""
    if not event:
        return "legacy"

    # Known structured events (data.event_type in old schema)
    direct = {
        "pa_ingestion": "message",
        "pa_decision": "thought",
        "pa_agent_launched": "task_state",
        "pa_agent_exited": "task_state",
        "pa_reply": "message",
    }
    if event in direct:
        return direct[event]

    # Human-readable event strings (ingestion scheduler writes Chinese prefixes)
    if event.startswith("收到 "):
        return "message"
    if event.startswith("决策 ") or "决策" in event:
        return "thought"
    if "启动 agent" in event or "launched" in event:
        return "task_state"
    if "执行结束" in event or "exited" in event or "FAILED" in event:
        return "task_state"
    if "回复" in event or "reply" in event:
        return "message"
    if "通知 PA" in event:
        return "message"
    if "读取结果" in event:
        return "result"
    return "legacy"


def trace(
    msg_id: str,
    task_id: str | None,
    role: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Append one trace entry. Fire-and-forget — never raises.

    Legacy signature preserved for all existing callers. Internally populates
    the new timeline fields with defaults: origin='internal', subkind='legacy',
    thread_id=msg_id (or new ulid if msg_id empty), data_type inferred from event.
    """
    entry = TimelineEntry(
        id=ulid_new(),
        ts=datetime.now().isoformat(),
        origin="internal",
        subkind="legacy",
        thread_id=msg_id or ulid_new(),
        parent_id=None,
        data_type=_infer_data_type(event),
        task_id=task_id,
        data=data if data else None,
        msg_id=msg_id if msg_id else None,
        role=role if role else None,
        event=event if event else None,
    )
    _append_entry(entry)


def latest_entry_for_task(task_id: str, data_type: str | None = None) -> dict[str, Any] | None:
    """Scan recent trace files for the latest entry for a task.

    Used as the source-of-truth for task status reconstruction (spec
    20260418-timeline-event-coverage Phase 4). Looks back 7 days by default.
    """
    from datetime import timedelta
    today = datetime.now().date()
    latest: dict[str, Any] | None = None
    latest_ts = ""
    for days_ago in range(7):
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
                    except json.JSONDecodeError:
                        continue
                    if entry.get("task_id") != task_id:
                        continue
                    if data_type and entry.get("data_type") != data_type:
                        continue
                    ts = entry.get("ts", "")
                    if ts > latest_ts:
                        latest_ts = ts
                        latest = entry
        except OSError:
            continue
    return latest


def get_current_task_status(task_id: str) -> str | None:
    """Return the latest task_state entry's data.status for the task, or None.

    Spec 20260418-timeline-event-coverage Phase 4: timeline is the source of
    truth for task state; TaskStore.status is a cache.
    """
    entry = latest_entry_for_task(task_id, data_type="task_state")
    if not entry:
        return None
    data = entry.get("data") or {}
    status = data.get("status")
    return str(status) if status else None


def trace_entry(
    *,
    origin: str,
    subkind: str,
    data_type: str,
    thread_id: str | None = None,
    parent_id: str | None = None,
    task_id: str | None = None,
    data: dict[str, Any] | None = None,
    msg_id: str | None = None,
    role: str | None = None,
    event: str | None = None,
) -> TimelineEntry:
    """Rich append API. Explicitly specify all timeline fields.

    Returns the created TimelineEntry so callers can chain (use entry.id as
    parent_id for subsequent entries). Fire-and-forget for I/O errors.

    If thread_id is None, this entry becomes its own root (thread_id = id).
    """
    eid = ulid_new()
    entry = TimelineEntry(
        id=eid,
        ts=datetime.now().isoformat(),
        origin=origin,
        subkind=subkind,
        thread_id=thread_id or eid,
        parent_id=parent_id,
        data_type=data_type,
        task_id=task_id,
        data=data if data else None,
        msg_id=msg_id if msg_id else None,
        role=role if role else None,
        event=event if event else None,
    )
    _append_entry(entry)
    return entry


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
