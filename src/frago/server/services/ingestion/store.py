"""Persistent task store backed by a JSON file."""

import contextlib
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import IngestedTask, TaskStatus

logger = logging.getLogger(__name__)

STORE_FILE = Path.home() / ".frago" / "ingested_tasks.json"
ARCHIVE_DIR = Path.home() / ".frago" / "ingested_tasks"

_TERMINAL_STATUSES = {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value}


def _migrate_to_list(data: dict[str, Any], list_key: str, legacy_key: str) -> list[str]:
    """Backward compat: if old str field exists, wrap as [str]."""
    val = data.get(list_key)
    if isinstance(val, list):
        return val
    legacy = data.get(legacy_key)
    if isinstance(legacy, str):
        return [legacy]
    return []


class TaskStore:
    """Thread-safe, file-backed store for ingested tasks.

    Singleton per store_path — all callers share the same in-memory state.

    Responsibilities:
    1. Track the lifecycle state of every ingested task
    2. De-duplicate by (channel, channel_message_id)
    3. Persist to disk so tasks survive server restarts
    """

    _instances: dict[Path, "TaskStore"] = {}
    _path: Path
    _lock: threading.Lock
    _tasks: dict[str, dict[str, Any]]

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
            target = self._find(task_id)
            if target is not None:
                target["status"] = status.value
                if session_id is not None:
                    target["session_id"] = session_id
                if result_summary is not None:
                    target["result_summary"] = result_summary
                if error is not None:
                    target["error"] = error
                if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    target["completed_at"] = datetime.now().isoformat()
                self._save()
                return
            logger.warning("Task not found for status update: %s", task_id)

    def update_retry_count(self, task_id: str, count: int) -> None:
        with self._lock:
            for data in self._tasks.values():
                if data["id"] == task_id or (len(task_id) >= 8 and data["id"].startswith(task_id)):
                    data["retry_count"] = count
                    self._save()
                    return

    def increment_recovery_count(self, task_id: str) -> int:
        """Increment recovery_count and return the new value."""
        with self._lock:
            for data in self._tasks.values():
                if data["id"] == task_id or (len(task_id) >= 8 and data["id"].startswith(task_id)):
                    count: int = data.get("recovery_count", 0) + 1
                    data["recovery_count"] = count
                    self._save()
                    return count
        return 0

    def get_by_status(self, status: TaskStatus) -> list[IngestedTask]:
        with self._lock:
            return [
                self._deserialize(d)
                for d in self._tasks.values()
                if d["status"] == status.value
            ]

    def get(self, task_id: str) -> IngestedTask | None:
        with self._lock:
            data = self._find(task_id)
            return self._deserialize(data) if data else None

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

    def get_first_queued(self) -> IngestedTask | None:
        """执行器取下一个待执行任务（按 created_at 排序）。"""
        with self._lock:
            queued = [
                d for d in self._tasks.values()
                if d["status"] == TaskStatus.QUEUED.value
            ]
            if not queued:
                return None
            queued.sort(key=lambda d: d.get("created_at", ""))
            return self._deserialize(queued[0])

    def get_executing(self) -> IngestedTask | None:
        """获取当前正在执行的任务（最多 1 个）。"""
        with self._lock:
            for data in self._tasks.values():
                if data["status"] == TaskStatus.EXECUTING.value:
                    return self._deserialize(data)
            return None

    def get_recent_completed(self, limit: int = 5) -> list[IngestedTask]:
        """PA 环境 prompt 用——最近完成/失败的任务。"""
        with self._lock:
            terminal = [
                d for d in self._tasks.values()
                if d["status"] in _TERMINAL_STATUSES
            ]
            terminal.sort(key=lambda d: d.get("completed_at") or d.get("created_at", ""), reverse=True)
            return [self._deserialize(d) for d in terminal[:limit]]

    def update_run_info(
        self,
        task_id: str,
        *,
        run_description: str | None = None,
        run_prompt: str | None = None,
        session_id: str | None = None,
        claude_session_id: str | None = None,
        pid: int | None = None,
    ) -> None:
        """PA 决策或执行器回填运行时信息。"""
        with self._lock:
            target = self._find(task_id)
            if target is None:
                logger.warning("Task not found for run_info update: %s", task_id)
                return
            if run_description is not None:
                target.setdefault("run_descriptions", []).append(run_description)
            if run_prompt is not None:
                target.setdefault("run_prompts", []).append(run_prompt)
            if session_id is not None:
                target["session_id"] = session_id
            if claude_session_id is not None:
                target["claude_session_id"] = claude_session_id
            if pid is not None:
                target["pid"] = pid
            self._save()

    # -- rotation --

    def rotate(self) -> int:
        """Archive terminal tasks to date-named files, return count archived.

        Safe to call at any time — only moves COMPLETED/FAILED tasks.
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
        today = datetime.now().date().isoformat()
        with self._lock:
            return any(
                d["status"] in _TERMINAL_STATUSES
                and (d.get("completed_at") or d["created_at"])[:10] < today
                for d in self._tasks.values()
            )

    # -- internal lookup (must hold _lock) --

    def _find(self, task_id: str) -> dict[str, Any] | None:
        """Find task data dict by exact or prefix match. Caller must hold _lock."""
        for data in self._tasks.values():
            if data["id"] == task_id:
                return data
        if len(task_id) >= 8:
            for data in self._tasks.values():
                if data["id"].startswith(task_id):
                    return data
        return None

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
            "reply_context": task.reply_context,
            "run_descriptions": task.run_descriptions,
            "run_prompts": task.run_prompts,
            "session_id": task.session_id,
            "pid": task.pid,
            "result_summary": task.result_summary,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "error": task.error,
            "retry_count": task.retry_count,
            "recovery_count": task.recovery_count,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> IngestedTask:
        # Handle legacy TIMEOUT status → FAILED
        status_val = data.get("status", "pending")
        if status_val == "timeout":
            status_val = "failed"
        return IngestedTask(
            id=data["id"],
            channel=data["channel"],
            channel_message_id=data["channel_message_id"],
            prompt=data["prompt"],
            status=TaskStatus(status_val),
            created_at=datetime.fromisoformat(data["created_at"]),
            reply_context=data.get("reply_context", {}),
            run_descriptions=_migrate_to_list(data, "run_descriptions", "run_description"),
            run_prompts=_migrate_to_list(data, "run_prompts", "run_prompt"),
            session_id=data.get("session_id"),
            pid=data.get("pid"),
            result_summary=data.get("result_summary"),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            error=data.get("error"),
            retry_count=data.get("retry_count", 0),
            recovery_count=data.get("recovery_count", 0),
        )
