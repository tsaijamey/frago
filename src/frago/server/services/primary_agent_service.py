"""Primary Agent service — manages the lifecycle of frago's PID 1 agent.

The Primary Agent is a persistent Claude Code session that acts as frago's
scheduler. It receives structured heartbeats, outputs JSON decisions, and
delegates execution to sub-agents working within Run instances.

Key design properties:
- Logically immortal: scheduling continuity across server restarts
- Physically bounded: session rotation prevents context O(n²) growth
- Heartbeat layered: code-level checks first (0 token), LLM only when needed
- Execution isolated: sub-agent work happens in Run containers, never in PA session

Any component that needs to communicate with the Primary Agent uses
PrimaryAgentService — it manages the attached session, heartbeat loop,
result collection, and Run lifecycle.
"""

import asyncio
import contextlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.ingestion.models import TaskStatus
from frago.server.services.pa_prompts import (
    PA_AGENT_COMPLETED_TEMPLATE,
    PA_AGENT_FAILED_TEMPLATE,
    PA_MERGED_MESSAGES_TEMPLATE,
    PA_MESSAGE_TEMPLATE,
    PA_REPLY_FAILED_TEMPLATE,
    SUB_AGENT_PROMPT_TEMPLATE,
)
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT as PRIMARY_AGENT_SYSTEM_PROMPT,
)
from frago.server.services.pa_validators import validate_pa_output, validate_queue_message
from frago.server.services.task_lifecycle import TaskLifecycle

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

