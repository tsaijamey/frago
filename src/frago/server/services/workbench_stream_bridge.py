"""Bridge that connects SessionStream file-watch events to the WebSocket
broadcast channel, so the workbench frontend receives record deltas in
real time instead of 5-second polling.

Design:
- Lazily starts a ``SessionStream`` per project when a session from that
  project is first viewed in the workbench.
- On receipt of new records, broadcasts ``session_records_append`` via the
  shared WebSocket manager.
- On turn completion, broadcasts ``session_turn_done``.
- Callbacks fire on the watcher's thread; the bridge uses
  ``asyncio.run_coroutine_threadsafe`` to cross into the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

from frago.server.websocket import create_message, manager
from frago.session.adapters.claude_code_records import find_session_file
from frago.session.opencode_stream import OpencodeStream
from frago.session.stream import SessionStream

logger = logging.getLogger(__name__)


# WebSocket event types (extend MessageType or keep local)
WS_SESSION_RECORDS_APPEND = "session_records_append"
WS_SESSION_TURN_DONE = "session_turn_done"


def _read_cwd_from_jsonl(file_path: Path) -> str | None:
    """Read the ``cwd`` field from the first few lines of a session JSONL."""
    try:
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            for _ in range(5):
                line = fh.readline()
                if not line:
                    break
                try:
                    record = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                cwd = record.get("cwd")
                if cwd and isinstance(cwd, str):
                    return cwd
    except OSError:
        pass
    return None


class WorkbenchStreamBridge:
    """Singleton that lazily starts ``SessionStream`` instances per project.

    Usage::

        bridge = WorkbenchStreamBridge.get_instance()
        bridge.ensure_watching(session_id)
    """

    _instance: WorkbenchStreamBridge | None = None
    _class_lock = threading.Lock()

    def __init__(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._streams: dict[str, SessionStream] = {}  # project_path → stream
        self._opencode_stream: OpencodeStream | None = None
        self._lock = threading.Lock()
        self._loop = loop

    # ---- singleton --------------------------------------------------------

    @classmethod
    def get_instance(cls, loop: asyncio.AbstractEventLoop | None = None) -> WorkbenchStreamBridge:
        """Return the process-wide singleton (thread-safe)."""
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls(loop)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Discard the singleton (test isolation)."""
        with cls._class_lock:
            if cls._instance is not None:
                cls._instance.stop_all()
                cls._instance = None

    # ---- lifecycle --------------------------------------------------------

    def ensure_watching(self, session_id: str) -> None:
        """Start watching the project for *session_id* if not already.

        Claude Code sessions (UUID-shaped) → ``SessionStream`` per project.
        Opencode sessions (``ses_`` prefix) → shared ``OpencodeStream``.

        Safe to call multiple times — duplicate calls are no-ops.
        """
        # Opencode session → shared OpencodeStream
        if session_id.startswith("ses_"):
            with self._lock:
                if self._opencode_stream is None:
                    self._opencode_stream = OpencodeStream(
                        on_records=self._on_new_records,
                        on_turn_complete=self._on_turn_complete,
                    )
                    self._opencode_stream.start()
                self._opencode_stream.watch_session(session_id)
            return

        # Claude Code session → SessionStream per project
        file_path = find_session_file(session_id)
        if file_path is None:
            logger.warning("WorkbenchStreamBridge: session file not found for %s", session_id)
            return

        project_path = _read_cwd_from_jsonl(file_path)
        if project_path is None:
            logger.warning("WorkbenchStreamBridge: no cwd found in %s", file_path)
            return

        with self._lock:
            if project_path in self._streams:
                return

            logger.info("WorkbenchStreamBridge: starting stream for %s", project_path)
            stream = SessionStream(
                project_path=project_path,
                on_records=self._on_new_records,
                on_turn_complete=self._on_turn_complete,
            )
            stream.start()
            self._streams[project_path] = stream

    def stop_all(self) -> None:
        """Stop all active streams."""
        with self._lock:
            for path, stream in list(self._streams.items()):
                try:
                    stream.stop()
                except Exception:
                    logger.exception("WorkbenchStreamBridge: error stopping stream %s", path)
            self._streams.clear()
            if self._opencode_stream is not None:
                try:
                    self._opencode_stream.stop()
                except Exception:
                    logger.exception("WorkbenchStreamBridge: error stopping opencode stream")
                self._opencode_stream = None

    # ---- callbacks (called on watcher thread) -----------------------------

    def _on_new_records(self, session_id: str, records: list[dict]) -> None:
        """Called by SessionStream when new records arrive."""
        if not records:
            return
        try:
            loop = self._loop or asyncio.get_event_loop()
        except RuntimeError:
            return

        data = {"session_id": session_id, "records": records}
        msg = create_message(WS_SESSION_RECORDS_APPEND, data)
        asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)

    def _on_turn_complete(self, session_id: str, done: bool,
                          stop_reason: str | None) -> None:
        """Called by SessionStream when a turn flips to complete."""
        try:
            loop = self._loop or asyncio.get_event_loop()
        except RuntimeError:
            return

        data = {
            "session_id": session_id,
            "done": done,
            "stop_reason": stop_reason,
        }
        msg = create_message(WS_SESSION_TURN_DONE, data)
        asyncio.run_coroutine_threadsafe(manager.broadcast(msg), loop)
