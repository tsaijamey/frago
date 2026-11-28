"""Server-side autonomous periodic patrol service for workbench queues.

Eliminates coupling between callback delivery and user-initiated WebUI actions
(such as opening a session view or refreshing the session list). Periodically sweeps
all active queues across all agent families (agy, codex, claude, opencode, coreagent)
and automatically injects ready items into idle sessions.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time

from frago.server.services import workbench_queue

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_PATROL_INTERVAL_S: float = 2.0
DEFAULT_CALLBACK_RECOVERY_INTERVAL_S: float = 15.0


class WorkbenchQueuePatrolService:
    """Service that autonomously runs periodic workbench queue patrol within the server lifespan."""

    _instance: WorkbenchQueuePatrolService | None = None
    _lock = threading.Lock()

    def __init__(self, interval_seconds: float | None = None) -> None:
        env_interval = os.environ.get("FRAGO_QUEUE_PATROL_INTERVAL_S")
        if interval_seconds is not None:
            self.interval_seconds = max(0.05, float(interval_seconds))
        elif env_interval:
            try:
                self.interval_seconds = max(0.05, float(env_interval))
            except ValueError:
                self.interval_seconds = DEFAULT_QUEUE_PATROL_INTERVAL_S
        else:
            self.interval_seconds = DEFAULT_QUEUE_PATROL_INTERVAL_S

        env_recovery = os.environ.get("FRAGO_CALLBACK_RECOVERY_INTERVAL_S")
        if env_recovery:
            try:
                self.recovery_interval_seconds = max(0.05, float(env_recovery))
            except ValueError:
                self.recovery_interval_seconds = DEFAULT_CALLBACK_RECOVERY_INTERVAL_S
        else:
            self.recovery_interval_seconds = DEFAULT_CALLBACK_RECOVERY_INTERVAL_S

        self._last_recovery_at: float = 0.0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @classmethod
    def get_instance(
        cls, interval_seconds: float | None = None
    ) -> WorkbenchQueuePatrolService:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(interval_seconds=interval_seconds)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for unit tests)."""
        with cls._lock:
            cls._instance = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._patrol_loop())
        logger.info(
            "WorkbenchQueuePatrolService started (interval: %.2fs)",
            self.interval_seconds,
        )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            self._task = None
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("WorkbenchQueuePatrolService stopped cleanly")

    async def _patrol_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now - self._last_recovery_at >= self.recovery_interval_seconds:
                self._last_recovery_at = now
                try:
                    from frago.session.async_dispatch import (
                        reconcile_recoverable_callback_deliveries,
                    )

                    await asyncio.to_thread(reconcile_recoverable_callback_deliveries)
                except Exception:
                    logger.debug(
                        "Error during recoverable callback reconciliation tick",
                        exc_info=True,
                    )

            try:
                await asyncio.to_thread(workbench_queue.patrol_active_queues, sync=True)
            except Exception:
                logger.debug("Error during autonomous queue patrol tick", exc_info=True)

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval_seconds
                )
