"""Persistent task store backed by a JSON file."""

import contextlib
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import IngestedTask, TaskStatus

logger = logging.getLogger(__name__)

STORE_FILE = Path.home() / ".frago" / "ingested_tasks.json"
ARCHIVE_DIR = Path.home() / ".frago" / "ingested_tasks"

_TERMINAL_STATUSES = {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.TIMEOUT.value}


class TaskStore:
    """Thread-safe, file-backed store for ingested tasks.

    Singleton per store_path — all callers share the same in-memory state.

    Responsibilities:
    1. Track the lifecycle state of every ingested task
    2. De-duplicate by (channel, channel_message_id)
    3. Persist to disk so tasks survive server restarts
    """

    _instances: dict[Path, "TaskStore"] = {}

    def __new__(cls, store_path: Path | None = None) -> "TaskStore":
        path = store_path or STORE_FILE
        if path not in cls._instances:
            instance = super().__new__(cls)
            instance._path = path
            instance._lock = threading.Lock()
            instance._tasks = instance._load()
            cls._instances[path] = instance
        return cls._instances[path]

    def __init__(self, store_path: Path | None = None) -> None:
        # Already initialized in __new__
        pass

    # -- public API --

    def exists(self, channel: str, channel_message_id: str) -> bool:
        key = f"{channel}:{channel_message_id}"
        with self._lock:
            if key in self._tasks:
                return True
            # Check archived files — completed tasks still count as "seen"
            if ARCHIVE_DIR.is_dir():
                for archive_path in ARCHIVE_DIR.glob("*.json"):
                    try:
                        archived = json.loads(archive_path.read_text(encoding="utf-8"))
                        if key in archived:
                            return True
                    except (json.JSONDecodeError, OSError):
                        continue
            return False

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
            target = None
            # Exact match first
            for data in self._tasks.values():
                if data["id"] == task_id:
                    target = data
                    break
            # Prefix match (PA may truncate task_id to 8 chars)
            if target is None and len(task_id) >= 8:
                for data in self._tasks.values():
                    if data["id"].startswith(task_id):
                        target = data
                        break
            if target is not None:
                target["status"] = status.value
                if session_id is not None:
                    target["session_id"] = session_id
                if result_summary is not None:
                    target["result_summary"] = result_summary
                if error is not None:
                    target["error"] = error
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
                    target["completed_at"] = datetime.now(UTC).isoformat()
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
            # Exact match first
            for data in self._tasks.values():
                if data["id"] == task_id:
                    return self._deserialize(data)
            # Prefix match (PA may truncate task_id to 8 chars)
            if len(task_id) >= 8:
                for data in self._tasks.values():
                    if data["id"].startswith(task_id):
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

    def has_pending(self) -> bool:
        """Check if there are any PENDING tasks."""
        with self._lock:
            return any(d["status"] == TaskStatus.PENDING.value for d in self._tasks.values())

    # -- rotation --

    def rotate(self) -> int:
        """Archive terminal tasks to date-named files, return count archived.

        Safe to call at any time — only moves COMPLETED/FAILED/TIMEOUT tasks.
        PENDING/EXECUTING tasks stay in the main file untouched.
        """
        with self._lock:
            active: dict[str, dict[str, Any]] = {}
            to_archive: dict[str, dict[str, dict[str, Any]]] = {}

            for key, data in self._tasks.items():
                if data["status"] in _TERMINAL_STATUSES:
                    date_str = (data.get("completed_at") or data["created_at"])[:10]
                    to_archive.setdefault(date_str, {})[key] = data
                else:
                    active[key] = data

            if not to_archive:
                return 0

            ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            for date_str, tasks in to_archive.items():
                archive_path = ARCHIVE_DIR / f"{date_str}.json"
                existing: dict[str, Any] = {}
                if archive_path.exists():
                    with contextlib.suppress(json.JSONDecodeError, OSError):
                        existing = json.loads(archive_path.read_text(encoding="utf-8"))
                existing.update(tasks)
                try:
                    archive_path.write_text(
                        json.dumps(existing, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError as e:
                    logger.error("Failed to write archive %s: %s", archive_path, e)
                    return 0

            archived_count = sum(len(t) for t in to_archive.values())
            self._tasks = active
            self._save()
            logger.info("Rotated %d task(s) to archive", archived_count)
            return archived_count

    def needs_rotation(self) -> bool:
        """Check if there are terminal tasks with completed_at before today."""
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            return any(
                d["status"] in _TERMINAL_STATUSES
                and (d.get("completed_at") or d["created_at"])[:10] < today
                for d in self._tasks.values()
            )

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
