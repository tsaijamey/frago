"""Abstract base class for cross-platform autostart management."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AutostartStatus:
    """Status information for autostart configuration."""

    enabled: bool
    platform: str
    config_path: Optional[Path] = None
    error: Optional[str] = None

    def __str__(self) -> str:
        if self.enabled:
            return f"Autostart: enabled ({self.platform})"
        return "Autostart: disabled"


class AutostartManager(ABC):
    """Abstract base class for platform-specific autostart managers.

    Each platform implementation handles:
    - Generating appropriate config files
    - Registering/unregistering autostart
    - Checking current status
    """

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Human-readable platform name (e.g., 'macOS LaunchAgent')."""
        ...

    @property
    @abstractmethod
    def config_path(self) -> Path:
        """Path to the autostart configuration file."""
        ...

    @abstractmethod
    def enable(self) -> tuple[bool, str]:
        """Enable autostart for frago server.

        Returns:
            Tuple of (success, message)
        """
        ...

    @abstractmethod
    def disable(self) -> tuple[bool, str]:
        """Disable autostart for frago server.

        Returns:
            Tuple of (success, message)
        """
        ...

    @abstractmethod
    def is_enabled(self) -> bool:
        """Check if autostart is currently enabled.

        Returns:
            True if autostart is enabled
        """
        ...

    def get_status(self) -> AutostartStatus:
        """Get detailed autostart status.

        Returns:
            AutostartStatus with current configuration details
        """
        return AutostartStatus(
            enabled=self.is_enabled(),
            platform=self.platform_name,
            config_path=self.config_path if self.is_enabled() else None,
        )
