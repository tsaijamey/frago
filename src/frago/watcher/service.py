"""WatchdogObserverService — CLI-layer singleton that manages a shared
watchdog Observer and dispatches file-system events to registered consumers.

Design contract:
- Owns ONE watchdog Observer instance (not one per consumer).
- Consumers register WatchTargets; the service schedules handlers under the hood.
- Callbacks fire on the Observer's internal thread — consumers bridge to
  asyncio / UI / subprocess themselves.
- This module does NOT import server/websocket/state.  It sits at the
  CLI layer alongside session, recipes, chrome, etc.
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.events import (
        FileCreatedEvent,
        FileDeletedEvent,
        FileModifiedEvent,
        FileMovedEvent,
    )

from frago.watcher.models import FileEvent, WatchTarget

logger = logging.getLogger(__name__)


class _DispatchHandler(FileSystemEventHandler):
    """Per-directory event handler that fans out to registered WatchTargets.

    One handler is created for each distinct watched directory path.
    When a file-system event arrives the handler finds every WatchTarget
    whose patterns match the affected file and calls the relevant callback.
    """

    def __init__(self, watched_path: str) -> None:
        super().__init__()
        self._watched_path = os.path.abspath(watched_path)
        self._targets: list[WatchTarget] = []
        self._lock = threading.Lock()

    # ---- target management -------------------------------------------------

    def add_target(self, target: WatchTarget) -> None:
        with self._lock:
            self._targets.append(target)

    def remove_target(self, target: WatchTarget) -> None:
        with self._lock:
            self._targets.remove(target)

    @property
    def target_count(self) -> int:
        with self._lock:
            return len(self._targets)

    # ---- event dispatch ----------------------------------------------------

    def _matches(self, target: WatchTarget, file_name: str) -> bool:
        """Return True if *file_name* matches the target's pattern list."""
        if not target.patterns:
            return True
        return any(fnmatch.fnmatch(file_name, p) for p in target.patterns)

    def _dispatch(self, event_type: str, file_path: str, is_directory: bool,
                  src_path: str | None = None) -> None:
        file_name = os.path.basename(file_path)
        fe = FileEvent(
            path=file_path,
            event_type=event_type,  # type: ignore[arg-type]
            src_path=src_path,
            is_directory=is_directory,
            timestamp=0.0,
        )
        with self._lock:
            targets_snapshot = list(self._targets)

        for target in targets_snapshot:
            if not self._matches(target, file_name):
                continue
            cb: Callable[[FileEvent], None] | None = {
                "created": target.on_created,
                "modified": target.on_modified,
                "deleted": target.on_deleted,
                "moved": target.on_moved,
            }.get(event_type)
            if cb is None:
                continue
            try:
                cb(fe)
            except Exception:
                logger.exception(
                    "Watch target callback failed (path=%s, event=%s)",
                    file_path,
                    event_type,
                )

    def on_created(self, event: FileCreatedEvent | Any) -> None:
        self._dispatch("created", str(event.src_path), bool(event.is_directory))

    def on_modified(self, event: FileModifiedEvent | Any) -> None:
        self._dispatch("modified", str(event.src_path), bool(event.is_directory))

    def on_deleted(self, event: FileDeletedEvent | Any) -> None:
        self._dispatch("deleted", str(event.src_path), bool(event.is_directory))

    def on_moved(self, event: FileMovedEvent | Any) -> None:
        self._dispatch("moved", str(event.dest_path), bool(event.is_directory),
                       src_path=str(event.src_path))


# ====================================================================
# Service
# ====================================================================


class WatchdogObserverService:
    """Singleton manager for a shared watchdog Observer.

    Usage::

        svc = WatchdogObserverService.get_instance()
        svc.add(WatchTarget(path="/tmp", patterns=["*.log"],
                            on_modified=my_handler))
        svc.start()
        ...
        svc.stop()
    """

    _instance: ClassVar[WatchdogObserverService | None] = None
    _class_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._observer: Any = None
        self._handlers: dict[str, _DispatchHandler] = {}  # abspath → handler
        self._running: bool = False
        self._state_lock = threading.Lock()

    # ---- singleton ---------------------------------------------------------

    @classmethod
    def get_instance(cls) -> WatchdogObserverService:
        """Return the process-wide singleton (thread-safe)."""
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Discard the singleton (primarily for test isolation)."""
        with cls._class_lock:
            if cls._instance is not None:
                with contextlib.suppress(Exception):
                    cls._instance.stop()
                cls._instance = None

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the underlying watchdog Observer (idempotent)."""
        with self._state_lock:
            if self._running:
                return
            if self._observer is not None:
                return  # already started externally

            observer: Any = Observer()
            # Schedule any handlers that were registered before start()
            for path, handler in self._handlers.items():
                observer.schedule(handler, path, recursive=any(
                    t.recursive for t in handler._targets  # noqa: SLF001
                ))

            observer.start()
            self._observer = observer
            self._running = True
            logger.debug("WatchdogObserverService started (%d paths watched)",
                         len(self._handlers))

    def stop(self) -> None:
        """Stop the Observer and release resources (idempotent)."""
        with self._state_lock:
            if self._observer is None:
                self._running = False
                return

            observer = self._observer
            self._observer = None
            self._running = False

        observer.stop()
        observer.join(timeout=3)
        logger.debug("WatchdogObserverService stopped")

    # ---- registration ------------------------------------------------------

    def add(self, target: WatchTarget) -> None:
        """Register a watch target.

        Safe to call before or after ``start()``.  If the Observer is
        already running the new handler is scheduled immediately.
        """
        abspath = os.path.abspath(target.path)

        with self._state_lock:
            if abspath not in self._handlers:
                self._handlers[abspath] = _DispatchHandler(abspath)
                # If Observer already running, schedule the new handler now
                if self._observer is not None:
                    self._observer.schedule(
                        self._handlers[abspath],
                        abspath,
                        recursive=target.recursive,
                    )

            self._handlers[abspath].add_target(target)

        logger.debug("WatchdogObserverService: added target for %s", abspath)

    def remove(self, target: WatchTarget) -> None:
        """Unregister a watch target.

        When the last target for a directory is removed the underlying
        handler is unscheduled.
        """
        abspath = os.path.abspath(target.path)

        with self._state_lock:
            handler = self._handlers.get(abspath)
            if handler is None:
                return

            handler.remove_target(target)

            if handler.target_count == 0:
                self._handlers.pop(abspath, None)
                logger.debug(
                    "WatchdogObserverService: removed last target for %s",
                    abspath,
                )

    # ---- query -------------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the Observer is currently active."""
        return self._running

    @property
    def watch_count(self) -> int:
        """How many directories are currently being watched."""
        with self._state_lock:
            return len(self._handlers)
