"""System status service.

Provides functionality for checking system status and server information.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


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

            # Check Chrome status (basic check)
            chrome_available = False
            chrome_connected = False
            try:
                from frago.browser.chrome_pool import ChromePool
                pool = ChromePool()
                chrome_available = pool.is_available()
                chrome_connected = pool.is_connected()
            except Exception:
                pass

            return {
                "chrome_available": chrome_available,
                "chrome_connected": chrome_connected,
                "projects_count": 0,  # TODO: implement project counting
                "tasks_running": tasks_running,
            }

        except Exception as e:
            logger.error("Failed to get system status: %s", e)
            return {
                "chrome_available": False,
                "chrome_connected": False,
                "projects_count": 0,
                "tasks_running": 0,
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
            started_at = datetime.now(timezone.utc).isoformat()

        return {
            "version": version,
            "host": host,
            "port": port,
            "started_at": started_at,
        }
