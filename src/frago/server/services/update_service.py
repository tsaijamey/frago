"""Self-update service for frago.

Provides functionality to update frago via uv tool upgrade
and restart the server with the new version.
"""

import asyncio
import logging
import os
import platform
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class UpdateStatus:
    """Update status constants."""
    IDLE = "idle"
    CHECKING = "checking"
    UPDATING = "updating"
    RESTARTING = "restarting"
    COMPLETED = "completed"
    ERROR = "error"


class UpdateService:
    """Service for self-updating frago and restarting the server."""

    _instance: Optional["UpdateService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the service."""
        self._status = UpdateStatus.IDLE
        self._progress = 0
        self._message = ""
        self._error: Optional[str] = None
        self._update_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "UpdateService":
        """Get singleton instance.

        Returns:
            UpdateService instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def get_status(self) -> Dict[str, Any]:
        """Get current update status.

        Returns:
            Status dictionary with status, progress, message, error
        """
        return {
            "status": self._status,
            "progress": self._progress,
            "message": self._message,
            "error": self._error,
        }

    def is_updating(self) -> bool:
        """Check if an update is in progress.

        Returns:
            True if updating or restarting
        """
        return self._status in (UpdateStatus.UPDATING, UpdateStatus.RESTARTING)

    async def start_update(self) -> Dict[str, Any]:
        """Start the update process.

        Returns:
            Initial status response
        """
        if self.is_updating():
            return {
                "status": "error",
                "error": "Update already in progress",
            }

        # Reset state
        self._status = UpdateStatus.UPDATING
        self._progress = 0
        self._message = "Starting update..."
        self._error = None

        # Broadcast initial status
        await self._broadcast_status()

        # Start update task
        self._update_task = asyncio.create_task(self._do_update())

        return {
            "status": "ok",
            "message": "Update started",
        }

    async def _do_update(self) -> None:
        """Execute the update process."""
        try:
            # Step 1: Run uv tool upgrade
            self._progress = 10
            self._message = "Downloading and installing update..."
            await self._broadcast_status()

            loop = asyncio.get_event_loop()
            success, output = await loop.run_in_executor(
                None, self._run_upgrade_command
            )

            if not success:
                self._status = UpdateStatus.ERROR
                self._error = output
                self._message = "Update failed"
                await self._broadcast_status()
                return

            # Step 2: Update complete, prepare for restart
            self._progress = 80
            self._message = "Update installed, preparing restart..."
            await self._broadcast_status()

            # Small delay to ensure WebSocket message is sent
            await asyncio.sleep(0.5)

            # Step 3: Trigger restart
            self._status = UpdateStatus.RESTARTING
            self._progress = 90
            self._message = "Restarting server..."
            await self._broadcast_status()

            # Launch restarter and shutdown
            await loop.run_in_executor(None, self._trigger_restart)

        except Exception as e:
            logger.exception("Update failed")
            self._status = UpdateStatus.ERROR
            self._error = str(e)
            self._message = "Update failed"
            await self._broadcast_status()

    def _run_upgrade_command(self) -> tuple[bool, str]:
        """Run uv tool upgrade command.

        Returns:
            Tuple of (success, output_or_error)
        """
        try:
            # Find uv executable
            if platform.system() == "Windows":
                # On Windows, uv might be in PATH or in %USERPROFILE%\.local\bin
                uv_cmd = "uv"
            else:
                uv_cmd = "uv"

            cmd = [uv_cmd, "tool", "upgrade", "frago-cli"]
            logger.info(f"Running upgrade command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Upgrade failed: {error_msg}")
                return False, error_msg

            logger.info(f"Upgrade output: {result.stdout}")
            return True, result.stdout

        except subprocess.TimeoutExpired:
            return False, "Update timed out after 5 minutes"
        except FileNotFoundError:
            return False, "uv command not found. Please install uv first."
        except Exception as e:
            return False, str(e)

    def _trigger_restart(self) -> None:
        """Trigger server restart via restarter script."""
        from frago.server.daemon import read_pid

        try:
            current_pid = os.getpid()
            server_pid = read_pid() or current_pid

            # Find the restarter module
            restarter_path = Path(__file__).parent.parent / "restarter.py"

            if not restarter_path.exists():
                logger.error(f"Restarter script not found: {restarter_path}")
                return

            # Build restart command
            # Use pythonw on Windows to avoid console window
            if platform.system() == "Windows":
                python_exe = sys.executable
                # Try to use pythonw if available
                pythonw = Path(python_exe).parent / "pythonw.exe"
                if pythonw.exists():
                    python_exe = str(pythonw)

                from frago.compat import get_windows_subprocess_kwargs

                subprocess.Popen(
                    [python_exe, str(restarter_path), str(server_pid)],
                    **get_windows_subprocess_kwargs(detach=True),
                )
            else:
                subprocess.Popen(
                    [sys.executable, str(restarter_path), str(server_pid)],
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            logger.info(f"Restarter launched for PID {server_pid}")

            # Schedule shutdown of current process
            # Use os._exit to avoid cleanup that might interfere with restarter
            import threading
            def delayed_exit():
                import time
                time.sleep(1)  # Give restarter time to start
                logger.info("Shutting down for restart...")
                os._exit(0)

            threading.Thread(target=delayed_exit, daemon=True).start()

        except Exception as e:
            logger.exception(f"Failed to trigger restart: {e}")

    async def _broadcast_status(self) -> None:
        """Broadcast update status via WebSocket."""
        try:
            from frago.server.websocket import manager, create_message

            message = create_message("data_update_status", {
                "status": self._status,
                "progress": self._progress,
                "message": self._message,
                "error": self._error,
            })
            await manager.broadcast(message)
            logger.debug(
                f"Broadcast update status: {self._status} ({self._progress}%)"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast update status: {e}")

    def reset(self) -> None:
        """Reset service state to idle."""
        self._status = UpdateStatus.IDLE
        self._progress = 0
        self._message = ""
        self._error = None
        self._update_task = None
