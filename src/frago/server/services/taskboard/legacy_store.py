"""Legacy persistent task store backed by a JSON file.

Phase 4 (Yi #133 + HUMAN #152 + Orchestrator #158): 从
``frago.server.services.ingestion.store`` 迁入 taskboard 层. Source-of-truth
现在是 board.timeline.jsonl; this store remains as an execution-context
sidecar holding fields not yet on board (channel / reply_context /
sub_tasks). Future phases may collapse it into board.Task entirely.

External imports should use ``from frago.server.services.taskboard.legacy_store
import TaskStore``. ingestion/store.py 已物理删除.
"""

import contextlib
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.taskboard.models import IngestedTask, SubTask, TaskStatus

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


def _migrate_sub_tasks(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Backward compat: build sub_tasks from legacy flat fields.

    Old format had run_descriptions/run_prompts as parallel arrays + scalar
    session_id/claude_session_id/pid/result_summary/error/completed_at.
    New format: sub_tasks list where each element is a self-contained run record.
    """
    existing = data.get("sub_tasks")
    if isinstance(existing, list):
        return existing

    # Reconstruct from legacy parallel arrays
    descriptions = _migrate_to_list(data, "run_descriptions", "run_description")
    prompts = _migrate_to_list(data, "run_prompts", "run_prompt")

    if not descriptions and not prompts:
        return []

    count = max(len(descriptions), len(prompts))
    subs: list[dict[str, Any]] = []
    for i in range(count):
        sub: dict[str, Any] = {
            "description": descriptions[i] if i < len(descriptions) else "",
            "prompt": prompts[i] if i < len(prompts) else "",
            "status": "pending",
            "created_at": data.get("created_at", datetime.now().isoformat()),
        }
        subs.append(sub)

    # Backfill scalar fields into the LAST sub_task (only record we have)
    if subs:
        last = subs[-1]
        for key in ("session_id", "claude_session_id", "pid",
                     "result_summary", "error", "completed_at"):
            val = data.get(key)
            if val is not None:
                last[key] = val
        # Infer sub_task status from task-level status
        status_val = data.get("status", "pending")
        if status_val in ("completed", "failed"):
            last["status"] = status_val
        elif status_val == "executing":
            last["status"] = "executing"
        else:
            last["status"] = "queued"

    return subs


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
        prev_status_value: str | None = None
        thread_id: str | None = None
        channel_msg_id: str | None = None
        with self._lock:
            target = self._find(task_id)
            if target is not None:
                prev_status_value = target.get("status")
                thread_id = target.get("thread_id")
                channel_msg_id = target.get("channel_message_id")
                target["status"] = status.value
                # Write run-level fields into current sub_task
                subs = target.get("sub_tasks", [])
                if subs:
                    cur = subs[-1]
                    if session_id is not None:
                        cur["session_id"] = session_id
                    if result_summary is not None:
                        cur["result_summary"] = result_summary
                    if error is not None:
                        cur["error"] = error
                    if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                        cur["completed_at"] = datetime.now().isoformat()
                        cur["status"] = status.value
                self._save()
            else:
                logger.warning("Task not found for status update: %s", task_id)
                return

        # Emit task_state timeline entry (spec 20260418-timeline-event-coverage Phase 4)
        if prev_status_value != status.value:
            try:
                from frago.server.services.trace import trace_entry

                data = {"status": status.value, "prev_status": prev_status_value}
                if error is not None:
                    data["error"] = error
                if session_id is not None:
                    data["run_id"] = session_id
                if result_summary is not None:
                    data["result_summary"] = result_summary[:200]
                trace_entry(
                    origin="internal",
                    subkind="task_store",
                    data_type="task_state",
                    thread_id=thread_id,
                    parent_id=None,
                    task_id=task_id,
                    data=data,
                    msg_id=channel_msg_id,
                )
            except Exception:
                logger.debug("failed to emit task_state entry", exc_info=True)

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

    def get_status(self, task_id: str) -> str | None:
        """Preferred API for reading a task's current status.

        Spec 20260418-timeline-consumer-unification Phase 5: timeline is the
        source of truth; this method transparently prefers the latest task_state
        entry in the timeline, falling back to the cached field in TaskStore
        only if the timeline has no entry yet for the task.
        """
        from frago.server.services.trace import get_current_task_status
        timeline_status = get_current_task_status(task_id)
        if timeline_status:
            return timeline_status
        # Fallback: cache (task created but no state transition emitted yet)
        with self._lock:
            data = self._find(task_id)
            return data.get("status") if data else None

    def rebuild_status_cache(self) -> int:
        """Reconcile TaskStore.status with timeline's task_state entries.

        Spec 20260418-timeline-event-coverage Phase 4: timeline is source of
        truth; this re-hydrates the cache on startup or periodically.
        Returns number of statuses corrected.
        """
        from frago.server.services.trace import get_current_task_status

        corrected = 0
        with self._lock:
            for data in self._tasks.values():
                task_id = data.get("id")
                if not task_id:
                    continue
                timeline_status = get_current_task_status(task_id)
                if timeline_status and timeline_status != data.get("status"):
                    logger.info(
                        "TaskStore rebuild: task %s cache=%s → timeline=%s",
                        task_id[:8], data.get("status"), timeline_status,
                    )
                    data["status"] = timeline_status
                    corrected += 1
            if corrected:
                self._save()
        return corrected

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
        """PA 决策或执行器回填运行时信息。

        run_description + run_prompt: append 新 SubTask（PA 决策路径）
        session_id / claude_session_id / pid: 回填到当前 sub_task（执行器路径）
        """
        with self._lock:
            target = self._find(task_id)
            if target is None:
                logger.warning("Task not found for run_info update: %s", task_id)
                return
            subs = target.setdefault("sub_tasks", [])
            # PA 决策路径：description + prompt → append 新 sub_task
            if run_description is not None or run_prompt is not None:
                subs.append({
                    "description": run_description or "",
                    "prompt": run_prompt or "",
                    "status": "queued",
                    "created_at": datetime.now().isoformat(),
                })
            # 执行器回填路径：写入当前（最后一个）sub_task
            if subs and (session_id is not None or claude_session_id is not None or pid is not None):
                cur = subs[-1]
                if session_id is not None:
                    cur["session_id"] = session_id
                if claude_session_id is not None:
                    cur["claude_session_id"] = claude_session_id
                if pid is not None:
                    cur["pid"] = pid
            self._save()

    # -- rotation --

    def rotate(self, *, exclude_failed: bool = False) -> int:
        """Archive terminal tasks to date-named files, return count archived.

        Safe to call at any time — only moves COMPLETED/FAILED tasks.
        PENDING/EXECUTING tasks stay in the main file untouched.

        Args:
            exclude_failed: If True, only archive COMPLETED tasks (keep FAILED
                in active store for PA visibility). Used by heartbeat cleanup.
        """
        archivable = {TaskStatus.COMPLETED.value} if exclude_failed else _TERMINAL_STATUSES
        with self._lock:
            active: dict[str, dict[str, Any]] = {}
            to_archive: dict[str, dict[str, dict[str, Any]]] = {}

            for key, data in self._tasks.items():
                if data["status"] in archivable:
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
    def _serialize_sub_task(sub: SubTask) -> dict[str, Any]:
        return {
            "description": sub.description,
            "prompt": sub.prompt,
            "session_id": sub.session_id,
            "claude_session_id": sub.claude_session_id,
            "pid": sub.pid,
            "result_summary": sub.result_summary,
            "error": sub.error,
            "status": sub.status,
            "created_at": sub.created_at.isoformat() if isinstance(sub.created_at, datetime) else sub.created_at,
            "completed_at": sub.completed_at.isoformat() if isinstance(sub.completed_at, datetime) else sub.completed_at,
        }

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
            "thread_id": task.thread_id,
            "sub_tasks": [TaskStore._serialize_sub_task(s) for s in task.sub_tasks],
            "retry_count": task.retry_count,
            "recovery_count": task.recovery_count,
        }

    @staticmethod
    def _deserialize_sub_task(d: dict[str, Any]) -> SubTask:
        created = d.get("created_at")
        completed = d.get("completed_at")
        return SubTask(
            description=d.get("description", ""),
            prompt=d.get("prompt", ""),
            session_id=d.get("session_id"),
            claude_session_id=d.get("claude_session_id"),
            pid=d.get("pid"),
            result_summary=d.get("result_summary"),
            error=d.get("error"),
            status=d.get("status", "pending"),
            created_at=datetime.fromisoformat(created) if isinstance(created, str) else (created or datetime.now()),
            completed_at=datetime.fromisoformat(completed) if isinstance(completed, str) else completed,
        )

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> IngestedTask:
        # Handle legacy TIMEOUT status → FAILED
        status_val = data.get("status", "pending")
        if status_val == "timeout":
            status_val = "failed"
        # Migrate legacy flat fields → sub_tasks
        raw_subs = _migrate_sub_tasks(data)
        sub_tasks = [TaskStore._deserialize_sub_task(s) for s in raw_subs]
        return IngestedTask(
            id=data["id"],
            channel=data["channel"],
            channel_message_id=data["channel_message_id"],
            prompt=data["prompt"],
            status=TaskStatus(status_val),
            created_at=datetime.fromisoformat(data["created_at"]),
            reply_context=data.get("reply_context", {}),
            thread_id=data.get("thread_id"),
            sub_tasks=sub_tasks,
            retry_count=data.get("retry_count", 0),
            recovery_count=data.get("recovery_count", 0),
        )
