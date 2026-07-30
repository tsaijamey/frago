"""File watching infrastructure for frago.

The watcher module provides a unified Observer lifecycle manager that
decouples file-system event detection from domain-specific consumers.

Design boundary:
- watcher      → manages watchdog Observer instances, dispatches raw FileEvent
- consumers    → register watchers, translate FileEvent into domain semantics

Layered correctly:
  watcher/          ← CLI-layer infrastructure (no server/websocket imports)
  session/stream.py ← consumer: translates jsonl-modify → session record
  server/           ← consumer: bridges FileEvent → WebSocket push
"""

from frago.watcher.models import FileEvent, WatchTarget
from frago.watcher.service import WatchdogObserverService

__all__ = [
    "FileEvent",
    "WatchTarget",
    "WatchdogObserverService",
]
