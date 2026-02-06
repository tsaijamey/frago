"""GitHub multi-device sync scheduler service.

Provides periodic background synchronization of Frago resources
with the configured GitHub repository.
"""

import asyncio
import logging
import threading
from typing import Any, Dict, Optional

from frago.server.services.multidevice_sync_service import MultiDeviceSyncService

logger = logging.getLogger(__name__)

# Sync interval in seconds (5 minutes)
GITHUB_SYNC_INTERVAL_SECONDS = 300


class GitHubSyncScheduler:
    """Service for scheduled GitHub sync with auto-start based on configuration."""

    _instance: Optional["GitHubSyncScheduler"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the scheduler."""
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._last_sync_result: Optional[Dict[str, Any]] = None
        self._last_sync_error: Optional[str] = None

    @classmethod
    def get_instance(cls) -> "GitHubSyncScheduler":
        """Get singleton instance.

        Returns:
            GitHubSyncScheduler instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def is_configured(self) -> bool:
        """Check if GitHub sync is configured.

        Returns:
            True if sync_repo_url is set in config or detectable from git remote
        """
        try:
            from frago.tools.sync_repo import get_sync_repo_url

            return bool(get_sync_repo_url())
        except Exception:
            return False

    async def start(self) -> None:
        """Start background sync task if configured.

        Only starts if sync_repo_url is configured.
        """
        if not self.is_configured():
            logger.info("GitHub sync not configured, skipping scheduled sync")
            return

        if self._task is not None and not self._task.done():
            logger.warning("GitHub sync scheduler already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(
            f"GitHub sync scheduler started "
            f"(interval: {GITHUB_SYNC_INTERVAL_SECONDS}s)"
        )

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
        logger.info("GitHub sync scheduler stopped")

    async def _sync_loop(self) -> None:
        """Background sync loop."""
        # Initial delay to avoid sync storm on startup
        await asyncio.sleep(10)

        while not self._stop_event.is_set():
            # Check if still configured (user might have disconnected)
            if not self.is_configured():
                logger.info("GitHub sync no longer configured, stopping scheduler")
                break

            # Perform sync
            try:
                await self._do_sync()
            except Exception as e:
                logger.warning(f"GitHub sync failed: {e}")
                self._last_sync_error = str(e)

            # Wait for next interval or stop event
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=GITHUB_SYNC_INTERVAL_SECONDS,
                )
                # If wait completes without timeout, stop was requested
                break
            except asyncio.TimeoutError:
                # Timeout means continue to next sync
                continue

    async def _do_sync(self) -> None:
        """Perform sync operation."""
        # Check if a manual sync is already running
        result = MultiDeviceSyncService.get_sync_result()
        if result.get("status") == "running":
            logger.debug("Sync already in progress, skipping scheduled sync")
            return

        logger.info("Starting scheduled GitHub sync...")

        # Use sync_now with auto_refresh=True (handles cache refresh internally)
        result = await MultiDeviceSyncService.sync_now(auto_refresh=True)

        self._last_sync_result = result
        self._last_sync_error = result.get("error")

        if result.get("success"):
            logger.info(
                f"Scheduled GitHub sync completed: "
                f"local={result.get('local_changes', 0)}, "
                f"remote={result.get('remote_updates', 0)}"
            )
        else:
            logger.warning(f"Scheduled GitHub sync failed: {result.get('error')}")

    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """Get the last sync result.

        Returns:
            Dictionary with last sync result or None
        """
        return self._last_sync_result

    def get_last_error(self) -> Optional[str]:
        """Get the last sync error if any.

        Returns:
            Error message or None
        """
        return self._last_sync_error

    def is_running(self) -> bool:
        """Check if scheduler is running.

        Returns:
            True if background task is active
        """
        return self._task is not None and not self._task.done()
