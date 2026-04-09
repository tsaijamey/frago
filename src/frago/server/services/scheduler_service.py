"""Scheduler service — PA's alarm clock.

Provides periodic scheduled task delivery to the Primary Agent.
Schedules persist in ~/.frago/schedules.json.

Design: schedule is an alarm clock, not an executor.
When a schedule is due, it enqueues a scheduled_task message to PA.
PA decides whether/how to execute.
"""

import asyncio
import contextlib
import json
import logging
import threading
import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# How often the scheduler checks for due recipes (seconds)
TICK_INTERVAL = 5


def _now_utc() -> datetime:
    return datetime.now()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _parse_interval(spec: str) -> int:
    """Parse interval spec like '30s', '10m', '2h' into seconds."""
    spec = spec.strip().lower()
    if spec.endswith("s"):
        return int(spec[:-1])
    elif spec.endswith("m"):
        return int(spec[:-1]) * 60
    elif spec.endswith("h"):
        return int(spec[:-1]) * 3600
    else:
        return int(spec)


class SchedulerService:
    """Background service for scheduled task delivery to PA."""

    _instance: Optional["SchedulerService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._schedules: list[dict[str, Any]] = []
        self._schedules_path = Path.home() / ".frago" / "schedules.json"
        # PA enqueue function — set by app.py during startup
        self._pa_enqueue: Callable[[dict[str, Any]], Coroutine] | None = None
        # Track schedules with active (unresolved) tasks for overlap control
        self._active_schedule_ids: set = set()

    @classmethod
    def get_instance(cls) -> "SchedulerService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if self._schedules_path.exists():
            try:
                data = json.loads(self._schedules_path.read_text(encoding="utf-8"))
                self._schedules = [
                    self._migrate_schedule(s) for s in data.get("schedules", [])
                ]
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load schedules: {e}")
                self._schedules = []
        else:
            self._schedules = []

    def _save(self) -> None:
        self._schedules_path.parent.mkdir(parents=True, exist_ok=True)
        self._schedules_path.write_text(
            json.dumps({"schedules": self._schedules}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # --- PA integration ---

    def set_pa_enqueue(self, enqueue_fn: Callable[[dict[str, Any]], Coroutine]) -> None:
        """Register the PA message queue enqueue function.

        Called by app.py during startup (bidirectional wiring).
        """
        self._pa_enqueue = enqueue_fn

    def update_schedule_result(
        self, schedule_id: str, status: str, task_id: str | None = None
    ) -> None:
        """Update schedule execution result. Called by PA after decision."""
        self._load()
        for s in self._schedules:
            if s["id"] == schedule_id:
                s["last_status"] = status
                # Append to history
                history = s.setdefault("history", [])
                entry: dict[str, Any] = {
                    "triggered_at": s.get("last_run_at", _now_utc().isoformat()),
                    "status": status,
                    "msg_id": "",
                    "task_id": task_id,
                }
                history.append(entry)
                # Keep only the most recent 50 entries
                if len(history) > 50:
                    s["history"] = history[-50:]
                self._save()
                # Clear active flag for overlap control
                self._active_schedule_ids.discard(schedule_id)
                logger.info(
                    "[scheduler] Schedule %s result updated: %s (task=%s)",
                    schedule_id, status, task_id,
                )
                return
        logger.warning("[scheduler] update_schedule_result: schedule %s not found", schedule_id)

    @staticmethod
    def _migrate_schedule(s: dict[str, Any]) -> dict[str, Any]:
        """Migrate old schedule format to new format (backward compat)."""
        if "name" not in s:
            s["name"] = s.get("recipe_name", "unnamed")
        if "prompt" not in s:
            recipe = s.get("recipe_name", "")
            s["prompt"] = f"执行 recipe {recipe}" if recipe else ""
        if "recipe" not in s and "recipe_name" in s:
            s["recipe"] = s.get("recipe_name")
        if "cron" not in s:
            s["cron"] = None
        if "overlap" not in s:
            s["overlap"] = "skip"
        if "timeout" not in s:
            s["timeout"] = 300
        if "history" not in s:
            s["history"] = []
        return s

    # --- CRUD ---

    def add_schedule(
        self,
        recipe_name: str | None = None,
        interval_seconds: int | None = None,
        params: dict[str, Any] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        name: str | None = None,
        prompt: str | None = None,
        cron: str | None = None,
        overlap: str = "skip",
        timeout: int = 300,
    ) -> dict[str, Any]:
        self._load()
        schedule_name = name or recipe_name or "unnamed"
        schedule_prompt = prompt or (f"执行 recipe {recipe_name}" if recipe_name else "")
        schedule = {
            "id": f"sch_{uuid.uuid4().hex[:8]}",
            "name": schedule_name,
            "prompt": schedule_prompt,
            "recipe": recipe_name,
            "recipe_name": recipe_name,  # backward compat
            "params": params or {},
            "interval_seconds": interval_seconds,
            "cron": cron,
            "overlap": overlap,
            "timeout": timeout,
            "start_at": start_at,
            "end_at": end_at,
            "enabled": True,
            "created_at": _now_utc().isoformat(),
            "last_run_at": None,
            "last_status": None,
            "run_count": 0,
            "history": [],
        }
        self._schedules.append(schedule)
        self._save()
        return schedule

    def remove_schedule(self, schedule_id: str) -> bool:
        self._load()
        before = len(self._schedules)
        self._schedules = [s for s in self._schedules if s["id"] != schedule_id]
        if len(self._schedules) < before:
            self._save()
            return True
        return False

    def toggle_schedule(self, schedule_id: str) -> bool | None:
        self._load()
        for s in self._schedules:
            if s["id"] == schedule_id:
                s["enabled"] = not s["enabled"]
                self._save()
                return s["enabled"]
        return None

    def list_schedules(self) -> list[dict[str, Any]]:
        self._load()
        return self._schedules

    # --- Service lifecycle ---

    async def start(self) -> None:
        self._load()
        if self._task is not None and not self._task.done():
            logger.warning("Recipe scheduler already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        count = len(self._schedules)
        logger.info(f"Recipe scheduler started ({count} schedule{'s' if count != 1 else ''})")

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Recipe scheduler stopped")

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _is_due(self, schedule: dict[str, Any], now: datetime) -> bool:
        """Check if a schedule is due for triggering."""
        interval = schedule.get("interval_seconds")
        cron_expr = schedule.get("cron")
        last_run = _parse_dt(schedule.get("last_run_at"))

        if cron_expr:
            try:
                from croniter import croniter
                base = last_run or _parse_dt(schedule.get("created_at")) or now
                cron = croniter(cron_expr, base)
                next_run = cron.get_next(datetime)
                return now >= next_run
            except (ValueError, KeyError) as e:
                logger.warning("[scheduler] Invalid cron expression for %s: %s", schedule["id"], e)
                return False
        elif interval:
            due_at = last_run + timedelta(seconds=interval) if last_run else now
            return now >= due_at
        return False

    def _next_run_at(self, schedule: dict[str, Any]) -> datetime | None:
        """Calculate the next run time for a schedule."""
        interval = schedule.get("interval_seconds")
        cron_expr = schedule.get("cron")
        last_run = _parse_dt(schedule.get("last_run_at"))
        now = _now_utc()

        if cron_expr:
            try:
                from croniter import croniter
                base = last_run or _parse_dt(schedule.get("created_at")) or now
                cron = croniter(cron_expr, base)
                return cron.get_next(datetime)
            except (ValueError, KeyError):
                return None
        elif interval:
            if last_run:
                return last_run + timedelta(seconds=interval)
            return now
        return None

    async def _loop(self) -> None:
        await asyncio.sleep(5)  # initial delay
        while not self._stop_event.is_set():
            # Reload schedules each tick (CLI may have added new ones)
            self._load()
            now = _now_utc()
            for schedule in self._schedules:
                if not schedule.get("enabled", True):
                    continue
                start = _parse_dt(schedule.get("start_at"))
                end = _parse_dt(schedule.get("end_at"))
                if start and now < start:
                    continue
                if end and now > end:
                    # Auto-disable expired schedules
                    schedule["enabled"] = False
                    self._save()
                    logger.info("[scheduler] Schedule %s expired (end_at reached), disabled", schedule["id"])
                    continue
                if self._is_due(schedule, now):
                    await self._execute(schedule)
            # Wait for tick or stop
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=TICK_INTERVAL
                )
                break
            except TimeoutError:
                continue

    async def _execute(self, schedule: dict[str, Any]) -> None:
        """Enqueue a scheduled_task message to PA (instead of direct execution)."""
        schedule_id = schedule["id"]
        schedule_name = schedule.get("name", schedule.get("recipe_name", "unnamed"))
        prompt = schedule.get("prompt", "")
        recipe = schedule.get("recipe", schedule.get("recipe_name"))

        # Overlap check: skip if previous trigger is still active
        overlap = schedule.get("overlap", "skip")
        if overlap == "skip" and schedule_id in self._active_schedule_ids:
            logger.info(
                "[scheduler] Schedule %s: skipping due to active task (overlap=skip)",
                schedule_id,
            )
            return

        # Immediately update last_run_at to prevent re-triggering on next tick
        schedule["last_run_at"] = _now_utc().isoformat()
        schedule["run_count"] = schedule.get("run_count", 0) + 1
        self._save()

        if not self._pa_enqueue:
            logger.warning("[scheduler] No PA enqueue function — cannot deliver schedule %s", schedule_id)
            return

        msg_id = f"sch_msg_{uuid.uuid4().hex[:8]}"
        message: dict[str, Any] = {
            "type": "scheduled_task",
            "msg_id": msg_id,
            "channel": "schedule",
            "schedule_id": schedule_id,
            "schedule_name": schedule_name,
            "prompt": prompt,
            "recipe": recipe,
            "triggered_at": schedule["last_run_at"],
            "last_status": schedule.get("last_status"),
            "run_count": schedule.get("run_count", 0),
        }
        try:
            await self._pa_enqueue(message)
            self._active_schedule_ids.add(schedule_id)
            logger.info(
                "[scheduler] Message enqueued: type=scheduled_task, schedule=%s (%s)",
                schedule_id, schedule_name,
            )
        except Exception as e:
            logger.warning("[scheduler] Failed to enqueue schedule %s: %s", schedule_id, e)
