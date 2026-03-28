"""Periodic tab cleanup service.

Reconciles tab group state with actual Chrome tabs and closes orphan tabs
that are not tracked by any group and not the landing page.
"""

import asyncio
import logging
import threading
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Cleanup interval: 60 seconds
TAB_CLEANUP_INTERVAL_SECONDS = 60

# CDP default
DEFAULT_CDP_PORT = 9222


class TabCleanupService:
    """Periodically reconcile tab groups and close orphan tabs."""

    _instance: Optional["TabCleanupService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @classmethod
    def get_instance(cls) -> "TabCleanupService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            "Tab cleanup service started (interval: %ds)",
            TAB_CLEANUP_INTERVAL_SECONDS,
        )

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
        logger.info("Tab cleanup service stopped")

    async def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._do_cleanup)
            except Exception as e:
                logger.debug("Tab cleanup cycle failed: %s", e)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=TAB_CLEANUP_INTERVAL_SECONDS,
                )
                break
            except asyncio.TimeoutError:
                continue

    def _do_cleanup(self) -> None:
        """Reconcile groups and close orphan tabs (runs in thread pool)."""
        from frago.cdp.tab_group_manager import TabGroupManager

        port = DEFAULT_CDP_PORT

        # Check if CDP is alive
        try:
            requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        except Exception:
            return  # Chrome not running, skip

        tgm = TabGroupManager(port=port)
        tgm.reconcile()

        # Collect grouped target_ids
        grouped_ids: set[str] = set()
        for group in tgm.list_groups().values():
            grouped_ids.update(group.tabs.keys())

        # Fetch live tabs and close orphans
        try:
            resp = requests.get(
                f"http://127.0.0.1:{port}/json/list", timeout=5
            )
            resp.raise_for_status()
        except Exception:
            return

        closed = 0
        for t in resp.json():
            if t.get("type") != "page":
                continue
            tid = t.get("id", "")
            url = t.get("url", "")
            title = t.get("title", "")
            # Keep: landing page, grouped tabs, data URLs
            if "/chrome/dashboard" in url or title == "frago":
                continue
            if url.startswith("data:text/html"):
                continue
            if tid in grouped_ids:
                continue
            # Orphan — close it
            try:
                requests.get(
                    f"http://127.0.0.1:{port}/json/close/{tid}", timeout=2
                )
                closed += 1
            except Exception:
                pass

        if closed:
            logger.info("Tab cleanup: closed %d orphan tab(s)", closed)