class PrimaryAgentService:
    """Manages the Primary Agent lifecycle: attached session + heartbeat + Run dispatch.

    Singleton — use get_instance() to access.
    """

    _instance: "PrimaryAgentService | None" = None

    def __init__(self) -> None:
        self._session_id: str | None = None
        self._pa_session: Any | None = None  # AgentSession instance
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

        # Message queue — all message sources enqueue here
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queue_consumer_task: asyncio.Task[None] | None = None

        # Task lifecycle coordinator — single point for all state transitions
        self._lifecycle = TaskLifecycle()

        # Executor — single-threaded task runner
        self._executor: Any = None  # Executor instance, initialized in initialize()

        # Ingestion scheduler reference — for accessing cached messages
        self._scheduler: Any = None

    def set_ingestion_scheduler(self, scheduler: Any) -> None:
        """Register ingestion scheduler for message cache access.

        Called by app.py during startup (bidirectional wiring).
        """
        self._scheduler = scheduler

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- lifecycle --

    async def initialize(self) -> None:
        """Initialize PA: create attached session, start queue consumer, executor and heartbeat."""
        await self._create_pa_session(reason="initialize")

        # Start message queue consumer
        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())

        # Start executor
        from frago.server.services.executor import Executor
        from frago.server.services.ingestion.store import TaskStore
        self._executor = Executor(
            store=TaskStore(),
            pa_enqueue_message=self.enqueue_message,
            broadcast_pa_event=self._broadcast_pa_event,
        )
        self._executor.start()

        await self._start_heartbeat()

        # Recover PENDING tasks from TaskStore
        await self._recover_pending_tasks()

    async def _recover_pending_tasks(self) -> int:
        """Scan TaskStore for PENDING tasks and re-enqueue them.

        Called at initialize() and by heartbeat when PA is idle and queue is empty.
        Returns the number of tasks recovered.
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
        """Stop executor, queue consumer, heartbeat, and PA session. Called during server shutdown."""
        # Stop executor
        if self._executor:
            await self._executor.stop()

        # Stop queue consumer
        if self._queue_consumer_task and not self._queue_consumer_task.done():
            self._queue_consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._queue_consumer_task
            self._queue_consumer_task = None

        await self._stop_heartbeat()
        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("PA session stop error", exc_info=True)
            self._pa_session = None

    def get_session_id(self) -> str | None:
        """Return the current PA session_id, or None if not initialized."""
        return self._session_id

    def set_busy(self, busy: bool) -> None:
        """Set busy state. Prevents heartbeat during external processing."""
        self._busy = busy

    def record_external_message(self) -> None:
        """Record that an external message was delivered."""
        self._last_external_message_at = time.monotonic()

    # -- PA session management --

    async def _create_pa_session(self, *, reason: str = "unknown") -> None:
        """Create a new attached PA session with bootstrap context."""
        from frago.server.services.agent_service import AgentService

        logger.info("PA session creating (reason=%s, seq=%d)", reason, self._heartbeat_seq)

        bootstrap = self._build_bootstrap_prompt()
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

        # Register output callback to capture PA's assistant messages
        if self._pa_session:
            self._pa_session._on_assistant_message = self._on_pa_message

        # Wait for Claude session_id resolution
        self._session_id = await self._wait_for_session_id(self._pa_internal_id)
        self._save_session_id(self._session_id)
        logger.info("PA session created: %s", self._session_id[:8])

    async def rotate_session(self) -> None:
        """Create a new session, rebuild from external state."""
        logger.info(
            "PA session rotation (turns=%d, tokens=%d, rotation_count=%d)",
            self._total_turns, self._accumulated_tokens, self._rotation_count,
        )

        # Stop old session
        if self._pa_session:
            try:
                await self._pa_session.stop()
            except Exception:
                logger.debug("Old PA session stop error", exc_info=True)
            self._pa_session = None

        # Remove from attached sessions registry
        if self._pa_internal_id:
            from frago.server.services.agent_service import AgentService
            AgentService._attached_sessions.pop(self._pa_internal_id, None)

        # Create new session with bootstrap
        await self._create_pa_session(reason="rotation")

        # Reset counters
        self._total_turns = 0
        self._accumulated_tokens = 0
        self._rotation_count += 1
        self._consecutive_json_failures = 0

        # Orphaned message reconciliation (P0)
        orphaned = await self._reconcile_orphaned_messages()
        if orphaned:
            logger.info("Rotation: re-enqueued %d orphaned message(s)", orphaned)

    async def _reconcile_orphaned_messages(self) -> int:
        """Scan message_cache for messages with no corresponding Task, re-enqueue them.

        Called at the end of rotate_session(). Messages that were dequeued and
        sent to PA but never became Tasks (due to rotation cutting the chain)
        will still be in message_cache (Phase 1 cleans cache only after Task
        creation). Comparing cache vs TaskStore finds these orphans.
        """
        if not self._scheduler:
            return 0

        from frago.server.services.ingestion.store import TaskStore
        store = TaskStore()
        orphaned = 0

        for _key, cached in list(self._scheduler._message_cache.items()):
            if store.exists(cached.channel, cached.msg_id):
                continue
            await self.enqueue_message({
                "type": "user_message",
                "msg_id": cached.msg_id,
                "channel": cached.channel,
                "channel_message_id": cached.msg_id,
                "prompt": cached.prompt,
                "reply_context": cached.reply_context,
                "_recovered": True,
            })
            orphaned += 1
            logger.info("Orphaned message re-enqueued: %s:%s", cached.channel, cached.msg_id)

        return orphaned

    def _build_bootstrap_prompt(self) -> str:
        """Build bootstrap context from TaskStore + RunLock."""
        import platform
        import time

        sections = []
        now = datetime.now()

        # System environment
        tz_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]

        # Detect Claude model from settings
        model_id = "claude default"
        try:
            settings_path = Path.home() / ".claude" / "settings.json"
            if settings_path.exists():
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
                custom_model = settings.get("ANTHROPIC_MODEL")
                if custom_model:
                    model_id = custom_model
        except Exception:
            pass

        sections.append(
            f"系统: {platform.system()} {platform.release()} | "
            f"模型: {model_id} | "
            f"时区: {tz_name} | "
            f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        )

        if self._rotation_count > 0:
            sections.append(f"这是第 {self._rotation_count + 1} 个 PA session（前一个因 rotation 退役）。")

        # Task queue snapshot (from TaskStore)
        try:
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()

            # Executing (0 or 1)
            executing = store.get_executing()
            # Queued (pending execution)
            queued = store.get_by_status(TaskStatus.QUEUED)
            # Recent completed
            recent_completed = store.get_recent_completed(limit=8)

            lines = ["任务队列:"]
            if executing:
                lines.append("  正在执行:")
                lines.append(f"    task_id: {executing.id[:8]}")
                lines.append(f"    channel: {executing.channel}")
                desc = executing.run_descriptions[-1] if executing.run_descriptions else executing.prompt
                lines.append(f"    description: {desc}")
                lines.append(f"    session_id: {executing.session_id or '(unknown)'}")
            else:
                lines.append("  正在执行: 无")

            if queued:
                lines.append(f"  排队中 ({len(queued)} 个):")
                for t in queued:
                    lines.append(f"    - [{t.id[:8]}] ({t.channel}) {t.prompt}")
            else:
                lines.append("  排队中: 0 个")

            if recent_completed:
                lines.append(f"  最近完成 ({len(recent_completed)} 个):")
                for t in recent_completed:
                    desc = t.run_descriptions[-1] if t.run_descriptions else t.prompt
                    summary = t.result_summary or t.error or ""
                    prompt_preview = t.prompt[:80] + "..." if len(t.prompt) > 80 else t.prompt
                    lines.append(f"    - [{t.id[:8]}] ({t.channel}) [{t.status.value}] {desc}")
                    lines.append(f"      原始消息: {prompt_preview}")
                    if summary:
                        lines.append(f"      结果: {summary}")

            sections.append("\n".join(lines))
        except Exception:
            sections.append("任务队列: 不可用")

        # Agent self-knowledge index
        try:
            knowledge_file = Path(__file__).parent / "agent_knowledge.json"
            knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
            sections.append("frago 系统索引:\n" + json.dumps(knowledge, ensure_ascii=False, indent=2))
        except Exception:
            pass

        return "\n\n".join(sections)

    # -- PA event broadcast --

    async def _broadcast_pa_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Broadcast a humanized timeline event to all connected WebSocket clients.

        Pure side-effect for frontend visibility.
        Persistence is handled by trace() calls at each instrumentation point.
        Failures are logged and swallowed — PA operation must not be affected.
        """
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
        """Enqueue a message for PA consumption. Called by scheduler, monitor, etc."""
        result = validate_queue_message(msg)
        if not result.ok:
            logger.warning("Rejected invalid queue message: %s (msg: %s)", result.error, msg)
            return
        await self._message_queue.put(msg)
        logger.debug("Message enqueued: type=%s", msg.get("type", "unknown"))

        # Broadcast ingestion event for frontend Timeline
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
                # Wait for first message
                first = await self._message_queue.get()
                # Brief wait to batch nearby messages
                await asyncio.sleep(0.1)

                # Drain remaining
                messages = [first]
                while not self._message_queue.empty():
                    try:
                        messages.append(self._message_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Ensure PA session exists
                if not self._pa_session or not self._session_id:
                    try:
                        await self._create_pa_session(reason="queue_consumer")
                    except Exception:
                        logger.exception("Failed to create PA session for queue consumer")
                        # Re-enqueue messages so they aren't lost
                        for m in messages:
                            await self._message_queue.put(m)
                        await asyncio.sleep(5)
                        continue

                # Wait until PA is idle (initial session subprocess or previous message done)
                # Timeout after 120s to avoid infinite hang if _running never clears
                _wait_start = asyncio.get_event_loop().time()
                while self._pa_session and self._pa_session.is_running:
                    if asyncio.get_event_loop().time() - _wait_start > 120:
                        logger.warning(
                            "Queue consumer: timed out waiting for PA subprocess "
                            "(is_running stuck), forcing rotation"
                        )
                        await self.rotate_session()
                        # Re-enqueue dequeued messages after timeout rotation (P1)
                        for m in messages:
                            await self._message_queue.put(m)
                        logger.info(
                            "Queue consumer: re-enqueued %d message(s) after timeout rotation",
                            len(messages),
                        )
                        break
                    await asyncio.sleep(0.5)

                # Trace: PA received messages from queue
                from frago.server.services.trace import trace as _trace
                for _m in messages:
                    if isinstance(_m, dict):
                        _trace(_m.get("msg_id", ""), _m.get("task_id"), "pa",
                               f"收到消息队列: {_m.get('channel', '')}")

                # Wait for PA session subprocess to be ready (P3)
                if self._pa_session:
                    _ready_start = asyncio.get_event_loop().time()
                    while not self._pa_session.is_running:
                        if asyncio.get_event_loop().time() - _ready_start > 10:
                            logger.warning("Queue consumer: PA session not ready after 10s")
                            break
                        await asyncio.sleep(0.2)

                # Merge into one text block
                merged = self._format_queue_messages(messages)
                logger.info(
                    "Queue consumer: sending %d merged messages to PA (%d chars)",
                    len(messages), len(merged),
                )
                await self._send_to_pa(merged)

                # Wait for PA to finish processing and handle output
                while self._pa_waiting:
                    if self._pa_session and not self._pa_session.is_running:
                        break
                    await asyncio.sleep(0.5)

                # Collect and process PA output
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
                        # Re-enqueue messages when PA produces no output (P3)
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
        msg_parts.append(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_parts.append("")

            if msg_type == "user_message":
                recovered_note = ""
                if msg.get("_recovered"):
                    recovered_note = (
                        "\n⚠️ 这是一个重新投递的待处理任务——之前的处理结果未生效"
                        "（可能因 session rotation 丢失）。你必须重新处理此任务。"
                    )
                channel_name = msg.get("channel", "?")
                reply_ctx = msg.get("reply_context") or {}
                chat_name = reply_ctx.get("chat_name")
                group_line = f"<group_name>{chat_name}</group_name>\n" if chat_name else ""

                msg_parts.append(PA_MESSAGE_TEMPLATE.format(
                    channel=channel_name,
                    channel_message_id=msg.get("channel_message_id", msg.get("msg_id", "?")),
                    prompt=msg.get("prompt", ""),
                    group_line=group_line,
                ) + recovered_note)

            elif msg_type == "agent_completed":
                outputs = msg.get("output_files", [])
                outputs_section = f"输出物: {', '.join(outputs)}" if outputs else ""
                recent_logs = msg.get("recent_logs", [])
                logs_section = ""
                if recent_logs:
                    logs_section = "执行日志 (最近):\n" + "\n".join(f"  {e}" for e in recent_logs)

                msg_parts.append(PA_AGENT_COMPLETED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    outputs_section=outputs_section,
                    recent_logs_section=logs_section,
                ))

            elif msg_type == "agent_failed":
                recent_logs = msg.get("recent_logs", [])
                logs_section = ""
                if recent_logs:
                    logs_section = "执行日志 (最近):\n" + "\n".join(f"  {e}" for e in recent_logs)

                msg_parts.append(PA_AGENT_FAILED_TEMPLATE.format(
                    task_id=msg.get("task_id", "?"),
                    channel=msg.get("channel", "?"),
                    run_id=msg.get("run_id", "?"),
                    session_id=msg.get("session_id", "?"),
                    result_summary=msg.get("result_summary", "(无)"),
                    recent_logs_section=logs_section,
                ))

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

            else:
                msg_parts.append(f"[{msg_type}] {json.dumps(msg, ensure_ascii=False, default=str)}")

        return PA_MERGED_MESSAGES_TEMPLATE.format(
            count=len(messages),
            messages_body="\n".join(msg_parts),
        )

    # -- heartbeat --

    def _load_heartbeat_config(self) -> dict[str, Any]:
        """Load heartbeat config from config.json, falling back to defaults."""
        try:
            if CONFIG_FILE.exists():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                user_config = raw.get("primary_agent", {}).get("heartbeat", {})
                return {**HEARTBEAT_DEFAULTS, **user_config}
        except (json.JSONDecodeError, OSError):
            pass
        return dict(HEARTBEAT_DEFAULTS)

    async def _start_heartbeat(self) -> None:
        """Start the heartbeat loop if enabled."""
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
        """Stop the heartbeat loop."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            return
        self._heartbeat_stop.set()
        self._heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat_task
        self._heartbeat_task = None
        logger.info("PA heartbeat stopped")

    async def _heartbeat_loop(self, interval: int, initial_delay: int) -> None:
        """Main heartbeat loop."""
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

        Non-blocking design:
        - If PA is currently processing (_pa_waiting), check if done and collect output
        - Rotation check
        - If PA is idle (not waiting, no active session), bootstrap new PA session
        - Message consumption is NOT done here — that's _queue_consumer_loop's job
        """
        logger.info("Heartbeat [%d]: tick (waiting=%s)", self._heartbeat_seq, self._pa_waiting)

        # ⓧ Ensure queue consumer is alive — auto-restart if dead
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

        # ⓪ If PA was processing, check if it's done — collect output
        if self._pa_waiting:
            if not self._pa_session or self._pa_session.is_running:
                logger.debug("Heartbeat [%d]: PA still processing, skip", self._heartbeat_seq)
                return
            # PA finished — process its output
            self._pa_waiting = False
            self._total_turns += 1
            estimated_tokens = (self._pa_input_len + len(self._pa_output_buffer)) // 4
            self._accumulated_tokens += estimated_tokens
            if self._pa_output_buffer.strip():
                logger.info("Heartbeat [%d]: processing PA response (%d chars)", self._heartbeat_seq, len(self._pa_output_buffer))
                await self._handle_pa_output(self._pa_output_buffer.strip())
            self._pa_output_buffer = ""

        # ① Rotation check (0 tokens)
        # NOTE: terminal task archival is handled by scheduler._rotation_loop()
        # (daily at 0:00 + startup catch-up). We intentionally keep COMPLETED
        # tasks in memory so that get_recent_completed() returns them in
        # bootstrap prompts — critical for PA continuity after rotation.
        if self._should_rotate():
            await self.rotate_session()
            self._heartbeat_seq += 1
            return

        # If PA has no session, create one with full environment bootstrap
        if not self._pa_session or not self._session_id:
            logger.info("Heartbeat [%d]: PA idle with no session, creating new session", self._heartbeat_seq)
            try:
                await self._create_pa_session(reason="heartbeat")
            except Exception:
                logger.exception("Heartbeat: failed to create PA session")

        # ③ Recover abandoned pending tasks when PA is idle and queue is empty
        if not self._pa_waiting and self._message_queue.empty():
            recovered = await self._recover_pending_tasks()
            if recovered:
                logger.info(
                    "Heartbeat [%d]: recovered %d pending tasks",
                    self._heartbeat_seq, recovered,
                )

        # ④ Ensure executor is alive
        if self._executor and (self._executor._loop_task is None or self._executor._loop_task.done()):
            logger.warning("Heartbeat [%d]: executor loop died, restarting", self._heartbeat_seq)
            self._executor.start()

        self._heartbeat_seq += 1

    def _cleanup_terminal_tasks(self) -> None:
        """Archive completed/failed tasks out of active store.

        Reuses TaskStore.rotate() which moves terminal tasks to
        date-named archive files, keeping the active file lean.
        Skipped if no terminal tasks exist (rotate() is a no-op).
        """
        try:
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()

            # Trace terminal tasks before archiving
            from frago.server.services.trace import trace as _trace
            for task in store.get_by_status(TaskStatus.COMPLETED):
                _trace(task.channel_message_id, task.id, "pa",
                       f"归档任务: status={task.status.value}, task={task.id[:8]}")

            archived = store.rotate(exclude_failed=True)
            if archived:
                logger.info(
                    "Heartbeat [%d]: archived %d terminal task(s)",
                    self._heartbeat_seq, archived,
                )
        except Exception:
            logger.debug("Failed to cleanup terminal tasks", exc_info=True)

    def _on_pa_message(self, text: str) -> None:
        """Callback invoked by AgentSession when PA produces a complete text block."""
        self._pa_output_buffer += text

    async def _send_to_pa(self, message: str) -> None:
        """Send message to PA via attached session. Non-blocking: returns immediately.

        Output is collected via _on_pa_message callback. The next heartbeat
        tick will check if PA is done and process the accumulated output.
        """
        if not self._pa_session:
            logger.warning("Cannot send to PA: no session")
            return

        # Reset output buffer
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
        """Send message to PA and wait for response. Returns output text or None on timeout."""
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
        """Parse PA's JSON output and route decisions.

        New protocol: reply → instant send, run → TaskStore QUEUED, resume → instant kill+restart.
        No semantic dedup, no decision review — single-threaded executor eliminates conflicts.
        """
        result = validate_pa_output(output_text)

        if not result.ok:
            logger.warning("PA output validation failed: %s (raw: %r)", result.error, output_text)
            self._consecutive_json_failures += 1

            if self._consecutive_json_failures >= 2:
                logger.error("2 consecutive validation failures after correction, rotating session")
                await self.rotate_session()
                return

            # Give PA one correction chance
            correction_msg = (
                f"你的上一条输出格式错误: {result.error}\n"
                "请重新输出纯 JSON 数组，不包含任何解释性文字。"
            )
            await self._send_to_pa(correction_msg)
            return

        self._consecutive_json_failures = 0
        decisions = result.raw_data

        if not decisions:
            logger.info("PA decision: [] (idle)")
            return

        logger.info("PA decision: %d action(s) → %s", len(decisions), [d.get("action") for d in decisions if isinstance(d, dict)])

        for d in decisions:
            if not isinstance(d, dict):
                continue
            action = d.get("action")
            # Log identifier: prefer task_id, fall back to msg_id
            log_id = (d.get("task_id") or d.get("msg_id") or "?")[:8]
            _decision_data = {
                "action": action or "",
                "task_id": d.get("task_id", ""),
                "msg_id": d.get("msg_id", ""),
                "details": {k: v for k, v in d.items() if k not in ("action", "task_id", "msg_id")},
            }
            await self._broadcast_pa_event("pa_decision", _decision_data)
            # Trace: PA decision
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

                else:
                    logger.warning("Unknown PA action: %s", action)
            except Exception:
                logger.exception("Failed to execute PA decision: %s", d)

        # Deferred cache cleanup: remove cached messages after all decisions are processed.
        # This ensures multiple actions referencing the same msg_id all get cache access.
        if self._scheduler:
            seen_msg_ids: set[tuple[str, str]] = set()
            for d in decisions:
                if isinstance(d, dict) and d.get("msg_id"):
                    seen_msg_ids.add((d.get("channel", ""), d["msg_id"]))
            for channel_key, mid in seen_msg_ids:
                self._scheduler.remove_cached_message(channel_key, mid)

    # -- decision handlers --

    def _create_task_from_cache(
        self, channel: str, msg_id: str, initial_status: TaskStatus,
    ) -> Any:
        """Create an IngestedTask from cached message data.

        Called by decision handlers when PA outputs msg_id (new message scenario).
        Returns the created task, or None if cache miss.
        """
        import uuid

        from frago.server.services.ingestion.models import IngestedTask
        from frago.server.services.ingestion.store import TaskStore

        if not self._scheduler:
            logger.warning("No ingestion scheduler — cannot create task from cache")
            return None

        cached = self._scheduler.get_cached_message(channel, msg_id)
        if not cached:
            logger.warning("Cache miss for %s:%s — message may have been lost on restart", channel, msg_id)
            return None

        task = IngestedTask(
            id=str(uuid.uuid4()),
            channel=cached.channel,
            channel_message_id=cached.msg_id,
            prompt=cached.prompt,
            status=initial_status,
            reply_context=cached.reply_context,
        )
        store = TaskStore()
        store.add(task)
        if initial_status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            store.update_status(task.id, initial_status)
        logger.info("Created task %s from cached message %s (status=%s)", task.id[:8], msg_id, initial_status.value)

        # NOTE: cache cleanup is deferred to after all decisions are processed
        # (see _execute_decisions loop) to support multiple actions per msg_id.

        return task

    async def _send_reply(self, decision: dict[str, Any]) -> None:
        """PA decided action:'reply' → instant send.

        Two paths:
        - msg_id present: new message → create task(COMPLETED) from cache → reply
        - task_id present: existing task (agent callback) → reply using existing task
        """
        task_id: str = decision.get("task_id", "")
        msg_id: str = decision.get("msg_id", "")
        channel: str = decision.get("channel", "")
        text: str = decision.get("text", "")

        if not channel or not text:
            logger.warning("reply decision missing channel or text")
            return

        # msg_id path: create task from cache (born completed — PA replied directly)
        if msg_id and not task_id:
            task = self._create_task_from_cache(channel, msg_id, TaskStatus.COMPLETED)
            if task:
                task_id = task.id
                from frago.server.services.trace import trace as _trace
                _trace(msg_id, task_id, "pa", f"创建任务并标记完成: reply 直达, task={task_id[:8]}")

        reply_params = {"text": text}
        result = await asyncio.to_thread(
            self._lifecycle.reply, task_id, channel, reply_params,
        )

        if result["status"] == "ok":
            # For existing tasks still PENDING (shouldn't happen in new flow, but backward compat)
            if task_id and not msg_id:
                from frago.server.services.ingestion.store import TaskStore
                task = TaskStore().get(task_id)
                if task and task.status == TaskStatus.PENDING:
                    TaskStore().update_status(task_id, TaskStatus.COMPLETED, result_summary="replied")
            _reply_data = {
                "task_id": task_id or "",
                "msg_id": msg_id or "",
                "channel": channel or "",
                "reply_text": text,
            }
            await self._broadcast_pa_event("pa_reply", _reply_data)
            # Trace: PA replied to channel
            from frago.server.services.trace import trace as _trace
            _trace(msg_id, task_id, "pa", f"回复 {channel}: {text[:80]}",
                   data={"event_type": "pa_reply", **_reply_data})
        elif result["status"] == "error":
            await self.enqueue_message({
                "type": "reply_failed",
                "task_id": task_id,
                "channel": channel,
                "error": result.get("error", "unknown"),
                "original_text": text,
            })

    async def _enqueue_run(self, decision: dict[str, Any]) -> None:
        """PA decided action:'run' → create/find task, mark QUEUED. Executor picks up.

        Two paths:
        - msg_id present: new message → create task(QUEUED) from cache
        - task_id present: existing task (e.g. multi-step follow-up)
        """
        task_id = decision.get("task_id", "")
        msg_id = decision.get("msg_id", "")
        description = decision.get("description", "")
        prompt = decision.get("prompt", "")
        channel = decision.get("channel", "")

        if not prompt:
            logger.warning("run decision missing prompt")
            return

        from frago.server.services.ingestion.store import TaskStore
        store = TaskStore()

        # msg_id path: create task from cache
        if msg_id and not task_id:
            task = self._create_task_from_cache(channel, msg_id, TaskStatus.QUEUED)
            if not task:
                logger.warning("run decision: cannot create task from msg_id %s", msg_id)
                return
            task_id = task.id
            from frago.server.services.trace import trace as _trace
            _trace(msg_id, task_id, "pa", f"创建任务 QUEUED: {description[:60]}, task={task_id[:8]}")

        if not task_id:
            logger.warning("run decision missing both task_id and msg_id")
            return

        store.update_run_info(
            task_id,
            run_description=description,
            run_prompt=prompt,
        )
        # Only set QUEUED if task was just created with that status (msg_id path)
        # or if it's an existing task that needs re-queuing
        existing = store.get(task_id)
        if existing and existing.status != TaskStatus.QUEUED:
            store.update_status(task_id, TaskStatus.QUEUED)
        logger.info("Task %s → QUEUED (desc=%s)", task_id[:8], description)

    async def _handle_resume(self, decision: dict[str, Any]) -> None:
        """PA decided action:'resume' → delegate to executor for instant kill+restart."""
        task_id = decision.get("task_id")
        prompt = decision.get("prompt", "")

        if not task_id or not prompt:
            logger.warning("resume decision missing task_id or prompt")
            return

        if self._executor:
            await self._executor.execute_resume(task_id, prompt)
        else:
            logger.warning("Executor not available for resume")

    # -- helpers --

    def _should_rotate(self) -> bool:
        """Check if session rotation is needed."""
        if self._total_turns >= ROTATION_TURN_THRESHOLD:
            return True
        return self._accumulated_tokens >= ROTATION_TOKEN_THRESHOLD

    @staticmethod
    def _build_sub_agent_prompt(
        task_id: str | None,  # noqa: ARG004  reserved for related_runs lookup
        task_prompt: str,
        run_id: str,
        related_runs: list[str] | None = None,
    ) -> str:
        """Build the prompt for a sub-agent working in a Run instance.

        Agent 只收到任务指令 + Run 实例信息。
        NEVER 暴露消息渠道（channel/chat_id/message_id）— 回复由 PA 统一发送。
        """
        related_section = ""
        if related_runs:
            lines = ["相关历史 Run（可用 frago run info <run_id> 查看详情）:"]
            for rid in related_runs:
                lines.append(f"  - {rid}")
            related_section = "\n" + "\n".join(lines) + "\n"

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
