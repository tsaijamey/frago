"""Persistent message journal — append-only JSONL + ack mechanism.

Replaces the in-memory asyncio.Queue for PA message delivery.
Messages survive server restarts and PA session rotations.

Storage: ~/.frago/message_journal.jsonl
Format: one JSON object per line, each with msg_id, type, task_id, payload, acked.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

JOURNAL_FILE = Path.home() / ".frago" / "message_journal.jsonl"


class MessageJournal:
    """Persistent message log with append + ack semantics."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or JOURNAL_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, msg_type: str, task_id: str | None, payload: dict) -> str:
        """Append a message to the journal. Returns msg_id."""
        msg_id = str(uuid.uuid4())
        entry = {
            "msg_id": msg_id,
            "type": msg_type,
            "task_id": task_id,
            "payload": payload,
            "created_at": datetime.now().isoformat(),
            "acked": False,
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as e:
            logger.error("Failed to append to message journal: %s", e)
        return msg_id

    def ack(self, task_id: str) -> int:
        """Mark all messages for a task_id as acked. Returns count acked."""
        return self._update_acked(task_id=task_id)

    def ack_by_msg_id(self, msg_id: str) -> bool:
        """Mark a specific message as acked by msg_id."""
        return self._update_acked(msg_id=msg_id) > 0

    def get_unacked(self) -> list[dict]:
        """Return all unacked messages, ordered by created_at."""
        entries = self._read_all()
        unacked = [e for e in entries if not e.get("acked", False)]
        unacked.sort(key=lambda e: e.get("created_at", ""))
        return unacked

    def compact(self, keep_days: int = 7) -> int:
        """Remove acked entries older than keep_days. Returns count removed."""
        entries = self._read_all()
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()

        kept: list[dict] = []
        removed = 0
        for entry in entries:
            if entry.get("acked") and entry.get("created_at", "") < cutoff:
                removed += 1
            else:
                kept.append(entry)

        if removed > 0:
            self._write_all(kept)
            logger.info("Journal compacted: removed %d acked entries", removed)
        return removed

    # -- internals --

    def _read_all(self) -> list[dict]:
        """Read all entries from journal, skipping corrupted lines."""
        if not self._path.exists():
            return []
        entries: list[dict] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Journal line %d corrupted, skipping", line_num)
        except OSError as e:
            logger.error("Failed to read message journal: %s", e)
        return entries

    def _write_all(self, entries: list[dict]) -> None:
        """Rewrite entire journal (used by compact and ack)."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as e:
            logger.error("Failed to write message journal: %s", e)

    def _update_acked(
        self,
        *,
        task_id: str | None = None,
        msg_id: str | None = None,
    ) -> int:
        """Mark entries as acked by task_id or msg_id. Returns count updated."""
        entries = self._read_all()
        count = 0
        for entry in entries:
            if entry.get("acked"):
                continue
            if (task_id and entry.get("task_id") == task_id) or \
               (msg_id and entry.get("msg_id") == msg_id):
                entry["acked"] = True
                count += 1
        if count > 0:
            self._write_all(entries)
        return count
