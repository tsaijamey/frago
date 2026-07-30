"""Session file stream — watches Claude Code session JSONL files in real-time.

Moved out of :mod:`frago.session.monitor`: the Observer lifecycle is now owned
by :mod:`frago.watcher`, and this module handles only the session-domain logic:

- Encode project paths → Claude Code session directory
- On file change, debounce, re-read the full JSONL through
  :mod:`frago.session.adapters.claude_code_records`
- Track the latest seen ``seq`` to surface only new ``UnifiedRecord`` entries
- Check turn completion via :func:`frago.session.transcript_completion.evaluate_file`

Design boundary:
- ``SessionStream`` registers with ``WatchdogObserverService`` (never owns an Observer)
- Callbacks fire on the Observer's thread — consumers must handle thread-safety
- This module does NOT import ``server/`` or ``cli/``
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from frago.session.claude_sessions import CLAUDE_PROJECTS_DIR
from frago.session.monitor import encode_project_path
from frago.watcher import FileEvent, WatchdogObserverService, WatchTarget

logger = logging.getLogger(__name__)

# Default debounce: wait for the file to settle before re-reading.
DEFAULT_DEBOUNCE_SECONDS = 0.3


class SessionStream:
    """Watch all ``*.jsonl`` files in one Claude Code project directory.

    Usage::

        stream = SessionStream(
            project_path="/Users/jamey/Repos/frago",
            on_records=my_handler,         # called with new UnifiedRecords
            on_turn_complete=my_handler,   # called when a turn finishes
        )
        stream.start()
        ...
        stream.stop()
    """

    def __init__(
        self,
        project_path: str,
        *,
        on_records: Callable[[str, list[dict[str, object]]], None] | None = None,
        on_turn_complete: Callable[[str, bool, str | None], None] | None = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        session_id_filter: str | None = None,
    ) -> None:
        """Create a stream for one project.

        Args:
            project_path: Absolute path to the project being watched.
            on_records: Called with ``(session_id, [record_dict, ...])`` when
                new records arrive.  Each dict is a ``UnifiedRecord`` serialised
                via ``dataclasses.asdict``.
            on_turn_complete: Called with ``(session_id, done, stop_reason)``
                when the latest turn flips to complete.
            debounce_seconds: How long to wait after the last file event before
                re-reading and classifying.
            session_id_filter: If set, only track this specific session.
        """
        self._project_path = os.path.abspath(project_path)
        self._on_records = on_records
        self._on_turn_complete = on_turn_complete
        self._debounce = debounce_seconds
        self._session_id_filter = session_id_filter

        self._watch_dir: Path | None = None
        self._target: WatchTarget | None = None

        # Per-file state: last-known seq (monotonically increasing).
        self._file_seqs: dict[str, int] = {}  # file_path → last seen seq
        # Per-file state: last known turn-completion verdict.
        self._file_done: dict[str, bool] = {}  # file_path → done
        # Debounce timers: file_path → last-event-time
        self._last_event_at: dict[str, float] = {}
        # Debounce lock
        self._debounce_lock = threading.Lock()
        # Running flag
        self._running = False

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Register with the global watcher and begin listening."""
        if self._running:
            return

        encoded = encode_project_path(self._project_path)
        self._watch_dir = CLAUDE_PROJECTS_DIR / encoded
        self._watch_dir.mkdir(parents=True, exist_ok=True)

        self._target = WatchTarget(
            path=str(self._watch_dir),
            patterns=["*.jsonl"],
            on_modified=self._on_file_event,
            on_created=self._on_file_event,
        )

        svc = WatchdogObserverService.get_instance()
        svc.add(self._target)
        svc.start()

        self._running = True
        logger.debug("SessionStream started: %s", self._watch_dir)

    def stop(self) -> None:
        """Unregister from the watcher."""
        if not self._running:
            return

        svc = WatchdogObserverService.get_instance()
        if self._target is not None:
            svc.remove(self._target)
            self._target = None

        self._running = False
        logger.debug("SessionStream stopped: %s", self._project_path)

    # ---- internal ---------------------------------------------------------

    def _on_file_event(self, event: FileEvent) -> None:
        """Called by the watcher thread when a ``*.jsonl`` file changes."""
        if event.is_directory:
            return

        file_path = event.path

        # Respect session filter
        if self._session_id_filter is not None:
            stem = os.path.splitext(os.path.basename(file_path))[0]
            if stem != self._session_id_filter:
                return

        now = time.monotonic()
        with self._debounce_lock:
            self._last_event_at[file_path] = now

        # Sleep outside the lock so other events can update the timestamp
        time.sleep(self._debounce)

        with self._debounce_lock:
            last = self._last_event_at.get(file_path, 0)
            if last > now:
                # A newer event arrived while we were sleeping — skip this round,
                # the follow-up sleep (triggered by the newer event) will handle it.
                return

        self._process_file(file_path)

    def _process_file(self, file_path: str) -> None:
        """Re-read and classify *file_path*, emit new records."""
        try:
            from frago.session.adapters.claude_code_records import to_unified
            from frago.session.transcript_completion import evaluate_file

            records = to_unified(file_path)

            session_id = Path(file_path).stem
            last_seq = self._file_seqs.get(file_path, -1)
            new_records = [r for r in records if r.seq > last_seq]

            if new_records:
                # Update last known seq
                self._file_seqs[file_path] = new_records[-1].seq

                if self._on_records is not None:
                    from dataclasses import asdict

                    try:
                        self._on_records(
                            session_id,
                            [asdict(r) for r in new_records],
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream on_records callback failed (session=%s)",
                            session_id,
                        )

            # Check turn completion (only if new records arrived or not yet known)
            verdict = evaluate_file(Path(file_path))
            done = bool(verdict.done) if verdict is not None else False
            prev_done = self._file_done.get(file_path, False)

            if done and not prev_done:
                # Turn just completed — only fire once per flip
                self._file_done[file_path] = True
                if self._on_turn_complete is not None:
                    try:
                        self._on_turn_complete(
                            session_id,
                            True,
                            verdict.stop_reason if verdict is not None else None,
                        )
                    except Exception:
                        logger.exception(
                            "SessionStream on_turn_complete callback failed (session=%s)",
                            session_id,
                        )
            elif not done:
                self._file_done[file_path] = False

        except Exception:
            logger.exception(
                "SessionStream failed to process file: %s", file_path
            )
