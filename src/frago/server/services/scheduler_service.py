"""Scheduler service — frago 的定时执行底座。

定时任务持久化在 ~/.frago/schedules.json，按性质分三种形态：

  kind=command   一条 shell 命令      → frago 自己执行
  kind=recipe    一个配方             → frago 自己执行
  kind=prompt    一句自然语言任务      → 交给 PA（这一种本来就需要理解和判断）

**前两种不经过 PA。** 2026-04 到 2026-08 之间它们是经过的，代价是：agent 会话起
不来时，任务只在日志里留一行警告然后无声地不发生。机械任务的执行不该绑在一个
agent 能不能启动上。

方向也随之反过来——PA 不再是定时任务的必经之路，而是它的两个身份之一：
执行 prompt 型任务的执行者，以及 ``frago schedule add`` 的调用方（agent 可以
给自己或给系统安排定时任务）。

执行完的通知回路见 schedule_executor 模块的模块文档。
"""

import asyncio
import contextlib
import json
import logging
import threading
import time
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
    """定时任务的调度与执行。机械任务自己跑，自然语言任务转给 PA。"""

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
        if "reply_channel" not in s:
            s["reply_channel"] = None
        if "reply_context" not in s:
            s["reply_context"] = {}
        # kind 是后加的。老记录按「有 recipe 就是配方型，否则是自然语言型」推断，
        # 推断结果落盘，之后不再重算——否则改了 recipe 字段会让形态跟着漂。
        if "kind" not in s:
            s["kind"] = "recipe" if s.get("recipe") or s.get("recipe_name") else "prompt"
        if "command" not in s:
            s["command"] = None
        if "cwd" not in s:
            s["cwd"] = None
        if "notify" not in s:
            # 老任务一律不通知：它们此前从没推送过，升级不该让人突然被刷屏。
            s["notify"] = {"on": "never", "to": None, "context": {}}
        for k, v in (
            ("last_success_at", None), ("last_digest", None),
            ("consecutive_failures", 0), ("staleness_notified_at", None),
        ):
            if k not in s:
                s[k] = v
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
        reply_channel: str | None = None,
        reply_context: dict[str, Any] | None = None,
        command: str | None = None,
        cwd: str | None = None,
        notify: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._load()
        if command:
            kind = "command"
        elif recipe_name:
            kind = "recipe"
        else:
            kind = "prompt"
        schedule_name = name or recipe_name or (command or "")[:40] or "unnamed"
        schedule_prompt = prompt or (f"执行 recipe {recipe_name}" if recipe_name else "")
        schedule = {
            "id": f"sch_{uuid.uuid4().hex[:8]}",
            "name": schedule_name,
            "kind": kind,
            "prompt": schedule_prompt,
            "recipe": recipe_name,
            "recipe_name": recipe_name,  # backward compat
            "command": command,
            "cwd": cwd,
            "notify": notify or {"on": "change", "to": None, "context": {}},
            "params": params or {},
            "interval_seconds": interval_seconds,
            "cron": cron,
            "overlap": overlap,
            "timeout": timeout,
            "start_at": start_at,
            "end_at": end_at,
            "reply_channel": reply_channel,
            "reply_context": reply_context or {},
            "enabled": True,
            "created_at": _now_utc().isoformat(),
            "last_run_at": None,
            "last_status": None,
            "last_success_at": None,
            "last_digest": None,
            "consecutive_failures": 0,
            "staleness_notified_at": None,
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

    def _period_seconds(self, schedule: dict[str, Any]) -> int | None:
        """这条任务多久跑一次。cron 型取相邻两次触发的间隔。"""
        interval = schedule.get("interval_seconds")
        if interval:
            return int(interval)
        cron_expr = schedule.get("cron")
        if not cron_expr:
            return None
        try:
            from croniter import croniter

            base = _now_utc()
            it = croniter(cron_expr, base)
            first = it.get_next(datetime)
            second = it.get_next(datetime)
            return int((second - first).total_seconds())
        except (ValueError, KeyError):
            return None

    async def _check_staleness(self) -> None:
        """该跑而没跑，本身就是要通报的事。

        定时任务最难发现的故障不是报错——报错至少有一行日志——而是它压根没触发：
        服务停过、机器睡过、任务被禁用了没人记得。这种情况下人以为它在跑，
        数据却停在几天前。所以这里主动喊一声，而且这条通知能发出去本身就证明
        调度器是活的，缩小了排查范围。
        """
        from frago.server.services import schedule_executor as ex

        now = _now_utc()
        for schedule in self._schedules:
            if not schedule.get("enabled", True):
                continue
            if (schedule.get("notify") or {}).get("on") in (None, "never"):
                continue
            if schedule.get("staleness_notified_at"):
                continue
            overdue = ex.is_stale(schedule, now, self._period_seconds(schedule))
            if overdue is None:
                continue
            result = ex.deliver(schedule, ex.staleness_text(schedule, overdue), self._pa_enqueue)
            if result.get("status") == "queued":
                await self._enqueue_notice(schedule, ex.staleness_text(schedule, overdue))
            schedule["staleness_notified_at"] = now.isoformat()
            self._save()
            logger.warning(
                "[scheduler] %s 已逾期 %s 未成功运行，已通知（%s）",
                schedule["id"], overdue, result.get("status"),
            )

    async def _loop(self) -> None:
        await asyncio.sleep(5)  # initial delay
        last_staleness_check = 0.0
        while not self._stop_event.is_set():
            # Reload schedules each tick (CLI may have added new ones)
            self._load()
            now = _now_utc()

            # 逾期巡检半小时一次就够——它盯的是「几个周期都没跑」这种慢故障
            if time.monotonic() - last_staleness_check > 1800:
                last_staleness_check = time.monotonic()
                with contextlib.suppress(Exception):
                    await self._check_staleness()
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
        """到期分流：命令和配方 frago 自己跑，自然语言任务交给 PA。"""
        schedule_id = schedule["id"]

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

        kind = schedule.get("kind") or ("recipe" if schedule.get("recipe") else "prompt")
        if kind in ("command", "recipe"):
            self._active_schedule_ids.add(schedule_id)
            try:
                await self._execute_native(schedule)
            finally:
                self._active_schedule_ids.discard(schedule_id)
            return

        await self._execute_via_pa(schedule)

    async def _execute_native(self, schedule: dict[str, Any]) -> None:
        """frago 自己执行，跑完按通知回路决定要不要说话。"""
        from frago.server.services import schedule_executor as ex

        schedule_id = schedule["id"]
        prev = {
            "last_digest": schedule.get("last_digest"),
            "consecutive_failures": schedule.get("consecutive_failures", 0),
        }

        try:
            outcome = await ex.run_scheduled(schedule)
        except Exception as e:  # noqa: BLE001 — 一个任务炸掉不该带走调度循环
            logger.exception("[scheduler] %s native execution crashed", schedule_id)
            outcome = ex.RunOutcome(ok=False, kind=schedule.get("kind", "?"), error=str(e))

        decision = ex.decide_notification(schedule, outcome, prev)
        notify_result: dict[str, Any] = {"status": "skipped", "reason": decision.reason}
        if decision.should:
            notify_result = ex.deliver(schedule, decision.text, self._pa_enqueue)
            if notify_result.get("status") == "queued":
                await self._enqueue_notice(schedule, decision.text)
                notify_result = {"status": "ok", "target": "pa"}

        # 状态写回：成功清零失败计数并推进指纹，失败只累加计数、指纹不动
        # （指纹代表「上一次成功的样子」，失败没有样子可言）。
        self._load()
        for s in self._schedules:
            if s["id"] != schedule_id:
                continue
            s["last_status"] = "success" if outcome.ok else "failed"
            if outcome.ok:
                s["last_success_at"] = _now_utc().isoformat()
                s["last_digest"] = outcome.digest
                s["consecutive_failures"] = 0
                s["staleness_notified_at"] = None
            else:
                s["consecutive_failures"] = int(s.get("consecutive_failures", 0)) + 1
            history = s.setdefault("history", [])
            history.append({
                "triggered_at": s.get("last_run_at", _now_utc().isoformat()),
                "status": s["last_status"],
                "kind": s.get("kind"),
                "exit_code": outcome.exit_code,
                "duration_ms": outcome.duration_ms,
                "error": outcome.error[:300] if outcome.error else "",
                "notified": decision.should,
                "notify_status": notify_result.get("status"),
                "notify_reason": decision.reason,
                "task_id": None,
            })
            if len(history) > 50:
                s["history"] = history[-50:]
            self._save()
            break

        logger.info(
            "[scheduler] %s (%s) → %s in %dms; notify=%s (%s)",
            schedule_id, schedule.get("kind"), "ok" if outcome.ok else "FAILED",
            outcome.duration_ms, notify_result.get("status"), decision.reason,
        )

    async def _enqueue_notice(self, schedule: dict[str, Any], text: str) -> None:
        """把一条通知投给 PA 读。agent 在这里是消费者，不是执行链路的一环。"""
        if not self._pa_enqueue:
            return
        await self._pa_enqueue({
            "type": "message",
            "msg_id": f"schnotice_{uuid.uuid4().hex[:8]}",
            "channel": schedule.get("reply_channel") or "schedule",
            "prompt": text,
            "reply_context": schedule.get("reply_context", {}),
        })

    async def _execute_via_pa(self, schedule: dict[str, Any]) -> None:
        """自然语言任务：仍然交给 PA，它需要的是理解而不是执行。"""
        schedule_id = schedule["id"]
        schedule_name = schedule.get("name", schedule.get("recipe_name", "unnamed"))
        prompt = schedule.get("prompt", "")
        recipe = schedule.get("recipe", schedule.get("recipe_name"))
        params = schedule.get("params", {}) or {}

        # Phase 3 (去账本): 不再 Ingestor.ingest_scheduled 写 board——scheduled 消息
        # 直接走下面的 PA enqueue 路径（带 reply_context），由常驻会话消费。
        if not self._pa_enqueue:
            logger.warning("[scheduler] No PA enqueue function — cannot deliver schedule %s", schedule_id)
            return

        msg_id = f"sch_msg_{uuid.uuid4().hex[:8]}"
        # Use reply_channel as the message channel so downstream task creation
        # and reply routing use the correct channel (e.g. "feishu") instead of "schedule".
        effective_channel = schedule.get("reply_channel") or "schedule"
        message: dict[str, Any] = {
            "type": "scheduled_task",
            "msg_id": msg_id,
            "channel": effective_channel,
            "schedule_id": schedule_id,
            "schedule_name": schedule_name,
            "prompt": prompt,
            "recipe": recipe,
            "params": params,
            "reply_context": schedule.get("reply_context", {}),
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
