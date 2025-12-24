"""Session synchronization service.

Provides background session synchronization from Claude Code
(~/.claude/projects/) to Frago session storage (~/.frago/sessions/).
"""

import asyncio
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Sync interval in seconds
SYNC_INTERVAL_SECONDS = 30


class SyncService:
    """Background session sync service."""

    _instance: Optional["SyncService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the sync service."""
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_result: Optional[Dict[str, Any]] = None

    @classmethod
    def get_instance(cls) -> "SyncService":
        """Get singleton instance.

        Returns:
            SyncService instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        """Start background sync task."""
        if self._task is not None and not self._task.done():
            logger.warning("Sync service already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"Session sync started (interval: {SYNC_INTERVAL_SECONDS}s)")

    async def stop(self) -> None:
        """Stop background sync task."""
        if self._task is None or self._task.done():
            return

        self._stop_event.set()
        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        logger.info("Session sync stopped")

    async def _sync_loop(self) -> None:
        """Background sync loop."""
        while not self._stop_event.is_set():
            try:
                # Run sync in thread pool to avoid blocking
                result = await asyncio.get_event_loop().run_in_executor(
                    None, self._do_sync
                )
                self._last_result = result

                if result.get("synced", 0) > 0 or result.get("updated", 0) > 0:
                    logger.info(
                        f"Session sync: synced={result.get('synced', 0)}, "
                        f"updated={result.get('updated', 0)}"
                    )

            except Exception as e:
                logger.warning(f"Session sync failed: {e}")

            # Wait for next sync interval or stop event
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=SYNC_INTERVAL_SECONDS,
                )
                # If wait completes without timeout, stop was requested
                break
            except asyncio.TimeoutError:
                # Timeout means continue to next sync
                continue

    def _do_sync(self) -> Dict[str, Any]:
        """Perform synchronization (runs in thread pool).

        Returns:
            Sync result dictionary
        """
        from frago.session.sync import sync_all_projects

        result = sync_all_projects()

        return {
            "synced": result.synced,
            "updated": result.updated,
            "skipped": result.skipped,
            "errors": result.errors,
        }

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Get the last sync result.

        Returns:
            Last sync result or None
        """
        return self._last_result

    @staticmethod
    def sync_now() -> Dict[str, Any]:
        """Perform immediate synchronization.

        Returns:
            Sync result dictionary
        """
        try:
            from frago.session.sync import sync_all_projects

            result = sync_all_projects()

            return {
                "success": True,
                "synced": result.synced,
                "updated": result.updated,
                "skipped": result.skipped,
                "errors": result.errors,
            }
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {
                "success": False,
                "error": str(e),
            }
