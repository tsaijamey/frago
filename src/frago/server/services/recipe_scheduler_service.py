"""Recipe scheduler service.

Provides periodic background execution of recipes at configurable intervals.
Schedules persist in ~/.frago/schedules.json.
"""

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How often the scheduler checks for due recipes (seconds)
TICK_INTERVAL = 5


def _now_utc() -> datetime:
    return datetime.now()


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
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


class RecipeSchedulerService:
    """Background service for scheduled recipe execution."""

    _instance: Optional["RecipeSchedulerService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._schedules: List[Dict[str, Any]] = []
        self._schedules_path = Path.home() / ".frago" / "schedules.json"

    @classmethod
    def get_instance(cls) -> "RecipeSchedulerService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if self._schedules_path.exists():
            try:
                data = json.loads(self._schedules_path.read_text(encoding="utf-8"))
                self._schedules = data.get("schedules", [])
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

    # --- CRUD ---

    def add_schedule(
        self,
        recipe_name: str,
        interval_seconds: int,
        params: Optional[Dict[str, Any]] = None,
        start_at: Optional[str] = None,
        end_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._load()
        schedule = {
            "id": f"sch_{uuid.uuid4().hex[:8]}",
            "recipe_name": recipe_name,
            "params": params or {},
            "interval_seconds": interval_seconds,
            "start_at": start_at,
            "end_at": end_at,
            "enabled": True,
            "created_at": _now_utc().isoformat(),
            "last_run_at": None,
            "last_status": None,
            "run_count": 0,
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

    def toggle_schedule(self, schedule_id: str) -> Optional[bool]:
        self._load()
        for s in self._schedules:
            if s["id"] == schedule_id:
                s["enabled"] = not s["enabled"]
                self._save()
                return s["enabled"]
        return None

    def list_schedules(self) -> List[Dict[str, Any]]:
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
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Recipe scheduler stopped")

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

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
                    continue
                interval = schedule.get("interval_seconds", 600)
                last_run = _parse_dt(schedule.get("last_run_at"))
                if last_run:
                    due_at = last_run + timedelta(seconds=interval)
                else:
                    due_at = now  # first run: immediately
                if now >= due_at:
                    await self._execute(schedule)
            # Wait for tick or stop
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=TICK_INTERVAL
                )
                break
            except asyncio.TimeoutError:
                continue

    async def _execute(self, schedule: Dict[str, Any]) -> None:
        name = schedule["recipe_name"]
        params = schedule.get("params", {})
        logger.info(f"[scheduler] Running recipe: {name} (schedule: {schedule['id']})")
        try:
            from frago.server.services.recipe_service import RecipeService

            result = await asyncio.to_thread(
                RecipeService.run_recipe, name, params, 300
            )
            status = "success" if result.get("status") != "error" else "failed"
        except Exception as e:
            logger.warning(f"[scheduler] Recipe {name} failed: {e}")
            status = "failed"
        schedule["last_run_at"] = _now_utc().isoformat()
        schedule["last_status"] = status
        schedule["run_count"] = schedule.get("run_count", 0) + 1
        self._save()
        logger.info(f"[scheduler] Recipe {name} finished: {status}")
