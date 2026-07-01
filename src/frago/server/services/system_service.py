"""System status service.

Provides functionality for checking system status and server information.
"""

import logging
import os
import platform
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional

import psutil

from frago.compat import get_windows_subprocess_kwargs

logger = logging.getLogger(__name__)


class UnsupportedPlatformError(RuntimeError):
    """Raised when an OS-level action is requested on an unsupported platform."""


class SystemService:
    """Service for system status and information."""

    @staticmethod
    def get_status() -> Dict[str, Any]:
        """Get system status.

        Returns:
            Dictionary with:
            - chrome_available: Whether Chrome is available
            - chrome_connected: Whether Chrome is connected
            - projects_count: Number of monitored projects
            - tasks_running: Number of running tasks
        """
        try:
            from frago.session.models import AgentType, SessionStatus
            from frago.session.storage import list_sessions

            # Count running tasks
            running_sessions = list_sessions(
                agent_type=AgentType.CLAUDE,
                status=SessionStatus.RUNNING,
                limit=100,
            )
            tasks_running = len(running_sessions)

            # Check Chrome status via CDP
            chrome_available = False
            chrome_connected = False
            try:
                from frago.chrome.cdp.launcher import ChromeLauncher
                launcher = ChromeLauncher()
                chrome_available = launcher.chrome_path is not None
                status = launcher.get_status()
                chrome_connected = status.get("running", False)
            except Exception:
                pass

            # Get CPU and memory usage
            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Get tab count from TabManager
            tab_count = 0
            try:
                from frago.chrome.cdp.tab_manager import TabManager
                tm = TabManager()
                tab_count = len(tm._state)
            except Exception:
                pass

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "chrome_available": chrome_available,
                "chrome_connected": chrome_connected,
                "projects_count": 0,  # TODO: implement project counting
                "tasks_running": tasks_running,
                "tab_count": tab_count,
            }

        except Exception as e:
            logger.error("Failed to get system status: %s", e)
            return {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "chrome_available": False,
                "chrome_connected": False,
                "projects_count": 0,
                "tasks_running": 0,
                "tab_count": 0,
            }

    @staticmethod
    def get_directories() -> Dict[str, Any]:
        """Get system default directories.

        Returns:
            Dictionary with:
            - home: User home directory path
            - cwd: Current working directory (if accessible)
        """
        from pathlib import Path

        home = str(Path.home())
        cwd = None
        try:
            cwd = str(Path.cwd())
        except Exception:
            pass

        return {
            "home": home,
            "cwd": cwd,
        }

    @staticmethod
    def get_info(
        host: str = "127.0.0.1",
        port: int = 8080,
        started_at: str = None,
    ) -> Dict[str, Any]:
        """Get server information.

        Args:
            host: Server host address.
            port: Server port.
            started_at: Server start time ISO string.

        Returns:
            Dictionary with version, host, port, and started_at.
        """
        try:
            from frago import __version__
            version = __version__
        except ImportError:
            version = "0.0.0"

        if started_at is None:
            started_at = datetime.now().isoformat()

        return {
            "version": version,
            "host": host,
            "port": port,
            "started_at": started_at,
        }

    # ------------------------------------------------------------------
    # OS-level actions (moved out of routes/settings.py — routes 不做 subprocess)
    # ------------------------------------------------------------------

    @staticmethod
    def reveal_or_open(path: str, reveal: bool) -> None:
        """Open a path in the system file manager, optionally revealing it.

        Raises UnsupportedPlatformError on unsupported platforms and propagates
        subprocess.CalledProcessError on failure (callers map to API responses).
        """
        system = platform.system()

        if reveal:
            if system == "Darwin":
                subprocess.run(["open", "-R", path], check=True)
            elif system == "Linux":
                parent = os.path.dirname(path)
                subprocess.run(["xdg-open", parent], check=True)
            elif system == "Windows":
                subprocess.run(
                    ["explorer", "/select,", path],
                    check=True,
                    **get_windows_subprocess_kwargs(),
                )
            else:
                raise UnsupportedPlatformError(f"Unsupported platform: {system}")
        else:
            if system == "Darwin":
                subprocess.run(["open", path], check=True)
            elif system == "Linux":
                subprocess.run(["xdg-open", path], check=True)
            elif system == "Windows":
                os.startfile(path)  # type: ignore
            else:
                raise UnsupportedPlatformError(f"Unsupported platform: {system}")

    @staticmethod
    def open_directory(directory: str) -> None:
        """Open a directory in the system file manager.

        Raises UnsupportedPlatformError on unsupported platforms and propagates
        subprocess.CalledProcessError on failure.
        """
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", directory], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", directory], check=True)
        elif system == "Windows":
            os.startfile(directory)  # type: ignore
        else:
            raise UnsupportedPlatformError(f"Unsupported platform: {system}")

    @staticmethod
    def find_vscode() -> Optional[str]:
        """Find VSCode executable path.

        Returns the path to use for opening files, or None if not found.
        - macOS: checks PATH first, then /Applications/Visual Studio Code.app
        - Linux/Windows: checks PATH
        """
        code_path = shutil.which("code")
        if code_path:
            return code_path

        if platform.system() == "Darwin":
            vscode_app = "/Applications/Visual Studio Code.app"
            if os.path.exists(vscode_app):
                return vscode_app

        return None

    @staticmethod
    def open_in_vscode(vscode_path: str, settings_path: str) -> None:
        """Open a file in VSCode using a non-blocking Popen."""
        if vscode_path.endswith(".app"):
            subprocess.Popen(["open", "-a", vscode_path, settings_path])
        else:
            subprocess.Popen(
                [vscode_path, settings_path],
                **get_windows_subprocess_kwargs(),
            )
