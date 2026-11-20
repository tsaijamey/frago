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
from frago.session.service import SessionOntologyService

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
        ontology_service: SessionOntologyService | None = None,
        origin: str = "terminal",
    ) -> None:
        self._on_records = on_records
        self._on_turn_complete = on_turn_complete
        self._ontology_service = (
            ontology_service if ontology_service is not None else SessionOntologyService()
        )
        self._origin = origin

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

    def _observed_origin(self, session_id: str) -> str:
        try:
            from frago.session.session_origin import load_origin_index

            if load_origin_index().is_worker(session_id):
                return "worker"
        except Exception:  # noqa: BLE001
            logger.debug("could not read origin index for %s", session_id, exc_info=True)
        return self._origin

    @staticmethod
    def _map_record_to_step_type(kind: str) -> str:
        if kind == "user.say":
            return "user"
        if kind in ("agent.say", "agent.think"):
            return "assistant"
        if kind == "tool.call":
            return "tool_call"
        if kind == "tool.result":
            return "tool_result"
        return "system"

    def _process_session(self, session_id: str) -> None:
        """Re-translate one session, diff, and emit."""
        records = _safe_translate(session_id)
        if records is None:
            return

        first_sight = session_id not in self._session_seqs
        last_seq = self._session_seqs.get(session_id, -1)
        new_records = [r for r in records if r.seq > last_seq]

        if new_records:
            self._session_seqs[session_id] = new_records[-1].seq
            # 刚登记上这一场，第一趟只对水位、一条不发。水位按 -1 起算的话，整场历史会
            # 被当成"新内容"一次性推给浏览器，接在流的尾巴上——最老的内容排在最新内容
            # 后面，人看到的是一坨乱序的旧货。页面打开会话时已经自己取过尾部了。
            if self._on_records is not None and not first_sight:
                from dataclasses import asdict

                try:
                    self._on_records(session_id, [asdict(r) for r in new_records])
                except Exception:
                    logger.exception(
                        "OpencodeStream on_records callback failed (session=%s)",
                        session_id,
                    )

            if not first_sight and self._ontology_service is not None:
                try:
                    from frago.session.service import TERMINAL_STATES

                    _bk = {"call.envelope", "session.state", "context.inject", "todo.snapshot", "usage.tick"}
                    _active_kinds = {
                        "user.say",
                        "tool.call",
                        "tool.result",
                        "agent.think",
                        "subagent.dispatch",
                        "agent.say",
                    }
                    tail_substantive = next(
                        (r for r in reversed(new_records) if r.kind not in _bk),
                        None,
                    )
                    has_active_work = any(r.kind in _active_kinds for r in new_records)
                    origin = self._observed_origin(session_id)
                    existing_rec = self._ontology_service.get_session(session_id)
                    if (
                        existing_rec is not None
                        and getattr(existing_rec, "lifecycle_state", None) in TERMINAL_STATES
                        and has_active_work
                        and (tail_substantive is None or tail_substantive.kind != "error")
                    ):
                        self._ontology_service.start_turn(
                            session_id,
                            agent_kernel_id="opencode",
                            origin=origin,
                        )
                    else:
                        self._ontology_service.ensure_managed_session(
                            session_id=session_id,
                            agent_kernel_id="opencode",
                            origin=origin,
                        )
                    if tail_substantive is not None and tail_substantive.kind == "error":
                        err_payload = (
                            tail_substantive.payload
                            if isinstance(tail_substantive.payload, dict)
                            else {}
                        )
                        err_msg = str(
                            err_payload.get("message")
                            or err_payload.get("code")
                            or "session_error"
                        )
                        self._ontology_service.reconcile_session_lifecycle(
                            session_id,
                            agent_kernel_id="opencode",
                            origin=origin,
                            is_alive=False,
                            observed_error=err_msg,
                        )
                    else:
                        for r in new_records:
                            step_type = self._map_record_to_step_type(r.kind)
                            payload = r.payload if isinstance(r.payload, dict) else {}
                            tool_name = (
                                payload.get("tool_name") if isinstance(payload, dict) else None
                            )
                            self._ontology_service.record_session_step(
                                session_id=session_id,
                                step_type=step_type,
                                payload_dict=payload,
                                tool_name=tool_name,
                            )
                except Exception:
                    logger.exception(
                        "OpencodeStream failed to record ontology steps for session %s",
                        session_id,
                    )

        turn = latest_turn(session_id)
        done = turn.done if turn is not None else False
        prev_done = self._session_done.get(session_id, False)

        # 第一趟连"这一轮说完了没有"也只是对齐，不当成刚刚翻面：页面刚打开一场早就答完
        # 的老会话，不该收到一条"刚刚答完"的通知，那会让它白白热十五分钟。
        if first_sight:
            self._session_done[session_id] = done
            return

        if done and not prev_done:
            self._session_done[session_id] = True
            if self._ontology_service is not None:
                try:
                    from frago.session.service import TERMINAL_STATES

                    cur_rec = self._ontology_service.ensure_managed_session(
                        session_id=session_id,
                        agent_kernel_id="opencode",
                        origin=self._observed_origin(session_id),
                    )
                    if getattr(cur_rec, "lifecycle_state", None) not in TERMINAL_STATES:
                        self._ontology_service.yield_awaiting_input(
                            session_id=session_id,
                            waiting_reason="end_turn",
                        )
                except Exception:
                    logger.exception(
                        "OpencodeStream failed to transition ontology awaiting_input for session %s",
                        session_id,
                    )
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
