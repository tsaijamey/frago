"""Agent task execution service.

Provides functionality for starting and continuing agent tasks.
Supports both detached (fire-and-forget) and attached (streaming) modes.
"""

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.base import (
    get_utf8_env,
    run_subprocess_background,
    run_subprocess_interactive,
)
from frago.server.websocket import manager

logger = logging.getLogger(__name__)


def _resolve_frago_cmd() -> list[str]:
    """Return the base command used to invoke frago from the server process.

    Preference order:
      1. ``frago`` in the same venv as the running server (most reliable when
         the daemon's PATH doesn't include ``.venv/Scripts`` — common on
         Windows and under systemd).
      2. ``uv run frago`` if ``uv`` is available (dev environments).
      3. Bare ``frago`` — last resort, only works when it happens to be on PATH.

    Callers append the subcommand and arguments (e.g. ``+ ["agent", ...]``).
    """
    venv_dir = Path(sys.executable).parent
    frago_in_venv = shutil.which("frago", path=str(venv_dir))
    if frago_in_venv:
        return [frago_in_venv]
    if shutil.which("uv"):
        return ["uv", "run", "frago"]
    return ["frago"]


class AgentSession:
    """Manages a single agent session with optional streaming support.

    In attached mode, holds a process handle and reads stdout for real-time
    streaming. The process itself is independent — if server restarts,
    the process continues running (degrades to detached mode).
    """

    def __init__(self, internal_id: str, project_path: str):
        self.internal_id = internal_id
        self.project_path = project_path
        self._process: subprocess.Popen | None = None
        self._reader_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._last_stream_activity: float | None = None
        self._attached = False
        self._running = False
        self._claude_session_id: str | None = None
        self._current_assistant_message = ""
        self._current_tool_input_json = ""
        self._pending_tool_calls: dict[str, dict[str, Any]] = {}
        # Optional callback for capturing complete assistant messages
        self._on_assistant_message: Any | None = None  # Callable[[str], None]

    def _get_frago_agent_command(self) -> list[str]:
        """Get frago agent command for subprocess."""
        return _resolve_frago_cmd() + ["agent"]

    def _cleanup_old_process(self) -> None:
        """Terminate old subprocess and reap it to prevent orphan/zombie leaks."""
        if not self._process:
            return

        old_pid = self._process.pid
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        except OSError:
            pass  # already dead
        finally:
            # Close pipe FDs so the old process doesn't linger
            for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
                if pipe:
                    with contextlib.suppress(OSError):
                        pipe.close()
            self._process = None
            logger.info(f"Cleaned up old subprocess (PID: {old_pid})")

    async def start(self, prompt: str) -> None:
        """Start agent process in attached mode.

        A fresh Claude session is started each time; conversational
        memory across messages is the caller's responsibility (PA
        rebuilds its prompt from queue + memory each turn).
        """
        # Kill old process before starting new one to prevent orphan leaks
        self._cleanup_old_process()

        cmd = self._get_frago_agent_command() + [
            "--passthrough",
            "--yes",
            "--source", "web",
        ]

        # Write prompt to temp file
        log_dir = Path.home() / ".frago" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = log_dir / f"agent-attached-{self.internal_id[:8]}.txt"
        prompt_file.write_text(prompt, encoding="utf-8")
        cmd.extend(["--prompt-file", str(prompt_file)])

        # FRAGO_PA marks this subprocess as a Primary Agent spawn so frago-hook
        # can short-circuit SessionStart / PreToolUse injections that pollute
        # PA's narrow JSON-action protocol with vanilla-agent guidance and
        # markdown tutorials. See PA validator failure analysis (2026-05-03).
        env = get_utf8_env()
        env["FRAGO_PA"] = "1"
        logger.info(f"Starting attached agent with command: {cmd} in {self.project_path}")
        self._process = run_subprocess_interactive(cmd, cwd=self.project_path, env=env)

        # Close stdin — prompt comes from --prompt-file
        if self._process.stdin:
            self._process.stdin.close()

        self._attached = True
        self._running = True
        self._last_stream_activity = asyncio.get_event_loop().time()
        self._reader_task = asyncio.create_task(self._read_stream())
        self._watchdog_task = asyncio.create_task(self._activity_watchdog(timeout=60.0))

        logger.info(
            f"Attached agent session {self.internal_id[:8]} started (PID: {self._process.pid})"
        )

    async def send_message(self, message: str) -> None:
        """Send a follow-up message by restarting the attached subprocess.

        Each call kills the existing claude child and launches a fresh
        ``frago agent`` invocation with the message as the new prompt.
        Cross-message Claude-side memory is not preserved at this layer;
        callers (PA) provide their own conversation context.
        """
        # Stop current reader task before starting new process
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None

        # Broadcast user message
        await manager.broadcast({
            "type": "agent_user_message",
            "internal_id": self.internal_id,
            "session_id": self._claude_session_id,
            "content": message,
        })

        # Drop the prior session id — fresh start has no continuation guarantee.
        self._claude_session_id = None

        # Start new process (start() will kill old process first)
        await self.start(message)

    async def stop(self) -> None:
        """Stop the attached session."""
        self._running = False

        if self._watchdog_task:
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
            self._watchdog_task = None

        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task

        self._cleanup_old_process()

        logger.info(f"Attached agent session {self.internal_id[:8]} stopped")

    async def _activity_watchdog(self, timeout: float) -> None:
        """Kill the subprocess if stdout stays silent for ``timeout`` seconds.

        Covers two failure modes with one mechanism:
          1. Startup deadlock — child never produces the init event (stdin
             write blocked on Windows pipe buffer before 514c061).
          2. Mid-turn stall — child emitted init/progress then went silent
             (observed during bootstraps that hang past 120s; without this
             the queue consumer was the only backstop at 120s).

        Any successful readline in ``_read_stream`` refreshes the activity
        timestamp. Normal inter-event gaps (thinking, tool calls) are much
        shorter than the timeout so legitimate work isn't killed.
        """
        check_interval = 5.0
        while True:
            try:
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                return
            if not self._running:
                return
            if self._process is None or self._process.poll() is not None:
                return
            if self._last_stream_activity is None:
                continue
            idle = asyncio.get_event_loop().time() - self._last_stream_activity
            if idle < timeout:
                continue
            logger.warning(
                "Activity watchdog: PID %s silent for %.0fs (> %.0fs) — killing stuck child",
                self._process.pid, idle, timeout,
            )
            self._cleanup_old_process()
            return

    async def _read_stream(self) -> None:
        """Read and parse stream-json output from Claude CLI."""
        if not self._process or not self._process.stdout:
            logger.error("No process or stdout available")
            return

        logger.info(f"Starting stream reader for attached session {self.internal_id[:8]}")
        line_count = 0

        try:
            loop = asyncio.get_event_loop()

            while self._running and self._process:
                line = await loop.run_in_executor(None, self._process.stdout.readline)
                self._last_stream_activity = loop.time()

                if not line:
                    logger.info(f"Attached process ended (read {line_count} lines)")
                    break

                line_count += 1
                line = line.strip()
                if not line:
                    continue

                logger.debug(f"Read line {line_count}: {line}")

                try:
                    event = json.loads(line)
                    await self._handle_stream_event(event)
                except json.JSONDecodeError:
                    logger.warning(f"Non-JSON output: {line}")
                    continue

        except Exception as e:
            logger.error(f"Error reading stream: {e}", exc_info=True)
        finally:
            self._running = False
            await manager.broadcast({
                "type": "agent_session_status",
                "internal_id": self.internal_id,
                "session_id": self._claude_session_id,
                "status": "completed",
            })

    async def _handle_stream_event(self, event: dict[str, Any]) -> None:
        """Parse and handle stream-json events from Claude CLI."""
        event_type = event.get("type", "")

        # Extract Claude session ID from system init event
        if event_type == "system" and event.get("subtype") == "init":
            self._claude_session_id = event.get("session_id")
            logger.info(f"Claude session ID resolved: {self._claude_session_id}")

            await manager.broadcast({
                "type": "agent_session_resolved",
                "internal_id": self.internal_id,
                "session_id": self._claude_session_id,
            })
            return

        # Unwrap stream_event wrapper
        if event_type == "stream_event":
            event = event.get("event", {})
            event_type = event.get("type", "")

        # Text streaming or tool input streaming
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                self._current_assistant_message += text

                await manager.broadcast({
                    "type": "agent_text_delta",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "content": text,
                    "done": False,
                })

            elif delta_type == "input_json_delta":
                self._current_tool_input_json += delta.get("partial_json", "")

        # Content block finished
        elif event_type == "content_block_stop":
            if self._current_assistant_message:
                await manager.broadcast({
                    "type": "agent_text_delta",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "content": "",
                    "done": True,
                })
                # Notify callback with complete assistant message
                if self._on_assistant_message:
                    with contextlib.suppress(Exception):
                        self._on_assistant_message(self._current_assistant_message)
                self._current_assistant_message = ""

            # Flush accumulated tool input
            if self._current_tool_input_json and self._pending_tool_calls:
                tool_call_id = list(self._pending_tool_calls.keys())[-1]
                tool_call = self._pending_tool_calls[tool_call_id]

                try:
                    tool_input = json.loads(self._current_tool_input_json)
                except json.JSONDecodeError:
                    tool_input = {"raw": self._current_tool_input_json}

                tool_call["input"] = tool_input

                await manager.broadcast({
                    "type": "agent_tool_executing",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_call["name"],
                    "parameters": tool_input,
                })

                self._current_tool_input_json = ""

        # Turn-end detection. Anthropic stream protocol emits message_delta
        # with stop_reason at the end of every turn. stop_reason="tool_use"
        # means the model wants its tool result fed back; the wrapper will
        # then start another turn cycle. Any other stop_reason (end_turn /
        # stop_sequence / max_tokens) means the model is done with this
        # prompt — the wrapper SHOULD exit, but some wrappers (notably
        # non-Anthropic backends in Claude Code passthrough mode) hang
        # without closing stdout. Preempt the 60s activity watchdog by
        # terminating proactively when we see a real end_turn marker.
        elif event_type == "message_delta":
            delta = event.get("delta", {})
            stop_reason = delta.get("stop_reason")
            if stop_reason and stop_reason != "tool_use":
                logger.info(
                    "Stream end-of-turn detected (stop_reason=%s) for "
                    "session %s; terminating subprocess proactively",
                    stop_reason, self.internal_id[:8],
                )
                if self._process and self._process.poll() is None:
                    with contextlib.suppress(Exception):
                        self._process.terminate()

        # Tool use detected
        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_call_id = block.get("id", "")
                tool_name = block.get("name", "")

                self._pending_tool_calls[tool_call_id] = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "input": {},
                    "timestamp": datetime.now().isoformat(),
                }
                self._current_tool_input_json = ""

        # Tool result
        elif event_type == "message":
            for content_block in event.get("content", []):
                if content_block.get("type") == "tool_result":
                    tool_use_id = content_block.get("tool_use_id", "")
                    content = content_block.get("content", "")

                    tool_call = self._pending_tool_calls.pop(tool_use_id, None)
                    if tool_call:
                        await manager.broadcast({
                            "type": "agent_tool_result",
                            "internal_id": self.internal_id,
                            "session_id": self._claude_session_id,
                            "tool_call_id": tool_use_id,
                            "tool_name": tool_call["name"],
                            "success": True,
                            "content": str(content),
                        })

    @property
    def is_attached(self) -> bool:
        return self._attached

    @property
    def is_running(self) -> bool:
        if not self._running:
            return False
        # The reader task may still be in its readline executor when the
        # subprocess has already exited; report the ground truth so the queue
        # consumer isn't stalled waiting for _read_stream's finally block.
        if self._process is None or self._process.poll() is not None:
            self._running = False
            return False
        return True

    @property
    def claude_session_id(self) -> str | None:
        return self._claude_session_id


