"""Persistent task store backed by a JSON file."""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import IngestedTask, TaskStatus

logger = logging.getLogger(__name__)

STORE_FILE = Path.home() / ".frago" / "ingested_tasks.json"


class TaskStore:
    """Thread-safe, file-backed store for ingested tasks.

    Responsibilities:
    1. Track the lifecycle state of every ingested task
    2. De-duplicate by (channel, channel_message_id)
    3. Persist to disk so tasks survive server restarts
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or STORE_FILE
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = self._load()

    # -- public API --

    def exists(self, channel: str, channel_message_id: str) -> bool:
        key = f"{channel}:{channel_message_id}"
        with self._lock:
            return key in self._tasks

    def add(self, task: IngestedTask) -> None:
        key = f"{task.channel}:{task.channel_message_id}"
        with self._lock:
            self._tasks[key] = self._serialize(task)
            self._save()

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        session_id: str | None = None,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            for data in self._tasks.values():
                if data["id"] == task_id:
                    data["status"] = status.value
                    if session_id is not None:
                        data["session_id"] = session_id
                    if result_summary is not None:
                        data["result_summary"] = result_summary
                    if error is not None:
                        data["error"] = error
                    if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                        data["completed_at"] = datetime.now(timezone.utc).isoformat()
                    self._save()
                    return
            logger.warning("Task not found for status update: %s", task_id)

    def get_by_status(self, status: TaskStatus) -> list[IngestedTask]:
        with self._lock:
            return [
                self._deserialize(d)
                for d in self._tasks.values()
                if d["status"] == status.value
            ]

    def get(self, task_id: str) -> IngestedTask | None:
        with self._lock:
            for data in self._tasks.values():
                if data["id"] == task_id:
                    return self._deserialize(data)
            return None

    def get_recent(
        self, *, channel: str | None = None, limit: int = 5
    ) -> list[IngestedTask]:
        """Return the most recent tasks, optionally filtered by channel."""
        with self._lock:
            items = list(self._tasks.values())
            if channel:
                items = [d for d in items if d["channel"] == channel]
            items.sort(key=lambda d: d.get("created_at", ""), reverse=True)
            return [self._deserialize(d) for d in items[:limit]]

    # -- persistence --

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load task store %s: %s", self._path, e)
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._tasks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to save task store: %s", e)

    # -- serialization --

    @staticmethod
    def _serialize(task: IngestedTask) -> dict[str, Any]:
        return {
            "id": task.id,
            "channel": task.channel,
            "channel_message_id": task.channel_message_id,
            "prompt": task.prompt,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "session_id": task.session_id,
            "result_summary": task.result_summary,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error": task.error,
            "reply_context": task.reply_context,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> IngestedTask:
        return IngestedTask(
            id=data["id"],
            channel=data["channel"],
            channel_message_id=data["channel_message_id"],
            prompt=data["prompt"],
            status=TaskStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            session_id=data.get("session_id"),
            result_summary=data.get("result_summary"),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            error=data.get("error"),
            reply_context=data.get("reply_context", {}),
        )
