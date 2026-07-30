"""Opencode session streaming — polls the opencode SQLite database for
new records and pushes deltas in near-real-time.

Unlike Claude Code (one JSONL per session), opencode stores everything in a
single SQLite file (``~/.local/share/opencode/opencode.db``) in WAL mode.
macOS FSEvents doesn't reliably detect WAL file writes, so this module
uses a short polling interval instead of file-system watching.

Design:
- One ``OpencodeStream`` singleton polls the DB every ``POLL_INTERVAL``
  seconds while any session is registered.
- Consumers call ``watch_session(sid)`` / ``unwatch_session(sid)`` to
  register / deregister interest.
- On each tick the stream re-translates watched sessions through
  :func:`opencode_records.translate_session`, diffs against cached seq,
  and pushes deltas via ``on_records`` callback.
- Turn completion is detected via :func:`opencode_store.latest_turn`.
- The polling thread stops automatically when no sessions are watched.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from frago.session.opencode_store import db_path, latest_turn

logger = logging.getLogger(__name__)

POLL_INTERVAL = 1.0  # seconds between polls when sessions are watched


class OpencodeStream:
    """Poll opencode DB and push record deltas for registered sessions.

    Usage::

        stream = OpencodeStream(
            on_records=lambda sid, recs: print(sid, len(recs)),
            on_turn_complete=lambda sid, done, reason: print(sid, done),
        )
        stream.start()
        stream.watch_session("ses_abc123")
        ...
        stream.stop()
    """

    def __init__(
        self,
        *,
        on_records: Callable[[str, list[dict]], None] | None = None,
        on_turn_complete: Callable[[str, bool, str | None], None] | None = None,
    ) -> None:
        self._on_records = on_records
        self._on_turn_complete = on_turn_complete

        self._session_seqs: dict[str, int] = {}
        self._session_done: dict[str, bool] = {}
        self._watched: set[str] = set()
        self._state_lock = threading.Lock()

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start the background poll thread."""
        if self._running:
            return

        db = db_path()
        if not db.exists():
            logger.debug("OpencodeStream: db not found at %s", db)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="opencode-stream")
        self._thread.start()
        self._running = True
        logger.info("OpencodeStream started: polling %s every %.1fs", db, POLL_INTERVAL)

    def stop(self) -> None:
        """Stop the background poll thread."""
        if not self._running:
            return
        self._stop_event.set()
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        logger.info("OpencodeStream stopped")

    # ---- session registration ---------------------------------------------

    def watch_session(self, session_id: str) -> None:
        """Register interest in *session_id*."""
        with self._state_lock:
            self._watched.add(session_id)

    def unwatch_session(self, session_id: str) -> None:
        """Deregister interest in *session_id*."""
        with self._state_lock:
            self._watched.discard(session_id)
            self._session_seqs.pop(session_id, None)
            self._session_done.pop(session_id, None)

    # ---- internal ---------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread: poll every POLL_INTERVAL while sessions are watched."""
        while not self._stop_event.is_set():
            with self._state_lock:
                has_sessions = bool(self._watched)

            if has_sessions:
                self._process()

            self._stop_event.wait(POLL_INTERVAL)

    def _process(self) -> None:
        """Re-translate all watched sessions, emit deltas."""
        with self._state_lock:
            sessions = set(self._watched)

        if not sessions:
            return

        for sid in sessions:
            try:
                self._process_session(sid)
            except Exception:
                logger.exception(
                    "OpencodeStream: failed processing session %s", sid
                )

    def _process_session(self, session_id: str) -> None:
        """Re-translate one session, diff, and emit."""
        records = _safe_translate(session_id)
        if records is None:
            return

        last_seq = self._session_seqs.get(session_id, -1)
        new_records = [r for r in records if r.seq > last_seq]

        if new_records:
            self._session_seqs[session_id] = new_records[-1].seq
            if self._on_records is not None:
                from dataclasses import asdict

                try:
                    self._on_records(session_id, [asdict(r) for r in new_records])
                except Exception:
                    logger.exception(
                        "OpencodeStream on_records callback failed (session=%s)",
                        session_id,
                    )

        turn = latest_turn(session_id)
        done = turn.done if turn is not None else False
        prev_done = self._session_done.get(session_id, False)

        if done and not prev_done:
            self._session_done[session_id] = True
            if self._on_turn_complete is not None:
                try:
                    self._on_turn_complete(session_id, True, "stop" if done else None)
                except Exception:
                    logger.exception(
                        "OpencodeStream on_turn_complete callback failed (session=%s)",
                        session_id,
                    )
        elif not done:
            self._session_done[session_id] = False


def _safe_translate(session_id: str) -> list | None:
    """Call translate_session, returning None on failure."""
    try:
        from frago.session.adapters.opencode_records import translate_session

        return translate_session(session_id)
    except Exception:
        logger.debug(
            "OpencodeStream: translate_session failed for %s", session_id, exc_info=True
        )
        return None
