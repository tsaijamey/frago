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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from frago.server.services.pa_prompts import (
    PA_AGENT_EXIT_TEMPLATE,
    PA_AGENT_NOTIFY_TEMPLATE,
    PA_MERGED_MESSAGES_TEMPLATE,
    PA_MESSAGE_TEMPLATE,
    SUB_AGENT_PROMPT_TEMPLATE,
)
from frago.server.services.pa_prompts import (
    PA_SYSTEM_PROMPT as PRIMARY_AGENT_SYSTEM_PROMPT,
)
from frago.server.services.pa_validators import validate_pa_output, validate_queue_message

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
        self._heartbeat_task: asyncio.Task | None = None
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
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._queue_consumer_task: asyncio.Task | None = None

        # Pending resume messages — queued when target session is still running
        # Maps session_id → list of messages to re-enqueue after process exits
        self._pending_resume_messages: dict[str, list[dict]] = {}

    @classmethod
    def get_instance(cls) -> "PrimaryAgentService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- lifecycle --

    async def initialize(self) -> None:
        """Initialize PA: create attached session, start queue consumer and heartbeat."""
        await self._create_pa_session()

        # Start message queue consumer
        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())

        await self._start_heartbeat()

        # Recover PENDING tasks from TaskStore
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            pending = store.get_by_status(TaskStatus.PENDING)
            for task in pending:
                await self.enqueue_message({
                    "type": "user_message",
                    "task_id": task.id,
                    "channel": task.channel,
                    "channel_message_id": task.channel_message_id,
                    "prompt": task.prompt,
                    "reply_context": task.reply_context,
                })
            if pending:
                logger.info("Recovered %d pending tasks into PA message queue", len(pending))
        except Exception:
            logger.debug("Failed to recover pending tasks", exc_info=True)

    async def stop(self) -> None:
        """Stop queue consumer, heartbeat, and PA session. Called during server shutdown."""
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

    async def _create_pa_session(self) -> None:
        """Create a new attached PA session with bootstrap context."""
        from frago.server.services.agent_service import AgentService

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
        await self._create_pa_session()

        # Reset counters
        self._total_turns = 0
        self._accumulated_tokens = 0
        self._rotation_count += 1
        self._consecutive_json_failures = 0

    def _build_bootstrap_prompt(self) -> str:
        """Build bootstrap context from Run system + TaskStore."""
        sections = []
        now = datetime.now(UTC)
        sections.append(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        if self._rotation_count > 0:
            sections.append(f"这是第 {self._rotation_count + 1} 个 PA session（前一个因 rotation 退役）。")

        # Active runs
        try:
            from frago.run.manager import RunManager
            from frago.run.models import RunStatus
            manager = RunManager(PROJECTS_DIR)
            active_runs = manager.list_runs(status=RunStatus.ACTIVE)
            if active_runs:
                lines = [f"活跃 Run ({len(active_runs)} 个):"]
                for r in active_runs[:10]:
                    lines.append(f"  - {r['run_id']}: {r['theme_description'][:60]}")
                sections.append("\n".join(lines))
            else:
                sections.append("活跃 Run: 0 个")
        except Exception:
            sections.append("活跃 Run: 不可用")

        # Pending tasks
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            pending = store.get_by_status(TaskStatus.PENDING)
            if pending:
                lines = [f"待处理任务 ({len(pending)} 个):"]
                for t in pending[:10]:
                    lines.append(f"  - [{t.id[:8]}] ({t.channel}) {t.prompt[:60]}")
                sections.append("\n".join(lines))
            else:
                sections.append("待处理任务: 0 个")

            # Recent completed
            recent = store.get_recent(limit=10)
            completed = [t for t in recent if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
            if completed:
                lines = [f"最近完成 ({len(completed)} 个):"]
                for t in completed[:5]:
                    lines.append(f"  - [{t.status.value}] {t.prompt[:60]}")
                sections.append("\n".join(lines))
        except Exception:
            sections.append("任务状态: 不可用")

        # Run mutex
        try:
            from frago.run.context import ContextManager
            ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
            current_run_id = ctx_mgr.get_current_run_id()
            if current_run_id:
                sections.append(f"当前执行中 Run: {current_run_id}")
            else:
                sections.append("当前执行中 Run: 无（空闲）")
        except Exception:
            sections.append("Run 锁状态: 不可用")

        # Agent self-knowledge index
        try:
            knowledge_file = Path(__file__).parent / "agent_knowledge.json"
            knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
            sections.append("frago 系统索引:\n" + json.dumps(knowledge, ensure_ascii=False, indent=2))
        except Exception:
            pass

        return "\n\n".join(sections)

    # -- message queue --

    async def enqueue_message(self, msg: dict) -> None:
        """Enqueue a message for PA consumption. Called by scheduler, monitor, etc."""
        result = validate_queue_message(msg)
        if not result.ok:
            logger.warning("Rejected invalid queue message: %s (msg: %s)", result.error, msg)
            return
        await self._message_queue.put(msg)
        logger.debug("Message enqueued: type=%s", msg.get("type", "unknown"))

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
                        await self._create_pa_session()
                    except Exception:
                        logger.exception("Failed to create PA session for queue consumer")
                        # Re-enqueue messages so they aren't lost
                        for m in messages:
                            await self._message_queue.put(m)
                        await asyncio.sleep(5)
                        continue

                # Wait until PA is idle (initial session subprocess or previous message done)
                while self._pa_session and self._pa_session.is_running:
                    logger.debug("Queue consumer: waiting for PA subprocess to finish")
                    await asyncio.sleep(0.5)

                # Pre-fetch Run info for agent_notify messages
                for msg in messages:
                    if msg.get("type") == "agent_notify":
                        msg["_run_info"] = await self._prefetch_run_info(msg.get("run_id"))

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
                    self._pa_output_buffer = ""

            except asyncio.CancelledError:
                logger.info("PA queue consumer cancelled")
                raise
            except Exception:
                logger.exception("Queue consumer error")
                await asyncio.sleep(1)

    async def _prefetch_run_info(self, run_id: str | None) -> dict:
        """Pre-fetch Run log entries and outputs for an agent_notify message."""
        info: dict[str, Any] = {}
        if not run_id:
            return info
        try:
            run_dir = PROJECTS_DIR / run_id
            from frago.run.logger import RunLogger
            run_logger = RunLogger(run_dir)
            recent_logs = run_logger.get_recent_logs(count=10)
            info["recent_logs"] = [
                f"[{log.step}] {log.status.value}: {json.dumps(log.data, ensure_ascii=False)}"
                for log in recent_logs
            ]
        except Exception:
            info["recent_logs"] = ["(unavailable)"]

        try:
            outputs_dir = PROJECTS_DIR / run_id / "outputs"
            if outputs_dir.exists():
                info["output_files"] = [f.name for f in outputs_dir.iterdir() if f.is_file()]
            else:
                info["output_files"] = []
        except Exception:
            info["output_files"] = []

        return info

    def _format_queue_messages(self, messages: list[dict]) -> str:
        """Format a batch of queued messages into a single text block for PA."""
        now = datetime.now(UTC)
        msg_parts: list[str] = []
        msg_parts.append(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_parts.append("")

            if msg_type == "user_message":
                msg_parts.append(PA_MESSAGE_TEMPLATE.format(
                    channel=msg.get("channel", "?"),
                    channel_message_id=msg.get("channel_message_id", "?"),
                    task_id=msg.get("task_id", ""),
                    prompt=msg.get("prompt", ""),
                ))

            elif msg_type == "agent_notify":
                summary_or_error = f"摘要: {msg.get('summary', '(无)')}"
                if msg.get("error"):
                    summary_or_error = f"错误: {msg['error']}"

                outputs = msg.get("outputs", [])
                outputs_section = f"输出物: {', '.join(outputs)}" if outputs else ""

                run_info = msg.get("_run_info", {})
                run_info_lines: list[str] = []
                if run_info.get("recent_logs"):
                    run_info_lines.append("执行日志 (最近):")
                    for entry in run_info["recent_logs"]:
                        run_info_lines.append(f"  {entry}")
                if run_info.get("output_files"):
                    run_info_lines.append(f"outputs/ 目录文件: {', '.join(run_info['output_files'])}")

                msg_parts.append(PA_AGENT_NOTIFY_TEMPLATE.format(
                    run_id=msg.get("run_id", "?"),
                    summary_or_error=summary_or_error,
                    outputs_section=outputs_section,
                    run_info_section="\n".join(run_info_lines),
                ))

            elif msg_type == "agent_exit":
                has_completion = msg.get("has_completion_marker", False)
                has_completion_str = (
                    "已写 completion marker" if has_completion
                    else "未写 completion marker（可能异常退出）"
                )
                task_id_str = f"关联任务: {msg['task_id']}" if msg.get("task_id") else ""

                msg_parts.append(PA_AGENT_EXIT_TEMPLATE.format(
                    run_id=msg.get("run_id", "?"),
                    has_completion_marker=has_completion_str,
                    task_id=task_id_str,
                ))

            else:
                msg_parts.append(f"[{msg_type}] {json.dumps(msg, ensure_ascii=False, default=str)}")

        return PA_MERGED_MESSAGES_TEMPLATE.format(
            count=len(messages),
            messages_body="\n".join(msg_parts),
        )

    # -- heartbeat --

    def _load_heartbeat_config(self) -> dict:
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

        # ② Rotation check (0 tokens)
        if self._should_rotate():
            await self.rotate_session()
            self._heartbeat_seq += 1
            return

        # If PA has no session, create one with full environment bootstrap
        if not self._pa_session or not self._session_id:
            logger.info("Heartbeat [%d]: PA idle with no session, creating new session", self._heartbeat_seq)
            try:
                await self._create_pa_session()
            except Exception:
                logger.exception("Heartbeat: failed to create PA session")

        self._heartbeat_seq += 1

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

    # -- PA output handling --

    async def _handle_pa_output(self, output_text: str) -> None:
        """Parse PA's JSON output and route decisions to Run/Recipe/Reply."""
        result = validate_pa_output(output_text)

        if not result.ok:
            logger.warning("PA output validation failed: %s (raw: %s)", result.error, output_text)
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
            task_id = d.get("task_id", "?")[:8]
            try:
                if action == "run":
                    logger.info("→ dispatch run (task=%s, desc=%s)", task_id, d.get("description", ""))
                    await self._dispatch_run(d)
                elif action == "resume":
                    logger.info("→ dispatch resume (session=%s)", d.get("session_id", "?")[:8])
                    await self._dispatch_resume(d)
                elif action == "recipe":
                    logger.info("→ dispatch recipe (task=%s, recipe=%s)", task_id, d.get("recipe_name"))
                    await self._dispatch_recipe(d)
                elif action == "reply":
                    logger.info("→ reply (task=%s, channel=%s)", task_id, d.get("channel"))
                    await self._execute_reply(d)
                elif action == "update":
                    logger.info("→ update (task=%s, status=%s)", task_id, d.get("status"))
                    self._update_task(d)
                else:
                    logger.warning("Unknown PA action: %s", action)
            except Exception:
                logger.exception("Failed to execute PA decision: %s", d)

    # -- Run dispatch --

    async def _dispatch_run(self, decision: dict) -> None:
        """PA decided action:'run' → create Run instance → launch sub-agent."""
        task_id = decision.get("task_id")
        description = decision.get("description", "")
        prompt = decision.get("prompt", "")
        related_runs = decision.get("related_runs", [])

        if not prompt:
            logger.warning("run decision missing prompt, skipping")
            return

        # Check Run mutex
        from frago.run.context import ContextManager
        from frago.run.exceptions import ContextAlreadySetError
        ctx_mgr = ContextManager(FRAGO_HOME, PROJECTS_DIR)
        if ctx_mgr.get_current_run_id():
            logger.info("Run lock active, task %s stays pending", task_id)
            return

        # Create Run instance
        from frago.run.constants import THEME_DESCRIPTION_MAX_LEN as THEME_DESC_MAX
        from frago.run.manager import RunManager
        manager = RunManager(PROJECTS_DIR)
        run = manager.create_run(description[:THEME_DESC_MAX] if description else prompt[:THEME_DESC_MAX])
        run_id = run.run_id
        logger.info("Created Run %s for task %s", run_id, task_id)

        # Set mutex
        try:
            ctx_mgr.set_current_run(run_id, run.theme_description)
        except ContextAlreadySetError:
            logger.warning("Run lock race condition, skipping dispatch")
            return

        # Update TaskStore
        if task_id:
            try:
                from frago.server.services.ingestion.models import TaskStatus
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                store.update_status(
                    task_id, TaskStatus.EXECUTING, session_id=run_id
                )
            except Exception:
                logger.debug("Failed to update TaskStore for %s", task_id, exc_info=True)

        # Build sub-agent prompt
        agent_prompt = self._build_sub_agent_prompt(
            task_id=task_id,
            task_prompt=prompt,
            run_id=run_id,
            related_runs=related_runs,
        )

        # Launch sub-agent in Run context
        from frago.server.services.agent_service import AgentService
        result = AgentService.start_task(
            prompt=agent_prompt,
            project_path=str(Path.home()),
            env_extra={"FRAGO_CURRENT_RUN": run_id},
        )
        if result.get("status") != "ok":
            logger.error("Failed to start sub-agent: %s", result.get("error"))
            # Release lock on failure
            ctx_mgr.release_context()
        else:
            logger.info("Sub-agent launched for Run %s (agent_id=%s)", run_id, result.get("id", "?")[:8])
            pid = result.get("pid")
            if pid:
                asyncio.create_task(self._monitor_sub_agent(run_id, _task_id=task_id, pid=pid))

    async def _dispatch_resume(self, decision: dict) -> None:
        """PA decided action:'resume' → append message to existing sub-agent session.

        If the target session is still running, the message is queued in
        _pending_resume_messages and will be re-enqueued when _monitor_sub_agent
        detects the process has exited.
        """
        session_id = decision.get("session_id")
        prompt = decision.get("prompt", "")
        task_id = decision.get("task_id")

        if not session_id or not prompt:
            logger.warning("resume decision missing session_id or prompt, skipping")
            return

        # Check session status before resume
        from frago.session.models import SessionStatus
        from frago.session.storage import read_metadata

        metadata = read_metadata(session_id)
        if metadata and metadata.status == SessionStatus.RUNNING:
            logger.info(
                "Session %s is running, queueing message for later delivery",
                session_id[:8],
            )
            pending = self._pending_resume_messages.setdefault(session_id, [])
            pending.append({
                "type": "user_message",
                "task_id": task_id,
                "prompt": prompt,
                "target_session_id": session_id,
            })
            return

        # Session is not running — safe to resume
        from frago.server.services.agent_service import AgentService

        result = AgentService.continue_task(session_id, prompt)
        if result.get("status") != "ok":
            logger.error(
                "Failed to resume session %s: %s",
                session_id[:8],
                result.get("error"),
            )
        else:
            logger.info("Resumed session %s with new prompt", session_id[:8])

    async def _monitor_sub_agent(self, run_id: str, _task_id: str | None, pid: int) -> None:
        """Watch sub-agent process; enqueue agent_exit message when it exits."""
        import os

        # Poll until process exits
        while True:
            try:
                os.kill(pid, 0)
                await asyncio.sleep(5)
            except (ProcessLookupError, PermissionError):
                break

        # Check last N log entries for completion marker
        log_file = PROJECTS_DIR / run_id / "logs" / "execution.jsonl"
        has_completion = False
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-20:]):
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("step") in ("TASK_COMPLETE", "TASK_FAILED"):
                    has_completion = True
                    break
        except Exception:
            pass

        logger.info(
            "Run %s: sub-agent (PID %d) exited (has_completion=%s), enqueueing agent_exit",
            run_id, pid, has_completion,
        )
        await self.enqueue_message({
            "type": "agent_exit",
            "run_id": run_id,
            "has_completion_marker": has_completion,
            "task_id": _task_id,
        })

        # Re-enqueue any pending resume messages whose sessions are no longer running
        await self._flush_pending_resume_messages()

    async def _flush_pending_resume_messages(self) -> None:
        """Check all pending resume messages and re-enqueue those whose sessions stopped.

        Called after a sub-agent process exits. Scans _pending_resume_messages
        for session_ids that are no longer RUNNING, and re-enqueues those
        messages into the PA message queue for reprocessing.
        """
        if not self._pending_resume_messages:
            return

        from frago.session.models import SessionStatus
        from frago.session.storage import read_metadata

        flushed_sessions: list[str] = []

        for session_id, messages in list(self._pending_resume_messages.items()):
            try:
                metadata = read_metadata(session_id)
                # Flush if session no longer running (completed/error/cancelled/not found)
                if not metadata or metadata.status != SessionStatus.RUNNING:
                    for msg in messages:
                        await self.enqueue_message(msg)
                    flushed_sessions.append(session_id)
                    logger.info(
                        "Flushed %d pending messages for session %s",
                        len(messages),
                        session_id[:8],
                    )
            except Exception:
                logger.debug(
                    "Error checking pending session %s", session_id[:8], exc_info=True
                )

        for sid in flushed_sessions:
            del self._pending_resume_messages[sid]

    async def _dispatch_recipe(self, decision: dict) -> None:
        """PA decided action:'recipe' → execute recipe directly."""
        recipe_name = decision.get("recipe_name")
        params = decision.get("params", {})
        task_id = decision.get("task_id")

        if not recipe_name:
            logger.warning("recipe decision missing recipe_name")
            return

        from frago.recipes.runner import RecipeRunner
        runner = RecipeRunner()

        try:
            result = await asyncio.to_thread(runner.run, recipe_name, params=params)
            logger.info("Recipe %s result: success=%s", recipe_name, result.get("success"))

            if task_id:
                try:
                    from frago.server.services.ingestion.models import TaskStatus
                    from frago.server.services.ingestion.store import TaskStore
                    store = TaskStore()
                    status = TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
                    summary = str(result.get("data", "")) if result.get("success") else result.get("error", "")
                    store.update_status(task_id, status, result_summary=summary)
                except Exception:
                    logger.debug("Failed to update TaskStore", exc_info=True)
        except Exception:
            logger.exception("Recipe %s execution failed", recipe_name)

    async def _execute_reply(self, decision: dict) -> None:
        """PA decided action:'reply' → call notify recipe.

        Merges PA's reply_params with the full reply_context from TaskStore,
        since PA only sees truncated task summaries and may not have complete
        addressing info (to, subject, in_reply_to, chat_id, etc.).
        """
        channel = decision.get("channel")
        reply_params = decision.get("reply_params", {})
        task_id = decision.get("task_id")

        if not channel:
            logger.warning("reply decision missing channel")
            return

        # Enrich reply_params with full reply_context from TaskStore
        if task_id:
            try:
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                task = store.get(task_id)
                if task and task.reply_context:
                    # If PA provided direct text, send as-is (natural reply)
                    if reply_params.get("text"):
                        full_params = {
                            "text": reply_params["text"],
                            "reply_context": task.reply_context,
                        }
                    else:
                        # Fallback to ingestion contract format
                        full_params = {
                            "status": reply_params.get("status", "completed"),
                            "reply_context": task.reply_context,
                        }
                        if reply_params.get("result_summary"):
                            full_params["result_summary"] = reply_params["result_summary"]
                        if reply_params.get("error"):
                            full_params["error"] = reply_params["error"]
                    if reply_params.get("html_body"):
                        full_params["html_body"] = reply_params["html_body"]
                    reply_params = full_params
            except Exception:
                logger.debug("Failed to enrich reply_params from TaskStore", exc_info=True)

        # Find the notify recipe for this channel
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            channels = raw.get("task_ingestion", {}).get("channels", [])
            notify_recipe = None
            for ch in channels:
                if ch.get("name") == channel:
                    notify_recipe = ch.get("notify_recipe")
                    break

            if not notify_recipe:
                logger.warning("No notify_recipe configured for channel %s", channel)
                return

            from frago.recipes.runner import RecipeRunner
            runner = RecipeRunner()
            await asyncio.to_thread(runner.run, notify_recipe, params=reply_params)
            logger.info("Reply sent via %s for channel %s", notify_recipe, channel)

            # Mark task as completed after successful reply
            if task_id:
                try:
                    from frago.server.services.ingestion.models import TaskStatus
                    from frago.server.services.ingestion.store import TaskStore
                    TaskStore().update_status(task_id, TaskStatus.COMPLETED,
                                             result_summary=reply_params.get("result_summary", "replied"))
                except Exception:
                    logger.debug("Failed to mark task completed after reply", exc_info=True)

        except Exception:
            logger.exception("Failed to send reply for channel %s", channel)

    def _update_task(self, decision: dict) -> None:
        """PA decided action:'update' → update task status and result_summary."""
        task_id = decision.get("task_id")
        result_summary = decision.get("result_summary")
        new_status = decision.get("status")  # optional: "completed", "failed"

        if not task_id:
            return

        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            task = store.get(task_id)
            if task:
                status = task.status
                if new_status == "completed":
                    status = TaskStatus.COMPLETED
                elif new_status == "failed":
                    status = TaskStatus.FAILED
                store.update_status(task_id, status, result_summary=result_summary)
        except Exception:
            logger.debug("Failed to update task %s", task_id, exc_info=True)

    def _find_task_for_run(self, run_id: str) -> Any:
        """Find the IngestedTask associated with a run_id."""
        try:
            from frago.server.services.ingestion.models import TaskStatus
            from frago.server.services.ingestion.store import TaskStore
            store = TaskStore()
            executing = store.get_by_status(TaskStatus.EXECUTING)
            for task in executing:
                if task.session_id == run_id:
                    return task
        except Exception:
            pass
        return None

    # -- helpers --

    def _should_rotate(self) -> bool:
        """Check if session rotation is needed."""
        if self._total_turns >= ROTATION_TURN_THRESHOLD:
            return True
        return self._accumulated_tokens >= ROTATION_TOKEN_THRESHOLD

    @staticmethod
    def _build_sub_agent_prompt(
        task_id: str | None,
        task_prompt: str,
        run_id: str,
        related_runs: list[str] | None = None,
    ) -> str:
        """Build the prompt for a sub-agent working in a Run instance."""
        related_section = ""
        if related_runs:
            lines = ["相关历史 Run（可用 frago run info <run_id> 查看详情）:"]
            for rid in related_runs:
                lines.append(f"  - {rid}")
            related_section = "\n" + "\n".join(lines) + "\n"

        # Look up channel/message_id from TaskStore
        channel = "unknown"
        message_id = ""
        if task_id:
            try:
                from frago.server.services.ingestion.store import TaskStore
                store = TaskStore()
                task = store.get(task_id)
                if task:
                    channel = task.channel
                    message_id = task.channel_message_id
            except Exception:
                pass

        # Load agent self-knowledge index
        knowledge_section = ""
        try:
            knowledge_file = Path(__file__).parent / "agent_knowledge.json"
            knowledge = json.loads(knowledge_file.read_text(encoding="utf-8"))
            knowledge_section = "\nfrago 系统索引:\n" + json.dumps(knowledge, ensure_ascii=False, indent=2) + "\n"
        except Exception:
            pass

        return SUB_AGENT_PROMPT_TEMPLATE.format(
            task_prompt=task_prompt,
            run_id=run_id,
            channel=channel,
            message_id=message_id,
            related_section=related_section,
            knowledge_section=knowledge_section,
        )

    # -- persistence --

    @staticmethod
    def _save_session_id(session_id: str) -> None:
        try:
            raw: dict = {}
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
                return info["session_id"]
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
