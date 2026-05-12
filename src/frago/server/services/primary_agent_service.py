"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

Phase 3 (Yi #133): PA service reads from board.view_for_pa and dispatches
PA decisions via DecisionApplier / ExecutionApplier / ResumeApplier / Ingestor.
The legacy ingestion.store + IngestedTask are kept ONLY for field continuity
that the board doesn't yet expose (reply_context, session_id, claude_session_id,
channel_message_id) — Phase 4 deletes the legacy classes entirely.

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
ROTATION_TURN_THRESHOLD = 30
ROTATION_TOKEN_THRESHOLD = 50000

# Task execution timeout (seconds)
TASK_TIMEOUT_SECONDS = 900


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
            sid = (s.get("session_id") or "")[:8]
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
        self._session_id: str | None = None
        self._pa_session: Any | None = None
        self._pa_internal_id: str | None = None

        # Heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_stop = asyncio.Event()
        self._heartbeat_seq: int = 0

        # State tracking
        self._server_start_time: float = time.monotonic()
        self._busy: bool = False
        self._last_external_message_at: float | None = None

        # Rotation counters
        self._total_turns: int = 0
        self._accumulated_tokens: int = 0
        self._rotation_count: int = 0

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
        """Initialize PA: create attached session, start queue consumer, executor and heartbeat."""
        await self._create_pa_session(reason="initialize")

        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())

        from frago.server.services.executor import Executor
        from frago.server.services.taskboard.legacy_store import TaskStore
        self._executor = Executor(
            store=TaskStore(),
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
        """Stop executor, queue consumer, heartbeat, and PA session."""
        if self._executor:
            await self._executor.stop()

        if self._queue_consumer_task and not self._queue_consumer_task.done():
            self._queue_consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_consumer_task
            self._queue_consumer_task = None

        await self._stop_heartbeat()
        await self._stop_reflection_tick()
        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("PA session stop error", exc_info=True)
            self._pa_session = None

    def get_session_id(self) -> str | None:
        return self._session_id

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def record_external_message(self) -> None:
        self._last_external_message_at = time.monotonic()

    # -- PA session management --

    async def _create_pa_session(self, *, reason: str = "unknown") -> None:
        """Create a new attached PA session with bootstrap context."""
        from frago.server.services.agent_service import AgentService

        logger.info("PA session creating (reason=%s, seq=%d)", reason, self._heartbeat_seq)

        bootstrap, reborn_reason = self._build_bootstrap_prompt(create_reason=reason)
        prompt = PRIMARY_AGENT_SYSTEM_PROMPT + "\n\n" + bootstrap

        result = await AgentService.start_task_attached(
            prompt=prompt,
            project_path=str(Path.home()),
        )
        if result.get("status") != "ok":
            raise RuntimeError(
                f"Failed to create PA session: {result.get('error')}"
            )

        self._pa_internal_id = result["internal_id"]
        self._pa_session = AgentService._attached_sessions.get(self._pa_internal_id)

        if self._pa_session:
            self._pa_session._on_assistant_message = self._on_pa_message

        self._session_id = await self._wait_for_session_id(self._pa_internal_id)
        self._save_session_id(self._session_id)
        logger.info("PA session created: %s", self._session_id[:8])

        if reborn_reason in ("rotation", "server_restart", "respawn"):
            asyncio.create_task(self._send_online_notification(reborn_reason))

    async def rotate_session(self) -> None:
        """Create a new session, rebuild from external state."""
        logger.info(
            "PA session rotation (turns=%d, tokens=%d, rotation_count=%d)",
            self._total_turns, self._accumulated_tokens, self._rotation_count,
        )

        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("Old PA session stop error", exc_info=True)
            self._pa_session = None

        if self._pa_internal_id:
            from frago.server.services.agent_service import AgentService
            AgentService._attached_sessions.pop(self._pa_internal_id, None)

        await self._create_pa_session(reason="rotation")

        self._total_turns = 0
        self._accumulated_tokens = 0
        self._rotation_count += 1
        self._consecutive_json_failures = 0

        # Phase finish: orphan reconciliation removed alongside ingestion._message_cache.
        # Ingestor.ingest_external/ingest_scheduled writes board synchronously, so every
        # ingested message is on board immediately. There is no "cached but not yet on
        # board" intermediate state to reconcile after rotation.

    def _build_bootstrap_prompt(self, create_reason: str | None = None) -> tuple[str, str]:
        """Build bootstrap context (board view + conversation history + knowledge)."""
        from frago.server.services.pa_context_builder import build_bootstrap

        return build_bootstrap(self._rotation_count, create_reason=create_reason)

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
        """Consumer loop: drain queue, merge messages, send to PA."""
        logger.info("PA queue consumer started")
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

                if not self._pa_session or not self._session_id:
                    try:
                        await self._create_pa_session(reason="queue_consumer")
                    except Exception:
                        logger.exception("Failed to create PA session for queue consumer")
                        for m in messages:
                            await self._message_queue.put(m)
                        await asyncio.sleep(5)
                        continue

                _wait_start = asyncio.get_event_loop().time()
                while self._pa_session and self._pa_session.is_running:
                    if asyncio.get_event_loop().time() - _wait_start > 120:
                        logger.warning(
                            "Queue consumer: timed out waiting for PA subprocess "
                            "(is_running stuck), forcing rotation"
                        )
                        await self.rotate_session()
                        for m in messages:
                            await self._message_queue.put(m)
                        logger.info(
                            "Queue consumer: re-enqueued %d message(s) after timeout rotation",
                            len(messages),
                        )
                        break
                    await asyncio.sleep(0.5)

                from frago.server.services.trace import trace_entry
                for _m in messages:
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

                merged = self._format_queue_messages(messages)
                logger.info(
                    "Queue consumer: sending %d merged messages to PA (%d chars)",
                    len(messages), len(merged),
                )
                await self._send_to_pa(merged)

                while self._pa_waiting:
                    if self._pa_session and not self._pa_session.is_running:
                        break
                    await asyncio.sleep(0.5)

                if self._pa_waiting:
                    self._pa_waiting = False
                    self._total_turns += 1
                    estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
                    self._accumulated_tokens += estimated_tokens
                    if self._pa_output_buffer.strip():
                        logger.info("Queue consumer: processing PA response (%d chars)", len(self._pa_output_buffer))
                        await self._handle_pa_output(self._pa_output_buffer.strip())
                    else:
                        logger.warning("Queue consumer: PA produced no output")
                        for m in messages:
                            await self._message_queue.put(m)
                        logger.info(
                            "Queue consumer: re-enqueued %d message(s) after PA no-output",
                            len(messages),
                        )
                    self._pa_output_buffer = ""

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

            elif msg_type == "schedule_failed":
                from frago.server.services.pa_prompts import (
                    PA_SCHEDULE_FAILED_TEMPLATE,
                )
                msg_parts.append(PA_SCHEDULE_FAILED_TEMPLATE.format(
                    name=msg.get("name", "?"),
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
        """Heartbeat: idle detection + environment awareness + output collection."""
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
            if not self._pa_session or self._pa_session.is_running:
                logger.debug("Heartbeat [%d]: PA still processing, skip", self._heartbeat_seq)
                return
            self._pa_waiting = False
            self._total_turns += 1
            estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
            self._accumulated_tokens += estimated_tokens
            if self._pa_output_buffer.strip():
                logger.info("Heartbeat [%d]: processing PA response (%d chars)", self._heartbeat_seq, len(self._pa_output_buffer))
                await self._handle_pa_output(self._pa_output_buffer.strip())
            self._pa_output_buffer = ""

        if self._should_rotate():
            await self.rotate_session()
            self._heartbeat_seq += 1
            return

        if not self._pa_session or not self._session_id:
            logger.info("Heartbeat [%d]: PA idle with no session, creating new session", self._heartbeat_seq)
            try:
                await self._create_pa_session(reason="heartbeat")
            except Exception:
                logger.exception("Heartbeat: failed to create PA session")

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
        """Send message to PA via attached session. Non-blocking."""
        if not self._pa_session:
            logger.warning("Cannot send to PA: no session")
            return

        self._pa_output_buffer = ""
        self._pa_input_len = len(message)

        try:
            await self._pa_session.send_message(message)
            self._pa_waiting = True
            logger.info("Heartbeat [%d]: sent message to PA (%d chars)", self._heartbeat_seq, len(message))
        except RuntimeError as e:
            logger.error("Failed to send to PA: %s", e)
            await self.rotate_session()

    async def _send_and_wait_pa(self, message: str, timeout: float = 60.0) -> str | None:
        """Send message to PA and wait for response."""
        await self._send_to_pa(message)

        deadline = asyncio.get_event_loop().time() + timeout
        while self._pa_waiting:
            if self._pa_session and not self._pa_session.is_running:
                break
            if asyncio.get_event_loop().time() > deadline:
                logger.warning("_send_and_wait_pa: timed out after %.0fs", timeout)
                self._pa_waiting = False
                return None
            await asyncio.sleep(0.5)

        if self._pa_waiting:
            self._pa_waiting = False
            self._total_turns += 1
            estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
            self._accumulated_tokens += estimated_tokens
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
                await self.rotate_session()
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
        if da_decisions:
            try:
                DecisionApplier(board).handle_pa_output(da_decisions)
            except Exception:
                logger.debug("DecisionApplier dispatch error (non-fatal)", exc_info=True)

        # Per-action side effects (channel push, executor.execute_resume, feedback).
        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action")
            log_id = (d.get("task_id") or d.get("msg_id") or "?")[:8]
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
                    await self._enqueue_run(d)
                elif action == "resume":
                    logger.info("→ resume (task=%s)", log_id)
                    await self._handle_resume(d)
                elif action == "dismiss":
                    logger.info("→ dismiss (msg=%s)", log_id)
                    # DA already marked msg dismissed on board; no side effect needed.
                elif action == "schedule":
                    logger.info("→ schedule (name=%s)", d.get("name", ""))
                    await self._handle_schedule(d)
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
            self._lifecycle.reply, task_id, channel, reply_params,
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

    async def _enqueue_run(self, decision: dict[str, Any]) -> None:
        """PA decided action:'run'.

        DecisionApplier already appended the run task onto the board.
        This wrapper validates inputs and emits run_failed feedback if the PA
        gave us a malformed decision (missing prompt / both ids absent).
        The executor's poll loop picks up the queued board task from there.
        """
        from frago.server.services.trace import trace_entry

        task_id = decision.get("task_id", "")
        msg_id = decision.get("msg_id", "")
        description = decision.get("description", "")
        prompt = decision.get("prompt", "")
        channel = decision.get("channel", "")

        async def _fail(reason: str, detail: str) -> None:
            logger.warning("run %s failed: %s — %s", task_id[:8] or msg_id[:12] or "?", reason, detail)
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
            event=f"run dispatched (board): task={(task_id or msg_id)[:8]}",
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
                                 f"PA 决策未提供 prompt，无法 resume task {task_id[:8]}。")
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

    async def _handle_schedule(self, decision: dict[str, Any]) -> None:
        """PA decided action:'schedule' → register schedule via SchedulerService.

        ``schedule`` is intentionally outside the 4-action board vocabulary; it is
        a separate subsystem (recipe scheduler), so we don't route it through DA.
        """
        from frago.server.services.trace import trace_entry

        name = decision.get("name", "unnamed")
        prompt = decision.get("prompt", "")
        cron = decision.get("cron")
        every = decision.get("every")
        recipe = decision.get("recipe")

        async def _fail(reason: str, detail: str) -> None:
            logger.warning("schedule %r failed: %s — %s", name, reason, detail)
            trace_entry(
                origin="internal", subkind="pa", data_type="action_result",
                thread_id=None, task_id=None,
                data={"action": "schedule", "status": "failed",
                      "reason": reason, "detail": detail, "name": name},
                event=f"schedule 失败: {reason}",
            )
            await self.enqueue_message({
                "type": "schedule_failed",
                "name": name,
                "reason": reason,
                "detail": detail,
            })

        if not prompt:
            await _fail("missing_prompt", "schedule 决策未提供 prompt。")
            return

        if not cron and not every:
            await _fail("missing_schedule_spec", "schedule 决策必须提供 cron 或 every 至少一个。")
            return

        if not self._scheduler_service:
            await _fail("scheduler_unavailable", "Recipe scheduler 未初始化。")
            return

        interval_seconds = None
        if every:
            from frago.server.services.scheduler_service import _parse_interval
            try:
                interval_seconds = _parse_interval(every)
            except (ValueError, IndexError) as e:
                await _fail("invalid_interval",
                            f"Invalid --every value {every!r}: {e}")
                return

        reply_channel = decision.get("channel")
        reply_context: dict[str, Any] = {}
        msg_id = decision.get("msg_id", "")
        # Phase finish: reply_context read from board (view_for_pa exposes it).
        if msg_id and reply_channel:
            board_msg_id = f"{reply_channel}:{msg_id}"
            try:
                view = get_board().view_for_pa()
                for t in view.get("threads", []):
                    for m in t.get("msgs", []):
                        if m.get("id") == board_msg_id:
                            ctx = m.get("reply_context")
                            if ctx:
                                reply_context = dict(ctx)
                            break
            except Exception:
                logger.debug(
                    "schedule reply_context board lookup failed for %s",
                    board_msg_id, exc_info=True,
                )

        try:
            schedule = self._scheduler_service.add_schedule(
                recipe_name=recipe,
                interval_seconds=interval_seconds,
                name=name,
                prompt=prompt,
                cron=cron,
                reply_channel=reply_channel,
                reply_context=reply_context,
            )
        except Exception as e:
            await _fail("add_schedule_exception", str(e))
            return
        logger.info("Schedule registered by PA: %s (%s)", schedule["id"], name)
        trace_entry(
            origin="internal", subkind="pa", data_type="action_result",
            thread_id=None, task_id=None,
            data={"action": "schedule", "status": "ok",
                  "schedule_id": schedule["id"], "name": name},
            event=f"schedule 成功: {schedule['id']}",
        )

    # -- helpers --

    def _should_rotate(self) -> bool:
        """Check if session rotation is needed."""
        if self._total_turns >= ROTATION_TURN_THRESHOLD:
            return True
        return self._accumulated_tokens >= ROTATION_TOKEN_THRESHOLD

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
