"""Console service for interactive Claude Code sessions.

Provides real-time streaming console interface for Claude Code,
supporting recipe development and general Claude tasks.
"""

import asyncio
import json
import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.server.services.base import run_subprocess_interactive
from frago.server.websocket import manager

logger = logging.getLogger(__name__)


class ConsoleMessage:
    """Represents a message in the console."""

    def __init__(
        self,
        msg_type: str,
        content: str,
        timestamp: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.type = msg_type
        self.content = content
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "metadata": self.metadata,
        }


class ConsoleSession:
    """Manages a single interactive console session with frago agent."""

    def __init__(
        self, session_id: str, project_path: Optional[str] = None, auto_approve: bool = True
    ):
        self.session_id = session_id
        # Default to home directory as the working directory for console sessions
        self.project_path = project_path or str(Path.home())
        self.auto_approve = auto_approve
        self.process: Optional[subprocess.Popen] = None
        self.messages: List[ConsoleMessage] = []
        self._running = False
        self._reader_task: Optional[asyncio.Task] = None
        self._current_assistant_message = ""
        self._pending_tool_calls: Dict[str, Dict[str, Any]] = {}
        self._claude_session_id: Optional[str] = None  # Claude CLI's internal session ID
        self._current_tool_input_json = ""  # Buffer for streaming tool input

    def _get_frago_agent_command(self) -> List[str]:
        """Get frago agent command for subprocess.

        Uses 'uv run frago agent' in development environment,
        falls back to 'frago agent' in production.

        Returns:
            Command list for frago agent
        """
        if shutil.which("uv"):
            return ["uv", "run", "frago", "agent"]
        return ["frago", "agent"]

    async def start(self, initial_prompt: str) -> None:
        """Start frago agent process with initial prompt.

        Args:
            initial_prompt: The first message to send to Claude
        """
        # Add user message to history
        user_msg = ConsoleMessage("user", initial_prompt)
        self.messages.append(user_msg)

        # Build frago agent command with passthrough mode for Web UI
        cmd = self._get_frago_agent_command() + [
            "--passthrough",      # Enable raw stream-json passthrough
            "--yes",              # Skip permission confirmation prompt
            "--source", "web",    # Mark session source as web
            # Note: SessionMonitor is needed to sync sessions to ~/.frago/sessions/
            # so watchdog can detect changes and update tasks list
        ]

        # Permission mode
        if not self.auto_approve:
            cmd.append("--ask")

        # Prepare prompt file (Windows-safe: avoid command line argument truncation)
        log_dir = Path.home() / ".frago" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = log_dir / f"console-{self.session_id[:8]}.txt"
        prompt_file.write_text(initial_prompt, encoding="utf-8")
        cmd.extend(["--prompt-file", str(prompt_file)])

        # Start subprocess
        try:
            logger.info(f"Starting frago agent with command: {cmd} in {self.project_path}")
            self.process = run_subprocess_interactive(cmd, cwd=self.project_path)

            # frago agent reads prompt from --prompt-file, just close stdin
            if self.process.stdin:
                self.process.stdin.close()

            self._running = True

            # Start background reader
            self._reader_task = asyncio.create_task(self._read_stream())

            logger.info(f"Console session {self.session_id[:8]} started (PID: {self.process.pid})")

        except Exception as e:
            logger.error(f"Failed to start console session: {e}")
            raise

    async def send_message(self, message: str) -> None:
        """Send a message to the running frago agent session.

        Uses --resume to continue the Claude session since stdin is closed after each message.

        Args:
            message: User message to send
        """
        if not self._claude_session_id:
            raise RuntimeError("No Claude session to resume (session_id not captured)")

        # Wait for current reader task to complete
        if self._reader_task:
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Reader task timeout, cancelling...")
                self._reader_task.cancel()
            except asyncio.CancelledError:
                pass

        # Add user message to history
        user_msg = ConsoleMessage("user", message)
        self.messages.append(user_msg)

        # Broadcast user message via WebSocket
        await manager.broadcast(
            {
                "type": "console_user_message",
                "session_id": self.session_id,
                "message": user_msg.to_dict(),
            }
        )

        # Build frago agent command with --resume to continue the session
        cmd = self._get_frago_agent_command() + [
            "--resume", self._claude_session_id,
            "--passthrough",      # Enable raw stream-json passthrough
            "--yes",              # Skip permission confirmation prompt
            "--source", "web",    # Mark session source as web
            "--no-monitor",       # Web UI handles its own session tracking
        ]

        # Permission mode
        if not self.auto_approve:
            cmd.append("--ask")

        # Prepare prompt file (Windows-safe)
        log_dir = Path.home() / ".frago" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = log_dir / f"console-{self.session_id[:8]}-resume.txt"
        prompt_file.write_text(message, encoding="utf-8")
        cmd.extend(["--prompt-file", str(prompt_file)])

        logger.info(f"Resuming Claude session {self._claude_session_id[:8]} via frago agent...")

        # Start new process with --resume
        self.process = run_subprocess_interactive(cmd, cwd=self.project_path)

        # frago agent reads prompt from --prompt-file, just close stdin
        if self.process.stdin:
            self.process.stdin.close()

        self._running = True

        # Start background reader for the new process
        self._reader_task = asyncio.create_task(self._read_stream())

    async def stop(self) -> None:
        """Stop the console session."""
        self._running = False

        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        logger.info(f"Console session {self.session_id[:8]} stopped")

    async def _read_stream(self) -> None:
        """Read and parse stream-json output from Claude CLI."""
        if not self.process or not self.process.stdout:
            logger.error("No process or stdout available")
            return

        logger.info(f"Starting stream reader for session {self.session_id[:8]}")
        line_count = 0

        try:
            # Use asyncio to read from subprocess in non-blocking way
            loop = asyncio.get_event_loop()

            while self._running and self.process:
                # Run blocking readline in executor to avoid blocking event loop
                line = await loop.run_in_executor(None, self.process.stdout.readline)

                if not line:
                    # Process ended
                    logger.info(f"Process ended (read {line_count} lines)")
                    break

                line_count += 1
                line = line.strip()
                if not line:
                    continue

                logger.debug(f"Read line {line_count}: {line[:100]}...")

                try:
                    event = json.loads(line)
                    await self._handle_stream_event(event)
                except json.JSONDecodeError:
                    # Non-JSON output, treat as system message
                    logger.warning(f"Non-JSON output: {line}")
                    continue

        except Exception as e:
            logger.error(f"Error reading stream: {e}", exc_info=True)
        finally:
            self._running = False
            # Broadcast session ended
            await manager.broadcast(
                {
                    "type": "console_session_status",
                    "session_id": self.session_id,
                    "status": "completed",
                }
            )

    async def _handle_stream_event(self, event: Dict[str, Any]) -> None:
        """Parse and handle stream-json events.

        Args:
            event: Parsed JSON event from Claude CLI
        """
        event_type = event.get("type", "")

        # Extract Claude's session ID from system init event
        if event_type == "system" and event.get("subtype") == "init":
            self._claude_session_id = event.get("session_id")
            logger.info(f"Claude session ID: {self._claude_session_id}")

            # Broadcast the real Claude session ID to frontend
            await manager.broadcast(
                {
                    "type": "console_session_id_resolved",
                    "internal_id": self.session_id,  # Internal ID for session management
                    "session_id": self._claude_session_id,  # Real Claude session ID
                }
            )
            return

        # Unwrap stream_event wrapper
        if event_type == "stream_event":
            event = event.get("event", {})
            event_type = event.get("type", "")

        # Assistant text streaming or tool input streaming
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type", "")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                self._current_assistant_message += text

                # Broadcast streaming text
                await manager.broadcast(
                    {
                        "type": "console_assistant_thinking",
                        "session_id": self.session_id,
                        "content": text,
                        "done": False,
                    }
                )

            elif delta_type == "input_json_delta":
                # Accumulate tool input JSON fragments
                partial_json = delta.get("partial_json", "")
                self._current_tool_input_json += partial_json

        # Content block finished (text or tool)
        elif event_type == "content_block_stop":
            if self._current_assistant_message:
                # Save complete assistant message
                msg = ConsoleMessage("assistant", self._current_assistant_message)
                self.messages.append(msg)

                # Broadcast completion
                await manager.broadcast(
                    {
                        "type": "console_assistant_thinking",
                        "session_id": self.session_id,
                        "content": "",
                        "done": True,
                    }
                )

                self._current_assistant_message = ""

            # Check if we have accumulated tool input to broadcast
            if self._current_tool_input_json and self._pending_tool_calls:
                # Get the most recent pending tool call
                tool_call_id = list(self._pending_tool_calls.keys())[-1]
                tool_call = self._pending_tool_calls[tool_call_id]

                # Parse accumulated JSON
                try:
                    tool_input = json.loads(self._current_tool_input_json)
                except json.JSONDecodeError:
                    tool_input = {"raw": self._current_tool_input_json}

                # Update pending tool call with actual input
                tool_call["input"] = tool_input

                # Save to messages
                tool_msg = ConsoleMessage(
                    "tool_call",
                    json.dumps(tool_input, indent=2),
                    tool_name=tool_call["name"],
                    tool_call_id=tool_call_id,
                )
                self.messages.append(tool_msg)

                # Broadcast tool executing with actual parameters
                await manager.broadcast(
                    {
                        "type": "console_tool_executing",
                        "session_id": self.session_id,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_call["name"],
                        "parameters": tool_input,
                    }
                )

                # Reset buffer
                self._current_tool_input_json = ""

        # Tool use detected - just record metadata, input comes via delta events
        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_call_id = block.get("id", "")
                tool_name = block.get("name", "")

                # Store pending tool call (input will be filled from delta events)
                self._pending_tool_calls[tool_call_id] = {
                    "id": tool_call_id,
                    "name": tool_name,
                    "input": {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                # Reset tool input buffer for new tool
                self._current_tool_input_json = ""

        # Tool result
        elif event_type == "message":
            message = event.get("content", [])
            for content_block in message:
                if content_block.get("type") == "tool_result":
                    tool_use_id = content_block.get("tool_use_id", "")
                    content = content_block.get("content", "")

                    # Find corresponding tool call
                    tool_call = self._pending_tool_calls.pop(tool_use_id, None)
                    if tool_call:
                        # Save result message
                        result_msg = ConsoleMessage(
                            "tool_result",
                            str(content),
                            tool_name=tool_call["name"],
                            tool_call_id=tool_use_id,
                        )
                        self.messages.append(result_msg)

                        # Broadcast result
                        await manager.broadcast(
                            {
                                "type": "console_tool_result",
                                "session_id": self.session_id,
                                "tool_call_id": tool_use_id,
                                "tool_name": tool_call["name"],
                                "success": True,
                                "content": str(content),
                            }
                        )

    def get_history(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Get message history.

        Args:
            limit: Maximum number of messages to return
            offset: Number of messages to skip

        Returns:
            Dictionary with messages and metadata
        """
        total = len(self.messages)
        messages = self.messages[offset : offset + limit]

        return {
            "messages": [msg.to_dict() for msg in messages],
            "total": total,
            "has_more": offset + limit < total,
        }


class ConsoleService:
    """Service for managing console sessions."""

    def __init__(self):
        self._sessions: Dict[str, ConsoleSession] = {}

    async def create_session(
        self, initial_prompt: str, project_path: Optional[str] = None, auto_approve: bool = True
    ) -> Dict[str, Any]:
        """Create and start a new console session.

        Args:
            initial_prompt: First message to send
            project_path: Optional project path context
            auto_approve: Whether to auto-approve all tools

        Returns:
            Session info dictionary
        """
        # Use a temporary internal ID for session management
        # The real Claude session ID will be sent via WebSocket once available
        internal_id = str(uuid.uuid4())
        session = ConsoleSession(internal_id, project_path, auto_approve)

        try:
            await session.start(initial_prompt)
            self._sessions[internal_id] = session

            return {
                # Return null - real session_id comes via WebSocket console_session_id_resolved
                "session_id": None,
                "internal_id": internal_id,  # For internal tracking only
                "status": "starting",
                "project_path": session.project_path,
                "auto_approve": auto_approve,
            }

        except Exception as e:
            logger.error(f"Failed to create console session: {e}")
            raise

    async def send_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """Send a message to an existing session.

        Args:
            session_id: Target session ID
            message: User message

        Returns:
            Status dictionary
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        try:
            await session.send_message(message)
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise

    async def stop_session(self, session_id: str) -> Dict[str, Any]:
        """Stop a running session.

        Args:
            session_id: Target session ID

        Returns:
            Status dictionary
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        try:
            await session.stop()
            del self._sessions[session_id]
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"Failed to stop session: {e}")
            raise

    def get_history(
        self, session_id: str, limit: int = 100, offset: int = 0
    ) -> Dict[str, Any]:
        """Get message history for a session.

        Args:
            session_id: Target session ID
            limit: Max messages to return
            offset: Number to skip

        Returns:
            History dictionary
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        return session.get_history(limit, offset)

    def get_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get session information.

        Args:
            session_id: Target session ID

        Returns:
            Session info dictionary
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        return {
            "session_id": session.session_id,
            "project_path": session.project_path,
            "auto_approve": session.auto_approve,
            "running": session._running,
            "message_count": len(session.messages),
        }


# Global console service instance
console_service = ConsoleService()
