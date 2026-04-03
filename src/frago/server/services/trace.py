"""Pipeline trace logger.

Writes one JSONL entry per pipeline hop: role + event + timestamp.
Daily file rotation with automatic cleanup of old files.

File location: ~/.frago/traces/trace-YYYY-MM-DD.jsonl
"""

import json
import logging
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
) -> list[dict]:
    """Load trace entries that have data (timeline-worthy events).

    Returns entries in pa_events-compatible format for timeline_service consumption:
    [{"timestamp": ..., "event_type": ..., "data": {...}}, ...]
    """
    entries: list[dict] = []
    today = datetime.now().date()

    for days_ago in range(lookback_days):
        date = today - timedelta(days=days_ago)
        path = TRACE_DIR / f"trace-{date.strftime('%Y-%m-%d')}.jsonl"
        if not path.exists():
            continue
        day_entries: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if not entry.get("data"):
                            continue
                        if since:
                            ts = datetime.fromisoformat(entry["ts"])
                            if ts < since:
                                continue
                        raw_data = entry["data"]
                        event_type = raw_data.pop("event_type", "")
                        day_entries.append({
                            "timestamp": entry["ts"],
                            "event_type": event_type,
                            "data": raw_data,
                        })
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        except Exception:
            continue
        entries = day_entries + entries
        if len(entries) >= limit:
            break

    return entries[-limit:]
