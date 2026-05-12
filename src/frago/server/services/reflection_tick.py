"""Reflection Tick — periodic internal-origin trigger for PA self-reflection.

Spec 20260418-timeline-event-coverage Phase 5. Separate from Heartbeat (which
is pure liveness). Reflection Tick produces `origin=internal, subkind=reflection`
timeline entries and enqueues an `internal_reflection` message so PA can
evaluate whether proactive action is warranted.

Cadence: slow (minutes level, default 30 min) — don't flood PA with busywork.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MIN = 30
DEFAULT_INITIAL_DELAY_SEC = 120  # wait after server start before first tick
DEFAULT_PROMPT_HINT = "扫描最近 timeline，评估是否有需要主动处理的事"


class ReflectionTicker:
    """Async scheduler that periodically triggers internal reflection.

    Not a generic cron — this is purpose-built for PA self-reflection. If the
    PA queue is clogged, the tick still fires (enqueue blocks briefly); the
    enqueue side is responsible for rate control.
    """

    def __init__(
        self,
        *,
        enqueue: Callable[[dict[str, Any]], Awaitable[None]],
        interval_min: int = DEFAULT_INTERVAL_MIN,
        initial_delay_sec: int = DEFAULT_INITIAL_DELAY_SEC,
        prompt_hint: str = DEFAULT_PROMPT_HINT,
    ) -> None:
        self._enqueue = enqueue
        self._interval_sec = max(60, interval_min * 60)
        self._initial_delay = max(0, initial_delay_sec)
        self._prompt_hint = prompt_hint
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "Reflection tick started (interval=%ds, initial_delay=%ds)",
            self._interval_sec, self._initial_delay,
        )

    async def stop(self) -> None:
        if not self._task or self._task.done():
            self._task = None
            return
        self._stop.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Reflection tick stopped")

    async def fire_once(self) -> str:
        """Synchronously trigger one reflection (bypass schedule).

        Used by tests or CLI. Returns the root thread_id generated.
        """
        return await self._fire()

    async def _loop(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._initial_delay)
            return  # stopped during initial delay
        except TimeoutError:
            pass
        while not self._stop.is_set():
            try:
                await self._fire()
            except Exception:
                logger.exception("reflection tick fire failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._interval_sec,
                )
                return
            except TimeoutError:
                continue

    async def _fire(self) -> str:
        from frago.server.services.taskboard import get_board
        from frago.server.services.taskboard.models import IllegalTransitionError
        from frago.server.services.trace import trace_entry, ulid_new

        tid = ulid_new()
        entry = trace_entry(
            origin="internal",
            subkind="reflection",
            data_type="thought",
            thread_id=tid,
            parent_id=None,
            task_id=None,
            data={
                "trigger": "scheduled",
                "prompt_hint": self._prompt_hint,
            },
            role="reflection",
            event="Reflection tick",
        )
        # B-2a: reflection thread 落 TaskBoard (single timeline source)
        try:
            get_board().create_thread(
                thread_id=tid,
                origin="internal",
                subkind="reflection",
                root_summary="Reflection tick",
                by="reflection_tick",
            )
        except IllegalTransitionError:
            # tick fired with same ulid (shouldn't happen) — proceed
            pass
        except Exception:
            logger.debug("reflection tick: board.create_thread failed", exc_info=True)
        await self._enqueue({
            "type": "internal_reflection",
            "thread_id": tid,
            "msg_id": tid,
            "reason": "scheduled",
            "ts": entry.ts,
            "prompt_hint": self._prompt_hint,
        })
        logger.debug("reflection tick fired: thread=%s", tid)
        return tid


def load_reflection_config() -> dict[str, Any]:
    """Read reflection config from ~/.frago/config.json with safe defaults."""
    import json
    from pathlib import Path

    config_file = Path.home() / ".frago" / "config.json"
    defaults = {
        "enabled": True,
        "interval_min": DEFAULT_INTERVAL_MIN,
        "initial_delay_sec": DEFAULT_INITIAL_DELAY_SEC,
        "prompt_hint": DEFAULT_PROMPT_HINT,
    }
    if not config_file.exists():
        return defaults
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        cfg = (data or {}).get("reflection") or {}
        return {**defaults, **cfg}
    except (json.JSONDecodeError, OSError):
        return defaults
