"""Sessions directory watcher service.

Uses watchdog to monitor ~/.frago/sessions/ for real-time updates,
replacing polling-based change detection.
"""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from watchdog.events import (
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    DirCreatedEvent,
)
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# Debounce delay for rapid file changes
DEBOUNCE_DELAY_SECONDS = 0.5

# Sessions directory
SESSIONS_DIR = Path.home() / ".frago" / "sessions"


class SessionsEventHandler(FileSystemEventHandler):
    """Handle file system events in sessions directory."""

    def __init__(self, on_change: callable):
        """Initialize handler.

        Args:
            on_change: Callback when sessions change detected
        """
        super().__init__()
        self._on_change = on_change
        self._pending = False
        self._lock = threading.Lock()

    def _trigger_change(self) -> None:
        """Trigger change callback with debouncing."""
        with self._lock:
            if not self._pending:
                self._pending = True
                self._on_change()

    def reset_pending(self) -> None:
        """Reset pending flag after processing."""
        with self._lock:
            self._pending = False

    def on_any_event(self, event) -> None:
        """Handle any file system event."""
        # Skip directory-only events that aren't creation
        if event.is_directory and event.event_type not in ("created", "modified"):
            return

        path = event.src_path

        # Only trigger for relevant session files
        if path.endswith(".json") or path.endswith(".jsonl"):
            self._trigger_change()


class SessionsWatcher:
    """Watch ~/.frago/sessions/ directory for changes.

    Uses watchdog for efficient file system monitoring instead of polling.
    When changes are detected, triggers StateManager refresh.
    """

    _instance: Optional["SessionsWatcher"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the watcher."""
        self._observer: Optional[Observer] = None
        self._handler: Optional[SessionsEventHandler] = None
        self._running = False
        self._debounce_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def get_instance(cls) -> "SessionsWatcher":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        """Start watching sessions directory."""
        if self._running:
            logger.warning("SessionsWatcher already running")
            return

        # Ensure sessions directory exists
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

        # Store event loop for cross-thread callback
        self._loop = asyncio.get_event_loop()

        # Create handler with callback
        self._handler = SessionsEventHandler(self._on_sessions_change)

        # Create and start observer
        self._observer = Observer()
        self._observer.schedule(self._handler, str(SESSIONS_DIR), recursive=True)
        self._observer.start()

        self._running = True
        logger.info(f"SessionsWatcher started, monitoring: {SESSIONS_DIR}")

    async def stop(self) -> None:
        """Stop watching."""
        if not self._running:
            return

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

        self._running = False
        logger.info("SessionsWatcher stopped")

    def _on_sessions_change(self) -> None:
        """Handle sessions directory change (called from watchdog thread)."""
        if self._loop:
            # Schedule async refresh in the event loop
            # Note: Don't check is_running() from another thread - it's unreliable
            try:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._debounced_refresh())
                )
            except RuntimeError:
                pass  # Event loop closed

    async def _debounced_refresh(self) -> None:
        """Execute refresh after debounce delay."""
        # If a task is already running, it will handle the refresh
        if self._debounce_task and not self._debounce_task.done():
            return

        # Create new refresh task
        self._debounce_task = asyncio.create_task(self._do_refresh())
        logger.debug("SessionsWatcher: refresh task scheduled")

    async def _do_refresh(self) -> None:
        """Actually perform the refresh."""
        await asyncio.sleep(DEBOUNCE_DELAY_SECONDS)

        # Reset pending flag
        if self._handler:
            self._handler.reset_pending()

        try:
            from frago.server.state import StateManager

            state_manager = StateManager.get_instance()
            if state_manager.is_initialized():
                await state_manager.refresh_tasks(broadcast=True)
        except Exception as e:
            logger.error(f"SessionsWatcher refresh failed: {e}")
