"""Agent task execution service.

Provides functionality for starting and continuing agent tasks.
Supports both detached (fire-and-forget) and attached (streaming) modes.
"""

import asyncio
import contextlib
import logging
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from frago.server.services.subprocess_utils import run_subprocess_background
from frago.server.websocket import manager

logger = logging.getLogger(__name__)


_attached_pool: Any | None = None


def _get_attached_pool() -> Any:
    """Lazily build the resident-session pool shared by attached sessions.

    Lazy rather than module-level so importing this service never costs a pool
    (and so tests can inject their own via ``AgentSession(pool=...)``).
    """
    global _attached_pool
    if _attached_pool is None:
        from frago.agent_driver.pool import WarmSessionPool

        _attached_pool = WarmSessionPool()
    return _attached_pool


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
    """Manages a single attached agent session backed by a resident tmux session.

    Phase 6 (spec 20260607): the turn runs inside a resident tmux TUI acquired
    from ``WarmSessionPool`` — the same mechanism PA already uses
    (``pa_tmux_runner.py``) — and the WebSocket event stream is driven by
    tailing the agent's transcript via ``TranscriptStreamer`` instead of
    parsing the retired headless backend's JSON stream off stdout. The emitted
    event names and field shapes are unchanged, so the frontend needs no
    changes; only the granularity coarsens from token deltas to content blocks.

    The session is resident: unlike the old subprocess model, ``send_message``
    reuses the live TUI (which keeps its own conversational context) instead of
    killing and respawning a fresh child.
    """

    def __init__(
        self,
        internal_id: str,
        project_path: str,
        *,
        prefix_provider: Callable[[], str] | None = None,
        agent_type: str = "claude",
        pool: Any | None = None,
        turn_timeout_s: float = 600.0,
    ):
        self.internal_id = internal_id
        self.project_path = project_path
        self.agent_type = agent_type
        self._pool = pool
        self._turn_timeout_s = turn_timeout_s
        self._tmux_session: Any | None = None
        self._streamer: Any | None = None
        self._attached = False
        self._running = False
        self._claude_session_id: str | None = None
        # One turn at a time per resident session: two concurrent send() calls
        # would interleave keystrokes into the same TUI and garble both turns.
        self._turn_lock = asyncio.Lock()
        # tool_use id → tool name, harvested from assistant records so a later
        # tool_result record (which carries only the id) can name its tool.
        self._pending_tool_calls: dict[str, dict[str, Any]] = {}
        # Optional callback for capturing complete assistant messages
        self._on_assistant_message: Any | None = None  # Callable[[str], None]
        # Session-bound prompt prefix (e.g., PA system prompt + bootstrap).
        # Invoked on every (re)start so identity/context survives a restart.
        # None for plain agent sessions.
        self._prefix_provider = prefix_provider

    def _assemble_prompt(self, message: str) -> str:
        """Prepend session-bound prefix to the caller-supplied message.

        Called on every (re)start. When ``prefix_provider`` is set the prefix
        is re-evaluated each time so dynamic state (e.g. PA bootstrap) is
        always current. Empty message returns the prefix alone.
        """
        if self._prefix_provider is None:
            return message
        prefix = self._prefix_provider()
        if not message:
            return prefix
        return f"{prefix}\n\n{message}"

    def _get_pool(self) -> Any:
        """The resident-session pool this attached session draws from.

        Defaults to the module-level pool shared by all attached sessions, so
        a reconnecting console reuses its warm TUI instead of cold-starting.
        """
        if self._pool is None:
            self._pool = _get_attached_pool()
        return self._pool

    async def _ensure_session(self) -> Any:
        """Acquire (or reuse) this session's resident tmux TUI + its streamer.

        Acquisition is blocking (tmux + readiness polling), so it runs in a
        worker thread. The streamer is created once per attached session and
        anchored to the transcript tail *before* the first prompt: a resumed
        session's transcript already holds its whole history, and replaying
        that as "new" would dump the entire past conversation at the frontend.
        """
        if self._tmux_session is not None and self._tmux_session.is_alive():
            return self._tmux_session

        # No FRAGO_PA marker here: this path now only ever serves WebUI
        # "new session", which must behave exactly like typing `claude` in a
        # terminal — including the SessionStart / PreToolUse hook injections.
        # The marker dates from when PA itself came through here (see the
        # 2026-05-03 validator analysis); PA has since moved to
        # pa_tmux_runner.py, which acquires its own session and never set it.
        pool = self._get_pool()
        session = await asyncio.to_thread(
            pool.acquire,
            self.agent_type,
            self.internal_id,
            self.project_path,
        )
        self._tmux_session = session

        if self._streamer is None:
            from frago.agent_driver.streamer import TranscriptStreamer

            driver = session.driver
            path_fn = driver.transcript_path
            if path_fn is None:
                # This agent exposes no transcript (opencode/codex today):
                # the turn still runs, it just streams no incremental events.
                logger.info(
                    "Agent %r exposes no transcript path — attached session %s "
                    "will run without incremental streaming",
                    self.agent_type, self.internal_id,
                )
            else:
                self._streamer = TranscriptStreamer(
                    self.agent_type, lambda: path_fn(session)
                )
                await asyncio.to_thread(self._streamer.seek_to_end)
        return session

    async def start(self, prompt: str) -> None:
        """Start a turn in attached mode on the resident tmux session.

        Per-turn user content comes from ``prompt``; any session-bound prefix
        (PA system prompt + bootstrap, etc.) is supplied by ``prefix_provider``
        and re-attached on every (re)start.
        """
        await self._ensure_session()
        self._attached = True
        await self._run_turn(self._assemble_prompt(prompt))

    async def send_message(self, message: str) -> None:
        """Send a follow-up message into the live resident session.

        Unlike the old subprocess model (which killed and respawned the child
        on every message, losing Claude-side context), the TUI stays alive and
        keeps its own conversational memory, so the raw message is enough — no
        prefix re-attachment and no session-id reset.
        """
        await manager.broadcast({
            "type": "agent_user_message",
            "internal_id": self.internal_id,
            "session_id": self._claude_session_id,
            "content": message,
        })
        await self._ensure_session()
        await self._run_turn(message)

    async def _run_turn(self, text: str) -> None:
        """Feed one turn and stream its transcript records until it completes.

        The turn's end is decided by the driver's own completion probe inside
        ``TmuxAgentSession.send`` (authoritative: it reads the transcript's
        stop_reason), with ``turn_timeout_s`` as the backstop. The streamer
        runs alongside and is drained once more after the turn returns so the
        final records aren't lost to the poll interval.
        """
        async with self._turn_lock:
            self._running = True
            session = self._tmux_session
            stream_task: asyncio.Task | None = None
            if self._streamer is not None:
                stream_task = asyncio.create_task(self._streamer.run(self._emit_record))
            try:
                await asyncio.to_thread(
                    session.send, text, timeout_s=self._turn_timeout_s
                )
            except Exception as e:
                logger.error("Attached turn failed: %s", e, exc_info=True)
            finally:
                if stream_task is not None:
                    stream_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stream_task
                if self._streamer is not None:
                    with contextlib.suppress(Exception):
                        await self._streamer.drain(self._emit_record)
                self._running = False
                await manager.broadcast({
                    "type": "agent_session_status",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "status": "completed",
                })

    async def _resolve_session_id(self) -> None:
        """Announce the agent-native session id once the transcript appears.

        The transcript's filename stem *is* the agent's native session id (the
        id the driver launched the CLI with), which is what the retired headless
        backend's ``system/init`` event carried. Derived from the path the driver handed
        us, so this stays agent-agnostic.
        """
        if self._claude_session_id is not None or self._streamer is None:
            return
        path = self._streamer.path
        if path is None:
            return
        self._claude_session_id = path.stem
        logger.info(f"Agent session ID resolved: {self._claude_session_id}")
        await manager.broadcast({
            "type": "agent_session_resolved",
            "internal_id": self.internal_id,
            "session_id": self._claude_session_id,
        })

    async def _emit_record(self, record: Any) -> None:
        """Map one normalized transcript record onto the existing WS events.

        Event names and field shapes are unchanged from the headless-backend era —
        the frontend is untouched. The only difference: text arrives as whole
        content blocks rather than token deltas, and ``parameters`` is taken
        straight from the record's complete ``tool_use.input`` instead of being
        reassembled from ``input_json_delta`` fragments.
        """
        await self._resolve_session_id()

        role = record.role or record.record_type

        if role == "assistant":
            text = record.content_text
            if text:
                # done=False opens a new assistant bubble, done=True closes it —
                # the pair the frontend's delta handler already expects.
                await manager.broadcast({
                    "type": "agent_text_delta",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "content": text,
                    "done": False,
                })
                await manager.broadcast({
                    "type": "agent_text_delta",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "content": "",
                    "done": True,
                })
                if self._on_assistant_message:
                    with contextlib.suppress(Exception):
                        self._on_assistant_message(text)

            for block in record.tool_calls:
                tool_call_id = block.get("id", "")
                tool_name = block.get("name", "")
                self._pending_tool_calls[tool_call_id] = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "timestamp": datetime.now().isoformat(),
                }
                await manager.broadcast({
                    "type": "agent_tool_executing",
                    "internal_id": self.internal_id,
                    "session_id": self._claude_session_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "parameters": block.get("input") or {},
                })
            return

        # User records carry tool results; their plain text is the echo of the
        # prompt we just sent, which the frontend already rendered itself.
        for block in record.tool_results:
            tool_use_id = block.get("tool_use_id", "")
            tool_call = self._pending_tool_calls.pop(tool_use_id, None)
            await manager.broadcast({
                "type": "agent_tool_result",
                "internal_id": self.internal_id,
                "session_id": self._claude_session_id,
                "tool_call_id": tool_use_id,
                "tool_name": tool_call["name"] if tool_call else "",
                "success": not block.get("is_error", False),
                "content": str(block.get("content", "")),
            })

    async def stop(self) -> None:
        """Stop the attached session and release its resident tmux session."""
        self._running = False
        pool = self._get_pool()
        with contextlib.suppress(Exception):
            await asyncio.to_thread(pool.evict, self.internal_id)
        self._tmux_session = None
        logger.info(f"Attached agent session {self.internal_id} stopped")

    @property
    def is_attached(self) -> bool:
        return self._attached

    @property
    def is_running(self) -> bool:
        return self._running

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
        agent_type: str = "claude",
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
            log_file = log_dir / f"agent-{task_id}.log"

            # Use temp file to pass prompt (Windows compatibility)
            prompt_file = log_dir / f"prompt-{task_id}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Build command (uses venv-aware frago lookup so daemons without
            # .venv on PATH still find the right binary)
            cmd = _resolve_frago_cmd() + [
                "agent", "--source", "web",
                "--agent-type", agent_type,
                "--session-id", claude_session_id,
                "--prompt-file", str(prompt_file),
            ]

            # Start process in background with correct cwd
            cwd = project_path or str(Path.home())
            env = None
            if env_extra:
                from frago.server.services.subprocess_utils import get_utf8_env
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
                "agent_type": agent_type,
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
        cls,
        prompt: str,
        project_path: str | None = None,
        *,
        prefix_provider: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        """Start agent task in attached mode with real-time streaming.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.
            prefix_provider: Optional zero-arg callable returning a prompt
                prefix re-evaluated on every (re)start. Use this to bind
                a long-lived role (e.g. PA system prompt + bootstrap) to
                the session — survives restarts triggered by send_message.

        Returns:
            Dictionary with internal_id, status, and project_path.
        """
        # Empty `prompt` is allowed only when a prefix_provider is bound —
        # the prefix becomes the entire initial message.
        if (not prompt or not prompt.strip()) and prefix_provider is None:
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        internal_id = str(uuid.uuid4())
        cwd = project_path or str(Path.home())

        session = AgentSession(internal_id, cwd, prefix_provider=prefix_provider)

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

