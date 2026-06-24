"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

PA service reads from board.view_for_pa and dispatches PA decisions via
DecisionApplier / ExecutionApplier / ResumeApplier / Ingestor. The single
persistence layer is board.timeline.jsonl (spec 20260512 v1.2 freeze:
TaskStore + ingested_tasks.json are gone).

Key design properties:
- Logically immortal: scheduling continuity across server restarts
- Physically bounded: session rotation prevents context O(n²) growth
- Heartbeat layered: code-level checks first (0 token), LLM only when needed
- Execution isolated: sub-agent work happens in Run containers, never in PA session
"""

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.pa_prompts import (
    PA_AGENT_COMPLETED_TEMPLATE,
    PA_AGENT_FAILED_TEMPLATE,
    PA_MERGED_MESSAGES_TEMPLATE,
    PA_MESSAGE_TEMPLATE,
    PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE,
    PA_QUEUE_GROUP_LINE_TEMPLATE,
    PA_QUEUE_LAST_STATUS_LINE_TEMPLATE,
    PA_QUEUE_LOGS_SECTION_TEMPLATE,
    PA_QUEUE_OUTPUTS_LINE_TEMPLATE,
    PA_QUEUE_RECIPE_LINE_TEMPLATE,
    PA_QUEUE_RECOVERED_NOTE,
    PA_QUEUE_TIME_HEADER_TEMPLATE,
    PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE,
    PA_RECOVERED_FAILED_TASK_TEMPLATE,
    PA_REPLY_FAILED_TEMPLATE,
    PA_SCHEDULED_TASK_TEMPLATE,
    SUB_AGENT_PROMPT_TEMPLATE,
    USER_PA_ONLINE_RESPAWN_TEMPLATE,
    USER_PA_ONLINE_RESTART_TEMPLATE,
    USER_PA_ONLINE_ROTATION_TEMPLATE,
)
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT as PRIMARY_AGENT_SYSTEM_PROMPT,
)
from frago.server.services.pa_validators import validate_pa_output, validate_queue_message
from frago.server.services.task_lifecycle import TaskLifecycle
from frago.server.services.taskboard import get_board
from frago.server.services.taskboard.decision_applier import DecisionApplier
from frago.server.services.taskboard.resume_applier import ResumeApplier

logger = logging.getLogger(__name__)

FRAGO_HOME = Path.home() / ".frago"
PROJECTS_DIR = FRAGO_HOME / "projects"
CONFIG_FILE = FRAGO_HOME / "config.json"

# Heartbeat defaults (overridable via config.json primary_agent.heartbeat)
HEARTBEAT_DEFAULTS = {
    "enabled": True,
    "interval_seconds": 300,       # 5 minutes
    "initial_delay_seconds": 30,   # wait after server startup
}

# Rotation thresholds
# Turn limit disabled (None): turns alone don't bloat context (each turn is
# already token-counted), so rotation is driven purely by accumulated tokens.
ROTATION_TURN_THRESHOLD = None
# Token window aligned to ~half of Claude's 1M context, leaving ample room
# for system prompt + bootstrap on rebuild.
ROTATION_TOKEN_THRESHOLD = 500000

# Task execution timeout (seconds)
TASK_TIMEOUT_SECONDS = 900

# Resident-tmux session key used when a message has no bound thread (fallback).
# Kept in sync with PaTmuxRunner.FALLBACK_KEY.
PaTmuxRunner_FALLBACK = "__fallback__"


def _render_domain_peek(peek: dict[str, Any] | None) -> str:
    """Render a domain peek payload as compact prior-context for sub-agent bootstrap."""
    if not peek:
        return ""
    lines: list[str] = []
    domain = peek.get("domain") or ""
    lines.append(f"\nDomain 先验摘要 ({domain})")
    sess_count = peek.get("session_count")
    insi_count = peek.get("insight_count")
    last = peek.get("last_accessed")
    if sess_count is not None or insi_count is not None or last:
        lines.append(
            f"  status={peek.get('status')} sessions={sess_count} insights={insi_count} last={last}"
        )

    insights = peek.get("top_insights") or []
    if insights:
        lines.append("  Top insights:")
        for ins in insights:
            payload = (ins.get("payload") or "").replace("\n", " ").strip()
            if len(payload) > 160:
                payload = payload[:157] + "..."
            lines.append(
                f"    - [{ins.get('type')}] (conf={ins.get('confidence')}) {payload}"
            )

    sessions = peek.get("recent_sessions") or []
    if sessions:
        lines.append("  Recent sessions:")
        for s in sessions:
            sid = s.get("session_id") or ""
            head = (s.get("summary_head") or "").replace("\n", " | ")
            if len(head) > 120:
                head = head[:117] + "..."
            lines.append(f"    - {sid} {head}")
    lines.append("")
    return "\n".join(lines) + "\n"


class PrimaryAgentService:
    """Manages the Primary Agent lifecycle: attached session + heartbeat + Run dispatch.

    Singleton — use get_instance() to access.
    """

    _instance: "PrimaryAgentService | None" = None

    def __init__(self) -> None:
        # Per-thread PA sessions (Phase 3: one session per conversation unit)
        self._sessions: dict[str, Any] = {}          # thread_id → AgentSession
        self._session_ids: dict[str, str] = {}       # thread_id → claude session_id
        self._pa_internal_ids: dict[str, str] = {}   # thread_id → internal_id

        # Per-thread rotation counters
        self._total_turns: dict[str, int] = {}
        self._accumulated_tokens: dict[str, int] = {}
        self._rotation_count: dict[str, int] = {}

        # Currently active thread (serial dispatch: one at a time)
        self._current_thread_id: str | None = None

        # Server-level fallback session (schedule_failed etc. with no thread)
        self._fallback_session: Any | None = None
        self._fallback_session_id: str | None = None
        self._fallback_internal_id: str | None = None
        self._fallback_total_turns: int = 0
        self._fallback_accumulated_tokens: int = 0
        self._fallback_rotation_count: int = 0

        # Heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_stop = asyncio.Event()
        self._heartbeat_seq: int = 0

        # State tracking
        self._server_start_time: float = time.monotonic()
        self._busy: bool = False
        self._last_external_message_at: float | None = None

        # JSON parse failure counter
        self._consecutive_json_failures: int = 0

        # Non-blocking PA communication state
        self._pa_output_buffer: str = ""
        self._pa_input_len: int = 0
        self._pa_waiting: bool = False

        # Message queue
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queue_consumer_task: asyncio.Task[None] | None = None

        # Track scheduled_task msg_id → schedule_id for PA result write-back
        self._schedule_msg_map: dict[str, str] = {}

        # Phase 3 (tmux 后端): 常驻会话执行器，按 thread_id 复用 tmux claude TUI。
        # 仅 backend=="tmux" 时使用；claude-p 路径不碰它。懒初始化。
        self._pa_tmux_runner: Any | None = None

        # Task lifecycle coordinator
        self._lifecycle = TaskLifecycle()

        # Executor
        self._executor: Any = None

        # Ingestion scheduler reference
        self._scheduler: Any = None

        # Recipe scheduler reference
        self._scheduler_service: Any = None

    def set_ingestion_scheduler(self, scheduler: Any) -> None:
        """Register ingestion scheduler for message cache access."""
        self._scheduler = scheduler

    def set_scheduler_service(self, scheduler: Any) -> None:
        """Register recipe scheduler for result write-back."""
        self._scheduler_service = scheduler

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- lifecycle --

    async def initialize(self) -> None:
        """Initialize PA: start queue consumer, executor and heartbeat.

        Per-thread PA sessions are created on demand when messages arrive
        (Phase 3: no single default session at startup).
        """
        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())

        from frago.server.services.executor import Executor
        self._executor = Executor(
            board=get_board(),
            pa_enqueue_message=self.enqueue_message,
            broadcast_pa_event=self._broadcast_pa_event,
        )
        self._executor.start()

        await self._start_heartbeat()
        await self._start_reflection_tick()

        # Phase 3: recover pending work by inspecting the board view.
        await self._recover_pending_tasks()

    async def _recover_pending_tasks(self) -> int:
        """Phase 3: re-enqueue board msgs/tasks that are still in non-terminal states.

        Reads board.view_for_pa() and finds:
        - msgs with status ∈ {awaiting_decision, dispatched} that have no replied task
        - tasks with status ∈ {queued, executing, resume_failed} that need PA attention

        Returns the number of items recovered into the PA message queue.

        TaskLifecycle.recover_pending_tasks still backs the rich field hydration
        (reply_context / channel_message_id) until Phase 4 removes the store.
        """
        try:
            messages = self._lifecycle.recover_pending_tasks()
            if not messages:
                return 0
            for msg in messages:
                await self.enqueue_message(msg)
            logger.info("Recovered %d pending tasks into PA message queue", len(messages))
            return len(messages)
        except Exception:
            logger.debug("Failed to recover pending tasks", exc_info=True)
            return 0

    async def stop(self) -> None:
        """Stop executor, queue consumer, heartbeat, and all PA sessions."""
        if self._executor:
            await self._executor.stop()

        if self._queue_consumer_task and not self._queue_consumer_task.done():
            self._queue_consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_consumer_task
            self._queue_consumer_task = None

        await self._stop_heartbeat()
        await self._stop_reflection_tick()
        for tid, sess in list(self._sessions.items()):
            try:
                await sess.stop()
            except Exception:
                logger.debug("PA session stop error for thread %s", tid, exc_info=True)
        self._sessions.clear()
        if self._fallback_session:
            try:
                await self._fallback_session.stop()
            except Exception:
                logger.debug("Fallback session stop error", exc_info=True)
            self._fallback_session = None
        if self._pa_tmux_runner is not None:
            try:
                self._pa_tmux_runner.shutdown()
            except Exception:
                logger.debug("PA tmux runner shutdown error", exc_info=True)
            self._pa_tmux_runner = None

    def get_session_id(self, thread_id: str | None = None) -> str | None:
        """Get the Claude session_id for a given thread (or current, or fallback).

        Phase 3: sessions are per-thread. ``thread_id=None`` returns the
        currently active thread's session_id (or fallback if no active thread).
        """
        tid = thread_id or self._current_thread_id
        if tid:
            return self._session_ids.get(tid)
        return self._fallback_session_id

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def record_external_message(self) -> None:
        self._last_external_message_at = time.monotonic()

    # -- PA session management --

    async def _create_pa_session(self, *, thread_id: str | None = None, reason: str = "unknown") -> str:
        """Create a new attached PA session with bootstrap context.

        ``thread_id``: the conversation unit this session serves. When None,
        the session is a fallback (server-level, no specific thread).

        Returns the internal_id for the new session.
        """
        from frago.server.services.agent_service import AgentService

        is_fallback = thread_id is None
        tag = f"thread={thread_id}" if thread_id else "fallback"

        logger.info("PA session creating (reason=%s, %s, seq=%d)", reason, tag, self._heartbeat_seq)

        _, reborn_reason = self._build_bootstrap_prompt(thread_id=thread_id, create_reason=reason)

        def _pa_prefix_provider() -> str:
            latest_bootstrap, _ = self._build_bootstrap_prompt(thread_id=thread_id, create_reason="message_dispatch")
            return PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + latest_bootstrap

        result = await AgentService.start_task_attached(
            prompt="",
            project_path=str(Path.home()),
            prefix_provider=_pa_prefix_provider,
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                f"Failed to create PA session ({tag}): {result.get('error')}"
            )

        internal_id = result["internal_id"]
        session = AgentService._attached_sessions.get(internal_id)

        if session:
            session._on_assistant_message = self._on_pa_message

        session_id = await self._wait_for_session_id(internal_id)

        if is_fallback:
            self._fallback_session = session
            self._fallback_session_id = session_id
            self._fallback_internal_id = internal_id
        else:
            self._sessions[thread_id] = session
            self._session_ids[thread_id] = session_id
            self._pa_internal_ids[thread_id] = internal_id
            get_board().bind_pa_session(thread_id, session_id, by="pa")

        logger.info("PA session created: %s (%s)", session_id, tag)

        # Online notification ("PA 回来了") is a server-level event, not a
        # per-conversation one. Only the fallback (server-level) session emits it.
        # Per-thread external sessions must NOT: a conversation unit's first
        # session gets reborn_reason heuristically tagged "server_restart" (history
        # exists), which would otherwise spam "PA 已重新上线" on every new thread —
        # i.e. on every inbound user message to a fresh conversation.
        #
        # Default OFF: rotation/respawn/server_restart are internal self-healing
        # events with no information value for the user, so the auto-broadcast is
        # suppressed unless explicitly enabled via
        # config.json -> primary_agent.reborn_notification.enabled = true.
        # This only gates the reborn broadcast; real user-facing replies
        # (reply / agent_completed) go through other paths and are unaffected.
        if (
            is_fallback
            and reborn_reason in ("rotation", "server_restart", "respawn")
            and self._reborn_notification_enabled()
        ):
            asyncio.create_task(self._send_online_notification(reborn_reason))

        return internal_id

    async def rotate_session(self, thread_id: str | None = None) -> None:
        """Create a new session for a thread, rebuild from external state.

        ``thread_id=None`` rotates the fallback session.
        """
        # Backend dispatch: the tmux backend has no subprocess to stop — rotation
        # evicts the resident session instead of tearing down an AgentSession.
        # This keeps _handle_pa_output's internal rotation call correct for tmux.
        from frago.server.services.agent_service import resolve_backend
        if resolve_backend() == "tmux":
            await self._rotate_tmux_session(thread_id)
            return

        is_fallback = thread_id is None
        tag = f"thread={thread_id}" if thread_id else "fallback"

        if is_fallback:
            turns = self._fallback_total_turns
            tokens = self._fallback_accumulated_tokens
            count = self._fallback_rotation_count
        else:
            turns = self._total_turns.get(thread_id, 0)
            tokens = self._accumulated_tokens.get(thread_id, 0)
            count = self._rotation_count.get(thread_id, 0)

        logger.info(
            "PA session rotation (%s, turns=%d, tokens=%d, rotation_count=%d)",
            tag, turns, tokens, count,
        )

        if is_fallback:
            if self._fallback_session:
                try:
                    await self._fallback_session.stop()
                except Exception:
                    logger.debug("Old fallback session stop error", exc_info=True)
                self._fallback_session = None
            if self._fallback_internal_id:
                from frago.server.services.agent_service import AgentService
                AgentService._attached_sessions.pop(self._fallback_internal_id, None)
            self._fallback_internal_id = None
            self._fallback_session_id = None
        else:
            old_sess = self._sessions.pop(thread_id, None)
            if old_sess:
                try:
                    await old_sess.stop()
                except Exception:
                    logger.debug("Old PA session stop error for thread %s", thread_id, exc_info=True)
            old_internal = self._pa_internal_ids.pop(thread_id, None)
            if old_internal:
                from frago.server.services.agent_service import AgentService
                AgentService._attached_sessions.pop(old_internal, None)
            self._session_ids.pop(thread_id, None)

        await self._create_pa_session(thread_id=thread_id, reason="rotation")

        if is_fallback:
            self._fallback_total_turns = 0
            self._fallback_accumulated_tokens = 0
            self._fallback_rotation_count = count + 1
        else:
            self._total_turns[thread_id] = 0
            self._accumulated_tokens[thread_id] = 0
            self._rotation_count[thread_id] = count + 1

        self._consecutive_json_failures = 0

    # -- Phase 3: per-thread session routing --

    async def _session_for(self, thread_id: str | None) -> Any | None:
        """Get or create a PA session for ``thread_id``.

        ``thread_id=None`` returns/creates the fallback session.
        Returns the AgentSession (or None on failure).
        """
        if thread_id is None:
            if self._fallback_session and self._fallback_session.is_running:
                return self._fallback_session
            try:
                await self._create_pa_session(thread_id=None, reason="route")
            except Exception:
                logger.exception("Failed to create fallback PA session")
                return None
            return self._fallback_session

        sess = self._sessions.get(thread_id)
        if sess and sess.is_running:
            return sess

        try:
            await self._create_pa_session(thread_id=thread_id, reason="route")
        except Exception:
            logger.exception("Failed to create PA session for thread %s", thread_id)
            return None
        return self._sessions.get(thread_id)

    @staticmethod
    def _resolve_thread_id(msg: dict) -> str | None:
        """Resolve which dedicated session a queue message routes to.

        Spec §不做什么 4: only ``origin=external`` threads bind a dedicated
        session. internal (reflection) / scheduled messages — and any thread_id
        not backed by a live board thread — route to the fallback session
        (return None). reflection intentionally creates no board thread, so
        binding its thread_id would crash _create_pa_session via board
        IllegalTransitionError(thread missing); fallback avoids that.
        """
        board = get_board()
        tid = msg.get("thread_id")
        if not tid:
            task_id = msg.get("task_id")
            if task_id:
                t = board.get_thread_for_task(task_id)
                if t:
                    tid = t.thread_id
        if not tid:
            msg_id = msg.get("msg_id")
            if msg_id:
                tid = board.thread_id_of_msg(msg_id)

        if tid:
            t = board.get_thread(tid)
            if t and t.get("origin") == "external":
                return tid
        return None

    @staticmethod
    def _set_msg_thread_id(msg: dict, thread_id: str | None) -> None:
        """Backfill thread_id on msg dict for downstream tracing."""
        if thread_id is not None:
            msg["thread_id"] = thread_id

    def _build_bootstrap_prompt(self, thread_id: str | None = None, create_reason: str | None = None) -> tuple[str, str]:
        """Build bootstrap context (board view + conversation history + knowledge).

        ``thread_id`` optional: when set, board view is filtered to that thread only
        (Phase 3 per-conversation routing). Default None = full view for fallback.
        """
        from frago.server.services.pa_context_builder import build_bootstrap

        return build_bootstrap(self._rotation_count.get(thread_id, 0) if thread_id else self._fallback_rotation_count, create_reason=create_reason, thread_id=thread_id)

    def _reborn_notification_enabled(self) -> bool:
        """Whether the PA reborn/restart auto-notification should be broadcast.

        Defaults to False: session rotation / subprocess respawn / server
        restart are internal self-healing events that carry no information for
        the user, so the "PA 已重新上线" broadcast is silenced by default. Opt in
        via config.json -> primary_agent.reborn_notification.enabled = true.
        """
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                cfg = (raw.get("primary_agent") or {}).get("reborn_notification") or {}
                return bool(cfg.get("enabled", False))
        except (json.JSONDecodeError, OSError):
            pass
        return False

    async def _send_online_notification(self, reborn_reason: str) -> None:
        """Send online notification to the most recently active channel.

        Phase 3: looks up reply_context via board (channel→latest msg). If board
        has the msg the routing info comes from the cached source on PA side.
        """
        try:
            from frago.server.services.trace import get_last_active_channel

            channel = get_last_active_channel()
            if not channel:
                logger.debug("No active channel found, skipping online notification")
                return

            if reborn_reason == "rotation":
                text = USER_PA_ONLINE_ROTATION_TEMPLATE
            elif reborn_reason == "respawn":
                text = USER_PA_ONLINE_RESPAWN_TEMPLATE
            else:
                text = USER_PA_ONLINE_RESTART_TEMPLATE

            reply_params: dict[str, Any] = {"text": text}
            reply_context = self._lookup_recent_reply_context(channel)
            if reply_context:
                reply_params["reply_context"] = reply_context
            else:
                logger.info(
                    "Skipping online notification to %s: no recent task with reply_context",
                    channel,
                )
                return

            self._lifecycle.reply(
                task_id="",
                channel=channel,
                reply_params=reply_params,
            )
            logger.info("Online notification sent to %s", channel)
        except Exception:
            logger.warning("Failed to send online notification", exc_info=True)

    def _lookup_recent_reply_context(self, channel: str) -> dict | None:
        """Look up the most recent reply_context for ``channel`` from board.

        Phase finish: view_for_pa now exposes msg.reply_context directly,
        so this reads board only — no scheduler cache lookup.
        """
        try:
            view = get_board().view_for_pa()
            latest_ctx: dict | None = None
            for t in view.get("threads", []):
                if t.get("subkind") != channel:
                    continue
                for m in t.get("msgs", []):
                    ctx = m.get("reply_context")
                    if ctx:
                        latest_ctx = ctx
            return latest_ctx
        except Exception:
            logger.debug("reply_context board lookup failed", exc_info=True)
            return None

    # -- PA event broadcast --

    async def _broadcast_pa_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a humanized timeline event to all connected WebSocket clients."""
        try:
            from frago.server.services.timeline_service import humanize_event
            from frago.server.websocket import MessageType, manager
            humanized = humanize_event(event_type, data)
            ts = datetime.now().isoformat()
            await manager.broadcast({
                "type": MessageType.TIMELINE_EVENT,
                "timestamp": ts,
                "event": {
                    "id": f"pa-{event_type}-{ts}",
                    "timestamp": ts,
                    **humanized,
                    "task_id": data.get("task_id", ""),
                    "msg_id": data.get("msg_id", ""),
                    "run_id": data.get("run_id"),
                    "raw_data": data,
                },
            })
        except Exception as e:
            logger.debug("Failed to broadcast PA event %s: %s", event_type, e)

    # -- message queue --

    async def enqueue_message(self, msg: dict[str, Any]) -> None:
        """Enqueue a message for PA consumption."""
        result = validate_queue_message(msg)
        if not result.ok:
            logger.warning("Rejected invalid queue message: %s (msg: %s)", result.error, msg)
            return
        await self._message_queue.put(msg)
        logger.debug("Message enqueued: type=%s", msg.get("type", "unknown"))

        if msg.get("type") == "user_message":
            await self._broadcast_pa_event("pa_ingestion", {
                "task_id": msg.get("task_id", ""),
                "msg_id": msg.get("channel_message_id", msg.get("msg_id", "")),
                "channel": msg.get("channel", ""),
                "prompt": msg.get("prompt", ""),
            })

    async def _queue_consumer_loop(self) -> None:
        """Consumer loop: drain queue, resolve thread_id, group by thread, route per session (serial)."""
        logger.info("PA queue consumer started (Phase 3: per-thread routing)")
        while True:
            try:
                first = await self._message_queue.get()
                await asyncio.sleep(0.1)

                messages = [first]
                while not self._message_queue.empty():
                    try:
                        messages.append(self._message_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Phase 3: resolve thread_id for each message, group by thread
                from collections import defaultdict
                grouped: dict[str | None, list[dict]] = defaultdict(list)
                for m in messages:
                    tid = self._resolve_thread_id(m)
                    self._set_msg_thread_id(m, tid)
                    grouped[tid].append(m)

                # Phase 3: choose execution backend once per drain cycle.
                from frago.server.services.agent_service import resolve_backend
                backend = resolve_backend()

                # Serial dispatch: process each group one at a time
                for tid, group in grouped.items():
                    self._current_thread_id = tid

                    # backend=="tmux": resident tmux claude TUI, synchronous turn.
                    # The claude-p path below is left exactly as-is for fallback.
                    if backend == "tmux":
                        await self._dispatch_group_tmux(tid, group)
                        continue

                    session = await self._session_for(tid)
                    if not session:
                        logger.error("No PA session available for thread=%s, dropping %d message(s)", tid, len(group))
                        continue

                    # Wait for session to be ready (no concurrent processing)
                    _wait_start = asyncio.get_event_loop().time()
                    while session.is_running:
                        if asyncio.get_event_loop().time() - _wait_start > 120:
                            logger.warning(
                                "Queue consumer: timed out waiting for PA subprocess "
                                "(is_running stuck, thread=%s), forcing rotation", tid,
                            )
                            await self.rotate_session(thread_id=tid)
                            for m in group:
                                await self._message_queue.put(m)
                            logger.info(
                                "Queue consumer: re-enqueued %d message(s) after timeout rotation",
                                len(group),
                            )
                            break
                        await asyncio.sleep(0.5)
                    else:
                        # Only process if we didn't break out of the timeout loop
                        from frago.server.services.trace import trace_entry
                        for _m in group:
                            if not isinstance(_m, dict):
                                continue
                            _tid = _m.get("thread_id")
                            _mtype = _m.get("type", "")
                            _channel = _m.get("channel", "") or _mtype
                            trace_entry(
                                origin="internal",
                                subkind="pa",
                                data_type="message",
                                thread_id=_tid,
                                parent_id=None,
                                task_id=_m.get("task_id"),
                                data={"queue_msg_type": _mtype, "channel": _m.get("channel")},
                                msg_id=_m.get("msg_id"),
                                role="pa",
                                event=f"收到消息队列: {_channel}",
                            )

                        merged = self._format_queue_messages(group)
                        logger.info(
                            "Queue consumer: sending %d merged messages to PA (thread=%s, %d chars)",
                            len(group), tid, len(merged),
                        )
                        await self._send_to_pa(merged)

                        while self._pa_waiting:
                            sess = self._current_session()
                            if sess and not sess.is_running:
                                break
                            await asyncio.sleep(0.5)

                        if self._pa_waiting:
                            self._pa_waiting = False
                            if tid:
                                self._total_turns[tid] = self._total_turns.get(tid, 0) + 1
                                estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
                                self._accumulated_tokens[tid] = self._accumulated_tokens.get(tid, 0) + estimated_tokens
                            else:
                                self._fallback_total_turns += 1
                                self._fallback_accumulated_tokens += (self._pa_input_len + len(self._pa_output_buffer)) // 4
                            if self._pa_output_buffer.strip():
                                logger.info("Queue consumer: processing PA response (%d chars, thread=%s)", len(self._pa_output_buffer), tid)
                                await self._handle_pa_output(self._pa_output_buffer.strip())
                            else:
                                logger.warning("Queue consumer: PA produced no output (thread=%s)", tid)
                                for m in group:
                                    await self._message_queue.put(m)
                                logger.info(
                                    "Queue consumer: re-enqueued %d message(s) after PA no-output",
                                    len(group),
                                )
                            self._pa_output_buffer = ""

                self._current_thread_id = None

            except asyncio.CancelledError:
                logger.info("PA queue consumer cancelled")
                raise
            except Exception:
                logger.exception("Queue consumer error")
                await asyncio.sleep(1)

    def _format_queue_messages(self, messages: list[dict[str, Any]]) -> str:
        """Format a batch of queued messages into a single text block for PA."""
        now = datetime.now()
        msg_parts: list[str] = []
        msg_parts.append(PA_QUEUE_TIME_HEADER_TEMPLATE.format(
            current_time=now.strftime("%Y-%m-%d %H:%M:%S"),
        ))

        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_parts.append("")

            if msg_type == "user_message":
                recovered_note = PA_QUEUE_RECOVERED_NOTE if msg.get("_recovered") else ""
                channel_name = msg.get("channel", "?")
                reply_ctx = msg.get("reply_context") or {}
                chat_name = reply_ctx.get("chat_name")
                group_line = (
                    PA_QUEUE_GROUP_LINE_TEMPLATE.format(chat_name=chat_name)
                    if chat_name else ""
                )

                msg_parts.append(PA_MESSAGE_TEMPLATE.format(
                    channel=channel_name,
                    channel_message_id=msg.get("channel_message_id", msg.get("msg_id", "?")),
                    prompt=msg.get("prompt", ""),
                    group_line=group_line,
                    received_at=msg.get("received_at") or "unknown",
                ) + recovered_note)

            elif msg_type == "agent_completed":
                outputs = msg.get("output_files", [])
                outputs_section = (
                    PA_QUEUE_OUTPUTS_LINE_TEMPLATE.format(outputs_list=", ".join(outputs))
                    if outputs else ""
                )
                logs_section = self._format_logs_section(msg.get("recent_logs", []))

                msg_parts.append(PA_AGENT_COMPLETED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    outputs_section=outputs_section,
                    recent_logs_section=logs_section,
                    event_at=msg.get("event_at") or "unknown",
                ))

            elif msg_type == "agent_failed":
                logs_section = self._format_logs_section(msg.get("recent_logs", []))

                msg_parts.append(PA_AGENT_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    recent_logs_section=logs_section,
                    event_at=msg.get("event_at") or "unknown",
                ))

            elif msg_type == "scheduled_task":
                recipe = msg.get("recipe")
                recipe_line = (
                    PA_QUEUE_RECIPE_LINE_TEMPLATE.format(recipe=recipe)
                    if recipe else ""
                )
                last_status = msg.get("last_status")
                last_status_line = (
                    PA_QUEUE_LAST_STATUS_LINE_TEMPLATE.format(last_status=last_status)
                    if last_status else ""
                )
                msg_channel = msg.get("channel", "schedule")
                msg_parts.append(PA_SCHEDULED_TASK_TEMPLATE.format(
                    msg_id=msg.get("msg_id", "?"),
                    channel=msg_channel,
                    schedule_id=msg.get("schedule_id", "?"),
                    schedule_name=msg.get("schedule_name", "?"),
                    prompt=msg.get("prompt", ""),
                    recipe_line=recipe_line,
                    last_status_line=last_status_line,
                    run_count=msg.get("run_count", 0),
                    fired_at=msg.get("triggered_at") or "unknown",
                ))
                # Phase finish: scheduled_task reply_context is now carried inline on
                # board.Source (ingest_scheduled writes it through Ingestor) and on the
                # queue dict above. No separate cache_message shim needed.
                if msg.get("msg_id") and msg.get("schedule_id"):
                    self._schedule_msg_map[msg["msg_id"]] = msg["schedule_id"]

            elif msg_type in ("reply_failed", "task_failed"):
                if msg.get("content"):
                    msg_parts.append(msg["content"])
                else:
                    msg_parts.append(PA_REPLY_FAILED_TEMPLATE.format(
                        task_id=msg.get("task_id", "?"),
                        channel=msg.get("channel", "?"),
                        error=msg.get("error", "unknown"),
                        reply_text=msg.get("reply_text", msg.get("original_text", "")),
                    ))

            elif msg_type == "recovered_failed_task":
                msg_parts.append(PA_RECOVERED_FAILED_TASK_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    original_error=msg.get("original_error", "unknown"),
                    original_prompt=msg.get("original_prompt", ""),
                ))

            elif msg_type == "internal_reflection":
                from frago.server.services.pa_prompts import (
                    PA_INTERNAL_REFLECTION_TEMPLATE,
                )
                msg_parts.append(PA_INTERNAL_REFLECTION_TEMPLATE.format(
                    thread_id=msg.get("thread_id", "?"),
                    ts=msg.get("ts", ""),
                    reason=msg.get("reason", "scheduled"),
                    prompt_hint=msg.get("prompt_hint", ""),
                ))

            elif msg_type == "resume_failed":
                from frago.server.services.pa_prompts import (
                    PA_RESUME_FAILED_TEMPLATE,
                )
                msg_parts.append(PA_RESUME_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    reason=msg.get("reason", "unknown"),
                    detail=msg.get("detail", "") or f"(original prompt: {msg.get('original_prompt', '')[:200]})",
                ))

            elif msg_type == "run_failed":
                from frago.server.services.pa_prompts import (
                    PA_RUN_FAILED_TEMPLATE,
                )
                msg_parts.append(PA_RUN_FAILED_TEMPLATE.format(
                    msg_id=msg.get("msg_id", "-") or "-",
                    task_id=msg.get("task_id", "-") or "-",
                    reason=msg.get("reason", "unknown"),
                    detail=msg.get("detail", ""),
                ))

            else:
                msg_parts.append(PA_QUEUE_UNKNOWN_FALLBACK_TEMPLATE.format(
                    msg_type=msg_type,
                    msg_json=json.dumps(msg, ensure_ascii=False, default=str),
                ))

        return PA_MERGED_MESSAGES_TEMPLATE.format(
            count=len(messages),
            messages_body="\n".join(msg_parts),
        )

    @staticmethod
    def _format_logs_section(recent_logs: list[str]) -> str:
        """Format recent log lines into PA_QUEUE_LOGS_SECTION_TEMPLATE body."""
        if not recent_logs:
            return ""
        body = "\n".join(f"  {line}" for line in recent_logs)
        return PA_QUEUE_LOGS_SECTION_TEMPLATE.format(logs_body=body)

    # -- heartbeat --

    def _load_heartbeat_config(self) -> dict[str, Any]:
        """Load heartbeat config from config.json."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                user_config = (raw.get("primary_agent") or {}).get("heartbeat") or {}
                return {**HEARTBEAT_DEFAULTS, **user_config}
        except (json.JSONDecodeError, OSError):
            pass
        return dict(HEARTBEAT_DEFAULTS)

    async def _start_heartbeat(self) -> None:
        config = self._load_heartbeat_config()
        if not config.get("enabled", True):
            logger.info("PA heartbeat disabled by config")
            return

        self._heartbeat_stop.clear()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(
                interval=config["interval_seconds"],
                initial_delay=config["initial_delay_seconds"],
            )
        )
        logger.info("PA heartbeat started (interval=%ds)", config["interval_seconds"])

    async def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            return
        self._heartbeat_stop.set()
        self._heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat_task
        self._heartbeat_task = None
        logger.info("PA heartbeat stopped")

    async def _start_reflection_tick(self) -> None:
        from frago.server.services.reflection_tick import (
            ReflectionTicker,
            load_reflection_config,
        )

        config = load_reflection_config()
        if not config.get("enabled", True):
            logger.info("Reflection tick disabled by config")
            self._reflection_ticker = None
            return

        self._reflection_ticker = ReflectionTicker(
            enqueue=self.enqueue_message,
            interval_min=int(config["interval_min"]),
            initial_delay_sec=int(config["initial_delay_sec"]),
            prompt_hint=str(config["prompt_hint"]),
        )
        await self._reflection_ticker.start()

    async def _stop_reflection_tick(self) -> None:
        ticker = getattr(self, "_reflection_ticker", None)
        if ticker is not None:
            await ticker.stop()
            self._reflection_ticker = None

    async def _heartbeat_loop(self, interval: int, initial_delay: int) -> None:
        logger.info("Heartbeat loop: waiting %ds initial delay", initial_delay)
        await asyncio.sleep(initial_delay)
        logger.info("Heartbeat loop: starting main loop")
        while not self._heartbeat_stop.is_set():
            try:
                await self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat failed")
            try:
                await asyncio.wait_for(
                    self._heartbeat_stop.wait(), timeout=interval
                )
                break
            except TimeoutError:
                continue

    async def _send_heartbeat(self) -> None:
        """Heartbeat: idle detection + environment awareness + output collection.

        Phase 3: iterates over all per-thread sessions, checks rotation per-thread.
        """
        logger.info("Heartbeat [%d]: tick (waiting=%s)", self._heartbeat_seq, self._pa_waiting)

        if self._queue_consumer_task is None or self._queue_consumer_task.done():
            if self._queue_consumer_task and self._queue_consumer_task.done():
                exc = self._queue_consumer_task.exception() if not self._queue_consumer_task.cancelled() else None
                logger.error(
                    "Queue consumer task died (exc=%s), restarting",
                    exc,
                )
            self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())
            logger.info("Queue consumer task restarted by heartbeat [%d]", self._heartbeat_seq)

        if self._busy:
            logger.debug("Heartbeat skipped: PA is busy")
            return

        if self._pa_waiting:
            sess = self._current_session()
            if sess and sess.is_running:
                logger.debug("Heartbeat [%d]: PA still processing, skip", self._heartbeat_seq)
                return
            self._pa_waiting = False
            tid = self._current_thread_id
            if tid:
                self._total_turns[tid] = self._total_turns.get(tid, 0) + 1
                estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
                self._accumulated_tokens[tid] = self._accumulated_tokens.get(tid, 0) + estimated_tokens
            else:
                self._fallback_total_turns += 1
                self._fallback_accumulated_tokens += (self._pa_input_len + len(self._pa_output_buffer)) // 4
            if self._pa_output_buffer.strip():
                logger.info("Heartbeat [%d]: processing PA response (%d chars)", self._heartbeat_seq, len(self._pa_output_buffer))
                await self._handle_pa_output(self._pa_output_buffer.strip())
            self._pa_output_buffer = ""

        # Per-thread rotation check: iterate all sessions
        for tid in list(self._sessions.keys()):
            if self._should_rotate(tid):
                await self.rotate_session(thread_id=tid)
        if self._should_rotate(None):
            await self.rotate_session(thread_id=None)

        # Ensure at least one session exists if there are pending tasks
        all_sessions = bool(self._sessions) or bool(self._fallback_session)
        if not all_sessions:
            recovered = await self._recover_pending_tasks()
            if recovered:
                logger.info(
                    "Heartbeat [%d]: recovered %d pending tasks, sessions will be created on demand",
                    self._heartbeat_seq, recovered,
                )

        if not self._pa_waiting and self._message_queue.empty():
            recovered = await self._recover_pending_tasks()
            if recovered:
                logger.info(
                    "Heartbeat [%d]: recovered %d pending tasks",
                    self._heartbeat_seq, recovered,
                )

        if self._executor and (self._executor._loop_task is None or self._executor._loop_task.done()):
            logger.warning("Heartbeat [%d]: executor loop died, restarting", self._heartbeat_seq)
            self._executor.start()

        self._heartbeat_seq += 1

    def _cleanup_terminal_tasks(self) -> None:
        """Phase 3: terminal task archival is board-side (vacuum + thread_archived markers).
        This helper now just logs the board's terminal task census for trace purposes.
        Phase 4 will fully retire this method when ingestion.store is deleted.
        """
        try:
            board = get_board()
            view = board.view_for_pa()
            terminal = sum(
                1 for t in view.get("threads", []) for m in t.get("msgs", [])
                for tk in m.get("tasks", [])
                if tk.get("status") in {"completed", "failed", "replied"}
            )
            if terminal:
                logger.debug(
                    "Heartbeat [%d]: board has %d terminal task(s)",
                    self._heartbeat_seq, terminal,
                )
        except Exception:
            logger.debug("Failed to read board terminal count", exc_info=True)

    def _on_pa_message(self, text: str) -> None:
        """Callback invoked by AgentSession when PA produces a complete text block."""
        self._pa_output_buffer += text

    async def _send_to_pa(self, message: str) -> None:
        """Send message to PA via current thread's attached session. Non-blocking."""
        session = self._current_session()
        if not session:
            logger.warning("Cannot send to PA: no session")
            return

        self._pa_output_buffer = ""
        self._pa_input_len = len(message)

        try:
            await session.send_message(message)
            self._pa_waiting = True
            logger.info("Heartbeat [%d]: sent message to PA (%d chars)", self._heartbeat_seq, len(message))
        except RuntimeError as e:
            logger.error("Failed to send to PA: %s", e)
            tid = self._current_thread_id
            self._current_thread_id = None
            await self.rotate_session(thread_id=tid)

    def _current_session(self) -> Any | None:
        """Get the currently active PA session."""
        if self._current_thread_id:
            return self._sessions.get(self._current_thread_id)
        return self._fallback_session

    async def _send_and_wait_pa(self, message: str, timeout: float = 60.0) -> str | None:
        """Send message to PA via current session and wait for response."""
        await self._send_to_pa(message)

        deadline = asyncio.get_event_loop().time() + timeout
        while self._pa_waiting:
            sess = self._current_session()
            if sess and not sess.is_running:
                break
            if asyncio.get_event_loop().time() > deadline:
                logger.warning("_send_and_wait_pa: timed out after %.0fs", timeout)
                self._pa_waiting = False
                return None
            await asyncio.sleep(0.5)

        if self._pa_waiting:
            self._pa_waiting = False
            tid = self._current_thread_id
            if tid:
                self._total_turns[tid] = self._total_turns.get(tid, 0) + 1
                estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
                self._accumulated_tokens[tid] = self._accumulated_tokens.get(tid, 0) + estimated_tokens
            else:
                self._fallback_total_turns += 1
                self._fallback_accumulated_tokens += (self._pa_input_len + len(self._pa_output_buffer)) // 4
            output = self._pa_output_buffer.strip()
            self._pa_output_buffer = ""
            return output if output else None

        return None

    # -- PA output handling --

    async def _handle_pa_output(self, output_text: str) -> None:
        """Phase 3 (Yi #133): parse PA's JSON output and route via DecisionApplier.

        Single dispatch path: DA.handle_pa_output routes all 4 actions
        (run / reply / resume / dismiss) onto the board (single source of truth).
        ``schedule`` action is intentionally not in the 4-action vocabulary and is
        delegated to the schedule subsystem directly.

        Side effects beyond board state (channel reply push, executor invocation,
        run_failed feedback) are handled by per-action wrappers below.
        """
        result = validate_pa_output(output_text)

        if not result.ok:
            logger.warning("PA output validation failed: %s (raw: %r)", result.error, output_text)
            self._consecutive_json_failures += 1

            if self._consecutive_json_failures >= 2:
                logger.error("2 consecutive validation failures after correction, rotating session")
                await self.rotate_session(thread_id=self._current_thread_id)
                return

            correction_msg = PA_OUTPUT_FORMAT_CORRECTION_TEMPLATE.format(
                error=result.error,
                raw_output=output_text,
            )
            await self._send_to_pa(correction_msg)
            return

        self._consecutive_json_failures = 0
        decisions = result.raw_data

        if not decisions:
            logger.info("PA decision: [] (idle)")
            return

        logger.info("PA decision: %d action(s) → %s", len(decisions), [d.get("action") for d in decisions if isinstance(d, dict)])

        # Phase 3 single-dispatch: 4-action set routed via DecisionApplier.
        board = get_board()
        da_decisions = [
            d for d in decisions
            if isinstance(d, dict) and d.get("action") in {"run", "reply", "resume", "dismiss"}
        ]
        # id(decision) → board outcome ({"ok", "reason", ...}). The board's
        # append result is authoritative for whether a run will actually
        # launch; the per-action loop below consults it instead of blindly
        # reporting "dispatched ok" (which masked rejected runs as success —
        # the sub-agent silently never started, see 2026-05-20 12:22).
        outcome_by_decision: dict[int, dict[str, Any]] = {}
        if da_decisions:
            try:
                outcomes = DecisionApplier(board).handle_pa_output(da_decisions)
                for dec, out in zip(da_decisions, outcomes, strict=True):
                    outcome_by_decision[id(dec)] = out
            except Exception:
                logger.warning("DecisionApplier dispatch error", exc_info=True)

        # Per-action side effects (channel push, executor.execute_resume, feedback).
        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action")
            log_id = d.get("task_id") or d.get("msg_id") or "?"
            _decision_data = {
                "action": action or "",
                "task_id": d.get("task_id", ""),
                "msg_id": d.get("msg_id", ""),
                "details": {k: v for k, v in d.items() if k not in ("action", "task_id", "msg_id")},
            }
            await self._broadcast_pa_event("pa_decision", _decision_data)
            from frago.server.services.trace import trace as _trace
            _desc = d.get("description") or d.get("text", "")
            _trace(d.get("msg_id", ""), d.get("task_id"), "pa",
                   f"决策 {action}: {str(_desc)[:80]}",
                   data={"event_type": "pa_decision", **_decision_data})
            try:
                if action == "reply":
                    logger.info("→ reply (id=%s, channel=%s)", log_id, d.get("channel"))
                    await self._send_reply(d)
                elif action == "run":
                    logger.info("→ run (id=%s, desc=%s)", log_id, d.get("description", ""))
                    out = outcome_by_decision.get(id(d))
                    if out is not None and not out.get("ok", True):
                        await self._enqueue_run(d, board_reason=out.get("reason"))
                    else:
                        await self._enqueue_run(d)
                elif action == "resume":
                    logger.info("→ resume (task=%s)", log_id)
                    await self._handle_resume(d)
                elif action == "dismiss":
                    logger.info("→ dismiss (msg=%s)", log_id)
                    # DA already marked msg dismissed on board; no side effect needed.
                else:
                    logger.warning("Unknown PA action: %s", action)
            except Exception:
                logger.exception("Failed to execute PA decision: %s", d)

        # Phase finish: deferred cache cleanup removed alongside _message_cache shim.

        # Write back schedule results.
        if self._scheduler_service:
            referenced_schedule_msg_ids: set[str] = set()
            for d in decisions:
                if not isinstance(d, dict):
                    continue
                msg_id = d.get("msg_id", "")
                schedule_id = self._schedule_msg_map.get(msg_id)
                if not schedule_id:
                    continue
                referenced_schedule_msg_ids.add(msg_id)
                action = d.get("action", "")
                if action == "run":
                    status = "dispatched"
                elif action == "reply":
                    status = "skipped"
                else:
                    status = action
                task_id = d.get("task_id")
                self._scheduler_service.update_schedule_result(schedule_id, status, task_id)
                self._schedule_msg_map.pop(msg_id, None)

            orphaned = {
                mid: sid for mid, sid in self._schedule_msg_map.items()
                if mid not in referenced_schedule_msg_ids
            }
            for msg_id, schedule_id in orphaned.items():
                logger.warning(
                    "[scheduler] PA did not reference scheduled_task %s (schedule %s) — marking skipped",
                    msg_id, schedule_id,
                )
                self._scheduler_service.update_schedule_result(schedule_id, "skipped")
                self._schedule_msg_map.pop(msg_id, None)

    # -- per-action side-effect wrappers (Phase 3: dispatch goes through DA;
    #    these handle channel push, executor.execute_resume, run_failed feedback) --

    async def _send_reply(self, decision: dict[str, Any]) -> None:
        """PA decided action:'reply' → push to channel.

        DecisionApplier already marked the board task replied; here we still
        need to push the text to the external channel via lifecycle.reply.
        """
        from frago.server.services.trace import trace_entry

        task_id: str = decision.get("task_id", "")
        msg_id: str = decision.get("msg_id", "")
        channel: str = decision.get("channel", "")
        text: str = decision.get("text", "")
        file_path: str = decision.get("file_path", "") or ""
        image_path: str = decision.get("image_path", "") or ""

        if not channel or not text:
            logger.warning("reply decision missing channel or text")
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "reply", "status": "failed",
                      "reason": "missing_channel_or_text",
                      "detail": f"channel={channel!r} text_len={len(text)}"},
                msg_id=msg_id or None,
                event="reply 失败: missing channel or text",
            )
            await self.enqueue_message({
                "type": "reply_failed",
                "task_id": task_id,
                "channel": channel,
                "error": "missing channel or text",
                "original_text": text,
            })
            return

        reply_params: dict[str, Any] = {"text": text}
        if file_path:
            reply_params["file_path"] = file_path
        if image_path:
            reply_params["image_path"] = image_path
        result = await asyncio.to_thread(
            self._lifecycle.reply, task_id, channel, reply_params, msg_id=msg_id,
        )

        if result["status"] == "ok":
            _reply_data = {
                "task_id": task_id or "",
                "msg_id": msg_id or "",
                "channel": channel or "",
                "reply_text": text,
            }
            await self._broadcast_pa_event("pa_reply", _reply_data)
            from frago.server.services.trace import trace as _trace
            _trace(msg_id, task_id, "pa", f"回复 {channel}: {text[:80]}",
                   data={"event_type": "pa_reply", **_reply_data})
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "reply", "status": "ok",
                      "channel": channel, "text_len": len(text),
                      "has_attachment": bool(file_path or image_path)},
                msg_id=msg_id or None,
                event=f"reply 成功: {channel}",
            )
        elif result["status"] == "error":
            error_detail = result.get("error", "unknown")
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "reply", "status": "failed",
                      "reason": "send_failed", "detail": error_detail,
                      "channel": channel},
                msg_id=msg_id or None,
                event=f"reply 失败: {error_detail[:80]}",
            )
            await self.enqueue_message({
                "type": "reply_failed",
                "task_id": task_id,
                "channel": channel,
                "error": error_detail,
                "original_text": text,
            })

    # Board rejection reason → human-readable detail fed back to the PA so it
    # can self-correct (re-dispatch on a clean task, wait, or tell the user)
    # instead of believing a silently-rejected run actually launched.
    _RUN_REJECT_DETAIL = {
        "illegal_transition": (
            "board 拒绝 run：父 msg 已关闭/状态不允许 append（常见于 ack reply 先关了"
            " msg）。子 agent 未启动。请用一条干净的任务（新 msg_id 或既有 task_id）重派。"
        ),
        "duplicate_run_inflight": (
            "board 拒绝 run：该 msg 已有一个 run 在排队/执行中，拒绝重复派发。等它完成"
            "再处理结果，不要重派。"
        ),
        "post_archive_append": (
            "board 拒绝 run：所属 thread 已归档，无法再 append。子 agent 未启动。"
        ),
        "msg_not_found": (
            "board 拒绝 run：找不到该 msg_id，run 无法落盘。子 agent 未启动。"
        ),
        "prompt_format_invalid": (
            "board 拒绝 run：prompt 不符合「首行≤80 摘要 + 空行 + 正文」格式。子 agent 未启动。"
        ),
    }

    async def _enqueue_run(
        self, decision: dict[str, Any], *, board_reason: str | None = None
    ) -> None:
        """PA decided action:'run'.

        DecisionApplier already attempted to append the run task onto the
        board. ``board_reason`` (set by the caller from the board outcome)
        means the append was *rejected* — we surface it as a "run 失败" trace
        plus run_failed feedback so the failure is loud and the PA can
        self-correct, rather than the old blind "dispatched ok" that masked a
        sub-agent that never launched. On success the executor's poll loop
        picks up the queued board task. This wrapper also still catches
        malformed PA decisions (missing prompt / both ids absent).
        """
        from frago.server.services.trace import trace_entry

        task_id = decision.get("task_id", "")
        msg_id = decision.get("msg_id", "")
        description = decision.get("description", "")
        prompt = decision.get("prompt", "")
        channel = decision.get("channel", "")

        async def _fail(reason: str, detail: str) -> None:
            logger.warning("run %s failed: %s — %s", task_id or msg_id or "?", reason, detail)
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=task_id or None,
                data={"action": "run", "status": "failed",
                      "reason": reason, "detail": detail,
                      "decision_msg_id": msg_id, "decision_task_id": task_id,
                      "channel": channel},
                msg_id=msg_id or None,
                event=f"run 失败: {reason}",
            )
            await self.enqueue_message({
                "type": "run_failed",
                "msg_id": msg_id,
                "task_id": task_id,
                "channel": channel,
                "reason": reason,
                "detail": detail,
            })

        if board_reason:
            await _fail(
                board_reason,
                self._RUN_REJECT_DETAIL.get(
                    board_reason, f"board 拒绝 run：{board_reason}。子 agent 未启动。"
                ),
            )
            return

        if not prompt:
            await _fail("missing_prompt", "run 决策未提供 prompt 字段，无法派发任务。")
            return

        if not task_id and not msg_id:
            await _fail(
                "missing_id",
                "run 决策必须提供 msg_id (新消息) 或 task_id (已有任务) 至少一个。",
            )
            return

        trace_entry(
            origin="internal", subkind="pa", data_type="action_result",
            thread_id=None, task_id=task_id or None,
            data={"action": "run", "status": "ok", "description": description[:120]},
            msg_id=msg_id or None,
            event=f"run dispatched (board): task={task_id or msg_id}",
        )

    async def _handle_resume(self, decision: dict[str, Any]) -> None:
        """PA decided action:'resume' → ResumeApplier routes board state;
        executor.execute_resume drives the hot injection into the live Claude
        session. Failures emit resume_failed feedback.
        """
        task_id = decision.get("task_id")
        prompt = decision.get("prompt", "")

        async def _feedback_fail(reason: str, detail: str) -> None:
            await self.enqueue_message({
                "type": "resume_failed",
                "task_id": task_id or "?",
                "reason": reason,
                "detail": detail,
                "original_prompt": prompt or "",
            })

        if not task_id:
            logger.warning("resume decision missing task_id")
            await _feedback_fail("missing_task_id",
                                 "PA 决策未提供 task_id，无法执行 resume。")
            return
        if not prompt:
            logger.warning("resume decision missing prompt")
            await _feedback_fail("missing_prompt",
                                 f"PA 决策未提供 prompt，无法 resume task {task_id}。")
            return

        if not self._executor:
            logger.warning("Executor not available for resume")
            await _feedback_fail("executor_unavailable",
                                 "Executor 未初始化，无法执行 resume。")
            return

        # Board side is handled by DecisionApplier+ResumeApplier; here we drive
        # the actual hot-injection through executor.
        result = await self._executor.execute_resume(task_id, prompt)
        if result.get("status") != "ok":
            await _feedback_fail(
                result.get("reason", "unknown"),
                result.get("detail", ""),
            )

    # -- helpers --

    # -- Phase 3: tmux 常驻后端执行路径 --

    def _get_pa_tmux_runner(self) -> Any:
        """Lazily construct the resident-tmux PA executor (backend=="tmux")."""
        if self._pa_tmux_runner is None:
            from frago.server.services.pa_tmux_runner import PaTmuxRunner

            self._pa_tmux_runner = PaTmuxRunner(cwd=str(Path.home()))
        return self._pa_tmux_runner

    async def _dispatch_group_tmux(self, tid: str | None, group: list[dict]) -> None:
        """Send a message group to PA via the resident tmux session, then route output.

        Synchronous from PA's view: run the resident claude TUI turn (blocking, in a
        thread), get the full answer text, and feed it through the *same* output path
        the claude-p backend uses (``_handle_pa_output`` → ``validate_pa_output`` →
        DecisionApplier). reply/run/resume/dismiss persistence and push are untouched.

        Rotation is token-driven and evicts the resident session (no subprocess to
        kill); on empty output the group is re-enqueued, mirroring the claude-p path.
        """
        from frago.server.services.trace import trace_entry

        for _m in group:
            if not isinstance(_m, dict):
                continue
            _mtype = _m.get("type", "")
            _channel = _m.get("channel", "") or _mtype
            trace_entry(
                origin="internal",
                subkind="pa",
                data_type="message",
                thread_id=_m.get("thread_id"),
                parent_id=None,
                task_id=_m.get("task_id"),
                data={"queue_msg_type": _mtype, "channel": _m.get("channel")},
                msg_id=_m.get("msg_id"),
                role="pa",
                event=f"收到消息队列: {_channel}",
            )

        merged = self._format_queue_messages(group)
        bootstrap, _ = self._build_bootstrap_prompt(
            thread_id=tid, create_reason="message_dispatch"
        )
        full_bootstrap = PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + bootstrap
        session_key = tid or PaTmuxRunner_FALLBACK

        runner = self._get_pa_tmux_runner()
        self._pa_input_len = len(merged)
        logger.info(
            "Queue consumer [tmux]: sending %d merged messages to PA (thread=%s, %d chars)",
            len(group), tid, len(merged),
        )

        try:
            text = await asyncio.to_thread(
                runner.run, session_key, merged, bootstrap=full_bootstrap
            )
        except Exception:
            logger.exception("PA tmux run failed (thread=%s), re-enqueueing group", tid)
            for m in group:
                await self._message_queue.put(m)
            return

        # Token accounting (same estimator as the claude-p path).
        estimated_tokens = (self._pa_input_len + len(text or "")) // 4
        if tid:
            self._total_turns[tid] = self._total_turns.get(tid, 0) + 1
            self._accumulated_tokens[tid] = self._accumulated_tokens.get(tid, 0) + estimated_tokens
        else:
            self._fallback_total_turns += 1
            self._fallback_accumulated_tokens += estimated_tokens

        if text and text.strip():
            logger.info(
                "Queue consumer [tmux]: processing PA response (%d chars, thread=%s)",
                len(text), tid,
            )
            await self._handle_pa_output(text.strip())
        else:
            logger.warning("Queue consumer [tmux]: PA produced no output (thread=%s)", tid)
            for m in group:
                await self._message_queue.put(m)

        # Rotation is token-driven; evict the resident session and reset counters.
        if self._should_rotate(tid):
            await self._rotate_tmux_session(tid)

    async def _rotate_tmux_session(self, thread_id: str | None = None) -> None:
        """Rotate a resident-tmux PA session: evict it and reset that key's counters.

        No subprocess exists in the tmux backend, so this NEVER touches
        ``_sessions`` / ``_create_pa_session`` (the claude-p machinery). The next
        ``run`` for this key re-injects bootstrap on a fresh resident session.
        """
        is_fallback = thread_id is None
        tag = f"thread={thread_id}" if thread_id else "fallback"
        session_key = thread_id or PaTmuxRunner_FALLBACK

        if is_fallback:
            count = self._fallback_rotation_count
        else:
            count = self._rotation_count.get(thread_id, 0)

        logger.info("PA tmux session rotation (%s, rotation_count=%d)", tag, count)

        try:
            self._get_pa_tmux_runner().evict(session_key)
        except Exception:
            logger.debug("PA tmux evict error for %s", tag, exc_info=True)

        if is_fallback:
            self._fallback_total_turns = 0
            self._fallback_accumulated_tokens = 0
            self._fallback_rotation_count = count + 1
        else:
            self._total_turns[thread_id] = 0
            self._accumulated_tokens[thread_id] = 0
            self._rotation_count[thread_id] = count + 1

        self._consecutive_json_failures = 0

    def _should_rotate(self, thread_id: str | None = None) -> bool:
        """Check if session rotation is needed for a given thread.

        ``thread_id=None`` checks fallback session.
        """
        if thread_id is None:
            turns = self._fallback_total_turns
            tokens = self._fallback_accumulated_tokens
        else:
            turns = self._total_turns.get(thread_id, 0)
            tokens = self._accumulated_tokens.get(thread_id, 0)
        if ROTATION_TURN_THRESHOLD is not None and turns >= ROTATION_TURN_THRESHOLD:
            return True
        return tokens >= ROTATION_TOKEN_THRESHOLD

    @staticmethod
    def _build_sub_agent_prompt(
        task_id: str | None,  # noqa: ARG004 reserved for related_runs lookup
        task_prompt: str,
        run_id: str,
        related_runs: list[str] | None = None,
        domain_peek: dict[str, Any] | None = None,
    ) -> str:
        """Build the prompt for a sub-agent working in a Run instance."""
        related_section = ""
        if related_runs:
            lines = ["相关历史 Run（可用 frago run info <run_id> 查看详情）:"]
            for rid in related_runs:
                lines.append(f"  - {rid}")
            related_section = "\n" + "\n".join(lines) + "\n"

        if domain_peek:
            related_section = (
                _render_domain_peek(domain_peek) + related_section
            )

        return SUB_AGENT_PROMPT_TEMPLATE.format(
            task_prompt=task_prompt,
            run_id=run_id,
            related_section=related_section,
        )

    # -- persistence --

    @staticmethod
    def _save_session_id(session_id: str) -> None:
        try:
            raw: dict[str, Any] = {}
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw.get("primary_agent"), dict):
                raw["primary_agent"] = {}
            raw["primary_agent"]["session_id"] = session_id
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.error("Failed to save PA session_id: %s", e)

    @staticmethod
    async def _wait_for_session_id(internal_id: str, timeout: float = 30.0) -> str:
        """Wait for AgentSession to resolve the real Claude session_id."""
        from frago.server.services.agent_service import AgentService

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = AgentService.get_attached_session_info(internal_id)
            if info and info.get("session_id"):
                return str(info["session_id"])
            await asyncio.sleep(0.5)

        raise RuntimeError(
            f"Timed out waiting for Claude session_id (internal_id={internal_id})"
        )

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}秒"
        if seconds < 3600:
            return f"{seconds // 60}分钟"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}小时{minutes}分钟"
        return f"{hours}小时"


# Phase 3 housekeeping: keep ResumeApplier importable from this module so
# legacy unit tests that monkeypatch primary_agent_service.ResumeApplier
# still find the symbol; the actual dispatch happens via DA → board.
_ = ResumeApplier
