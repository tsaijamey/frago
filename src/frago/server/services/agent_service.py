"""Agent task execution service.

Provides functionality for starting and continuing agent tasks.
"""

import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from frago.compat import prepare_command_for_windows
from frago.server.services.base import get_utf8_env

logger = logging.getLogger(__name__)


class AgentService:
    """Service for agent task execution."""

    @staticmethod
    def start_task(prompt: str, project_path: Optional[str] = None) -> Dict[str, Any]:
        """Start agent task.

        Executes `frago agent {prompt}` command in background.
        Returns immediately after task starts.

        Args:
            prompt: Task description/prompt.
            project_path: Optional project path context.

        Returns:
            Dictionary with status, task_id, and message or error.
        """
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()
        task_id = str(uuid.uuid4())

        try:
            # Find frago executable
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago command not found, please ensure it's properly installed and in PATH",
                }

            # Prepare log directory
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-{task_id[:8]}.log"

            # Use temp file to pass prompt (Windows compatibility)
            prompt_file = log_dir / f"prompt-{task_id[:8]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Build command
            # Pass --source web to mark this session as created from web interface
            cmd = [frago_path, "agent", "--yes", "--source", "web", "--prompt-file", str(prompt_file)]
            if project_path:
                cmd.extend(["--project", project_path])

            # Start process in background
            with open(log_file, "w", encoding="utf-8") as f:
                subprocess.Popen(
                    prepare_command_for_windows(cmd),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=get_utf8_env(),
                )

            title = prompt[:50] + "..." if len(prompt) > 50 else prompt

            return {
                "status": "ok",
                "id": task_id,
                "title": title,
                "project_path": project_path,
                "agent_type": "claude",
                "started_at": datetime.now(timezone.utc).isoformat(),
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

    @staticmethod
    def continue_task(session_id: str, prompt: str) -> Dict[str, Any]:
        """Continue conversation in specified session.

        Args:
            session_id: Session ID to continue.
            prompt: User's new prompt.

        Returns:
            Dictionary with status and message or error.
        """
        if not session_id:
            return {"status": "error", "error": "session_id cannot be empty"}
        if not prompt or not prompt.strip():
            return {"status": "error", "error": "Task description cannot be empty"}

        prompt = prompt.strip()

        try:
            # Find frago executable
            frago_path = shutil.which("frago")
            if not frago_path:
                return {
                    "status": "error",
                    "error": "frago command not found, please ensure it's properly installed and in PATH",
                }

            # Prepare log directory
            log_dir = Path.home() / ".frago" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"agent-resume-{session_id[:8]}.log"

            # Use temp file to pass prompt
            prompt_file = log_dir / f"prompt-resume-{session_id[:8]}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")

            # Start process in background
            with open(log_file, "w", encoding="utf-8") as f:
                subprocess.Popen(
                    prepare_command_for_windows([
                        frago_path,
                        "agent",
                        "--resume",
                        session_id,
                        "--yes",
                        "--prompt-file",
                        str(prompt_file),
                    ]),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=get_utf8_env(),
                )

            title = prompt[:50] + "..." if len(prompt) > 50 else prompt

            return {
                "status": "ok",
                "message": f"Continued in session {session_id[:8]}...: {title}",
            }

        except FileNotFoundError:
            return {
                "status": "error",
                "error": "frago command not found, please ensure it's properly installed",
            }
        except Exception as e:
            logger.error("Failed to continue agent task: %s", e)
            return {
                "status": "error",
                "error": f"Failed to continue task: {str(e)}",
            }
