"""Version check service for PyPI updates.

Provides background checking for new frago versions from PyPI
with WebSocket broadcast when updates are available.
"""

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Check interval in seconds (1 hour)
VERSION_CHECK_INTERVAL_SECONDS = 3600

# PyPI API endpoint
PYPI_URL = "https://pypi.org/pypi/frago-cli/json"


class VersionCheckService:
    """Service for checking PyPI version updates with periodic refresh."""

    _instance: Optional["VersionCheckService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        """Initialize the service."""
        self._cache: Optional[Dict[str, Any]] = None
        self._last_check_error: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @classmethod
    def get_instance(cls) -> "VersionCheckService":
        """Get singleton instance.

        Returns:
            VersionCheckService instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _get_current_version(self) -> str:
        """Get current installed frago version.

        Returns:
            Current version string
        """
        try:
            from frago import __version__
            return __version__
        except ImportError:
            return "0.0.0"

    async def initialize(self) -> None:
        """Initialize by performing first version check.

        This ensures version info is available before
        the initial data push to clients.
        """
        if self._cache is not None:
            logger.debug("Version info already initialized")
            return

        try:
            await self._do_check()
            logger.info(
                f"Version check initialized: "
                f"current={self._cache.get('current_version')}, "
                f"latest={self._cache.get('latest_version')}"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize version check: {e}")
            self._last_check_error = str(e)
            # Set cache with current version only
            self._cache = {
                "current_version": self._get_current_version(),
                "latest_version": None,
                "update_available": False,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }

    async def start(self) -> None:
        """Start background check task."""
        if self._task is not None and not self._task.done():
            logger.warning("Version check service already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._check_loop())
        logger.info(
            f"Version check service started "
            f"(interval: {VERSION_CHECK_INTERVAL_SECONDS}s)"
        )

    async def stop(self) -> None:
        """Stop background check task."""
        if self._task is None or self._task.done():
            return

        self._stop_event.set()
        self._task.cancel()

        try:
            await self._task
        except asyncio.CancelledError:
            pass

        self._task = None
        logger.info("Version check service stopped")

    async def _check_loop(self) -> None:
        """Background check loop."""
        while not self._stop_event.is_set():
            try:
                await self._do_check()
            except Exception as e:
                logger.warning(f"Version check failed: {e}")
                self._last_check_error = str(e)

            # Wait for next check interval or stop event
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=VERSION_CHECK_INTERVAL_SECONDS,
                )
                # If wait completes without timeout, stop was requested
                break
            except asyncio.TimeoutError:
                # Timeout means continue to next check
                continue

    async def _do_check(self) -> None:
        """Perform version check and broadcast if changed."""
        current_version = self._get_current_version()

        try:
            # Run synchronous request in thread pool
            loop = asyncio.get_event_loop()
            latest_version = await loop.run_in_executor(
                None, self._fetch_latest_version
            )
        except Exception as e:
            logger.warning(f"Failed to fetch PyPI version: {e}")
            self._last_check_error = str(e)
            # Update cache with error but keep current version
            if self._cache is None:
                self._cache = {
                    "current_version": current_version,
                    "latest_version": None,
                    "update_available": False,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                }
            return

        # Compare versions
        update_available = self._compare_versions(current_version, latest_version)

        new_cache = {
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }

        # Only broadcast if data changed
        if new_cache != self._cache:
            self._cache = new_cache
            self._last_check_error = None
            await self._broadcast_update()
            logger.debug(
                f"Version info updated: {current_version} -> {latest_version}, "
                f"update_available={update_available}"
            )

    def _fetch_latest_version(self) -> str:
        """Fetch latest version from PyPI (runs in thread pool).

        Returns:
            Latest version string

        Raises:
            Exception if fetch fails
        """
        response = requests.get(PYPI_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("info", {}).get("version", "0.0.0")

    def _compare_versions(self, current: str, latest: str) -> bool:
        """Compare version strings to determine if update is available.

        Args:
            current: Current version string
            latest: Latest version string

        Returns:
            True if latest is newer than current
        """
        try:
            from packaging.version import Version
            return Version(latest) > Version(current)
        except Exception:
            # Fallback to string comparison if packaging not available
            return latest != current and latest > current

    async def _broadcast_update(self) -> None:
        """Broadcast version info update via WebSocket."""
        try:
            from frago.server.websocket import manager, create_message

            message = create_message("data_version", {
                "data": self._cache,
                "error": self._last_check_error,
            })
            await manager.broadcast(message)
            logger.debug(
                f"Broadcast version info to {manager.connection_count} clients"
            )
        except Exception as e:
            logger.warning(f"Failed to broadcast version info: {e}")

    async def get_version_info(self) -> Dict[str, Any]:
        """Get cached version info.

        Returns:
            Version info dictionary
        """
        if self._cache is None:
            await self._do_check()
        return self._cache or {
            "current_version": self._get_current_version(),
            "latest_version": None,
            "update_available": False,
            "checked_at": None,
            "error": "Not checked yet",
        }

    def get_last_error(self) -> Optional[str]:
        """Get the last check error if any.

        Returns:
            Error message or None
        """
        return self._last_check_error
