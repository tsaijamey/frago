"""Data models for the file watching infrastructure.

These structures are deliberately lightweight — they describe
file-system events and watch targets without any domain semantics.
Domain consumers translate FileEvents into their own models downstream.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

EventType = Literal["created", "modified", "deleted", "moved"]


@dataclass(slots=True)
class FileEvent:
    """A file-system event produced by the OS and forwarded by watchdog.

    Attributes:
        path: Absolute or relative path of the affected file.
        event_type: What happened (created / modified / deleted / moved).
        src_path: For moved events only — the original path before the move.
        is_directory: Whether the event target is a directory.
        timestamp: Unix timestamp (float) when the event was received.
    """

    path: str
    event_type: EventType
    src_path: str | None = None
    is_directory: bool = False
    timestamp: float = 0.0


@dataclass
class WatchTarget:
    """A watch registration describing what to monitor and how to react.

    Each target pairs a directory path with a set of file-name patterns
    and one or more callbacks.  Callbacks are invoked on the Observer's
    internal thread — consumers that bridge to asyncio or UI must handle
    thread-safety themselves.

    Attributes:
        path: Directory to watch (absolute path recommended).
        patterns: Glob-style patterns to filter files (e.g. ``["*.jsonl"]``).
            ``None`` or empty means "all files".
        on_created: Called when a new file appears in the watched directory.
        on_modified: Called when an existing file is written to.
        on_deleted: Called when a file is removed from the directory.
        on_moved: Called when a file is renamed / moved.
        recursive: Whether to watch subdirectories (default False).
    """

    path: str
    patterns: list[str] | None = None
    on_created: Callable[[FileEvent], None] | None = None
    on_modified: Callable[[FileEvent], None] | None = None
    on_deleted: Callable[[FileEvent], None] | None = None
    on_moved: Callable[[FileEvent], None] | None = None
    recursive: bool = False

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("WatchTarget.path must not be empty")
        if self.patterns is not None and not isinstance(self.patterns, list):
            raise TypeError("WatchTarget.patterns must be a list or None")
