"""Session synchronization service.

Provides background session synchronization from Claude Code
(~/.claude/projects/) to Frago session storage (~/.frago/sessions/).
"""

import asyncio
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Sync interval in seconds (30s is sufficient)
SYNC_INTERVAL_SECONDS = 30


class SyncService:
    """Background session sync service."""

    _instance: Optional["SyncService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the sync service."""
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_result: dict[str, Any] | None = None

        # mtime cache: session_id -> last-seen mtime (float)
        # Persists across sync cycles so unchanged sessions skip read_metadata entirely
        self._session_mtimes: dict[str, float] = {}

        # opencode counterpart: session_id -> last-seen time_updated (ms).
        # Same role as the mtime cache, keyed on the session database's own clock.
        self._opencode_updated: dict[str, int] = {}

        # codex counterpart: session_id -> last-seen rollout mtime (float).
        # codex records live in append-only files, so mtime is the right clock
        # here, exactly as it is for Claude Code.
        self._codex_mtimes: dict[str, float] = {}

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

        import contextlib
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

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

                # Check if there are changes
                has_changes = result.get("synced", 0) > 0 or result.get("updated", 0) > 0

                if has_changes:
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
            except TimeoutError:
                # Timeout means continue to next sync
                continue

    def _do_sync(self) -> dict[str, Any]:
        """Perform synchronization (runs in thread pool).

        Covers every core; one failing NEVER stops the others.

        Returns:
            Sync result dictionary
        """
        from frago.session.sync import sync_all_projects

        totals = {"synced": 0, "updated": 0, "skipped": 0, "errors": []}

        for label, run in (
            ("claude", lambda: sync_all_projects(mtime_cache=self._session_mtimes)),
            ("opencode", self._sync_opencode),
            ("codex", self._sync_codex),
        ):
            try:
                result = run()
            except Exception as e:
                logger.warning(f"{label} session sync failed: {e}")
                totals["errors"].append(f"{label}: {e}")
                continue
            totals["synced"] += result.synced
            totals["updated"] += result.updated
            totals["skipped"] += result.skipped
            totals["errors"].extend(result.errors)

        return totals

    def _sync_opencode(self) -> Any:
        """Archive opencode sessions from its SQLite log (spec 20260725 Phase 3)."""
        from frago.session.opencode_sync import sync_opencode_sessions

        return sync_opencode_sessions(since_updated_cache=self._opencode_updated)

    def _sync_codex(self) -> Any:
        """Archive codex sessions from their rollout JSONL files."""
        from frago.session.codex_sync import sync_codex_sessions

        return sync_codex_sessions(since_mtime_cache=self._codex_mtimes)

    def get_last_result(self) -> dict[str, Any] | None:
        """Get the last sync result.

        Returns:
            Last sync result or None
        """
        return self._last_result

    @staticmethod
    def sync_now() -> dict[str, Any]:
        """Perform immediate synchronization.

        Returns:
            Sync result dictionary
        """
        from frago.session.codex_sync import sync_codex_sessions
        from frago.session.opencode_sync import sync_opencode_sessions
        from frago.session.sync import sync_all_projects

        totals: dict[str, Any] = {
            "success": False,
            "synced": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
        }
        succeeded = False

        # Every core runs; one failing NEVER stops the others.
        for label, run in (
            ("claude", sync_all_projects),
            ("opencode", sync_opencode_sessions),
            ("codex", sync_codex_sessions),
        ):
            try:
                result = run()
            except Exception as e:
                logger.error(f"{label} sync failed: {e}")
                totals["errors"].append(f"{label}: {e}")
                continue
            succeeded = True
            totals["synced"] += result.synced
            totals["updated"] += result.updated
            totals["skipped"] += result.skipped
            totals["errors"].extend(result.errors)

        totals["success"] = succeeded
        if not succeeded:
            totals["error"] = "; ".join(totals["errors"])
        return totals