class AgentService:
    """Service for agent task execution.

    Supports both detached (fire-and-forget) and attached (streaming) modes.
    """

    # Attached sessions registry (in-memory, lost on server restart)
    _attached_sessions: dict[str, AgentSession] = {}

    @staticmethod
    def start_task(
        prompt: str,
        project_path: str | None = None,
        env_extra: dict[str, str] | None = None,
        claude_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Start agent task.

        Executes `frago agent {prompt}` command in background.
        Returns immediately after task starts.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.
            env_extra: Additional environment variables for the subprocess.
            claude_session_id: Pre-generated UUID for Claude Code session traceability.

        Returns:
            Dictionary with status, task_id, pid, claude_session_id, and message or error.
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        task_id = str(uuid.uuid4())
        claude_session_id = claude_session_id or str(uuid.uuid4())

        try:
            # Prepare log directory
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-{task_id[:8]}.log"

            # Use temp file to pass prompt (Windows compatibility)
            prompt_file = log_dir / f"prompt-{task_id[:8]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Build command (uses venv-aware frago lookup so daemons without
            # .venv on PATH still find the right binary)
            cmd = _resolve_frago_cmd() + [
                "agent", "--yes", "--source", "web",
                "--session-id", claude_session_id,
                "--prompt-file", str(prompt_file),
            ]

            # Start process in background with correct cwd
            cwd = project_path or str(Path.home())
            env = None
            if env_extra:
                from frago.server.services.base import get_utf8_env
                env = get_utf8_env()
                env.update(env_extra)
            with open(log_file, "w", encoding="utf-8") as f:
                process = run_subprocess_background(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    cwd=cwd,
                    env=env,
                )

            title = prompt

            return {
                "status": "ok",
                "id": task_id,
                "pid": process.pid,
                "claude_session_id": claude_session_id,
                "title": title,
                "project_path": project_path,
                "agent_type": "claude",
                "started_at": datetime.now().isoformat(),
                "message": f"Task started: {title}",
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago command not found, please ensure it's properly installed",
            }
        except Exception as e:
            logger.error("Failed to start agent task: %s", e)
            return {
                "status": "error",
                "error": f"Failed to start task: {str(e)}",
            }

    @classmethod
    async def start_task_attached(
        cls, prompt: str, project_path: str | None = None
    ) -> dict[str, Any]:
        """Start agent task in attached mode with real-time streaming.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.

        Returns:
            Dictionary with internal_id, status, and project_path.
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        internal_id = str(uuid.uuid4())
        cwd = project_path or str(Path.home())

        session = AgentSession(internal_id, cwd)

        try:
            await session.start(prompt)
            cls._attached_sessions[internal_id] = session

            return {
                "status": "ok",
                "session_id": None,  # Real Claude session ID comes via WebSocket
                "internal_id": internal_id,
                "project_path": cwd,
            }
        except Exception as e:
            logger.error("Failed to start attached agent task: %s", e)
            return {"status": "error", "error": f"Failed to start task: {str(e)}"}

    @classmethod
    async def send_message_attached(cls, internal_id: str, message: str) -> dict[str, Any]:
        """Send a continuation message to an attached session.

        Args:
            internal_id: Internal session ID.
            message: User message.

        Returns:
            Status dictionary.
        """
        session = cls._attached_sessions.get(internal_id)
        if not session:
            return {"status": "error", "error": f"Attached session {internal_id} not found"}

        try:
            await session.send_message(message)
            return {"status": "ok"}
        except Exception as e:
            logger.error("Failed to send message to attached session: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    async def stop_attached(cls, internal_id: str) -> dict[str, Any]:
        """Stop an attached session.

        Args:
            internal_id: Internal session ID.

        Returns:
            Status dictionary.
        """
        session = cls._attached_sessions.pop(internal_id, None)
        if not session:
            return {"status": "error", "error": f"Attached session {internal_id} not found"}

        try:
            await session.stop()
            return {"status": "ok"}
        except Exception as e:
            logger.error("Failed to stop attached session: %s", e)
            return {"status": "error", "error": str(e)}

    @classmethod
    def get_attached_session_info(cls, internal_id: str) -> dict[str, Any] | None:
        """Get info about an attached session.

        Args:
            internal_id: Internal session ID.

        Returns:
            Session info dictionary or None if not found.
        """
        session = cls._attached_sessions.get(internal_id)
        if not session:
            return None

        return {
            "internal_id": session.internal_id,
            "session_id": session.claude_session_id,
            "project_path": session.project_path,
            "attached": session.is_attached,
            "running": session.is_running,
        }

