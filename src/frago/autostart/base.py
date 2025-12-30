"""Abstract base class for cross-platform autostart management."""

import platform
import shutil
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

    def _collect_environment_path(self) -> str:
        """Collect PATH including node/claude locations for autostart environment.

        Autostart mechanisms (LaunchAgent, systemd, Registry Run) don't inherit
        the user's shell PATH configuration. This method collects paths where
        critical commands are located so they can be explicitly set.

        Returns:
            Colon-separated (Unix) or semicolon-separated (Windows) PATH string
        """
        paths: set[str] = set()
        system = platform.system()

        # Get paths of critical commands from current environment
        for cmd in ["node", "claude", "frago"]:
            cmd_path = shutil.which(cmd)
            if cmd_path:
                paths.add(str(Path(cmd_path).parent))

        # Platform-specific common paths
        if system == "Darwin":
            # macOS: homebrew locations
            paths.update(["/opt/homebrew/bin", "/usr/local/bin"])
            # Common user bin
            paths.add(str(Path.home() / ".local/bin"))
        elif system == "Linux":
            # Linux: user local bin
            paths.add(str(Path.home() / ".local/bin"))
            paths.add("/usr/local/bin")
        elif system == "Windows":
            # Windows: common locations handled by _get_frago_path
            pass

        # System base paths (always include)
        if system != "Windows":
            paths.update(["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])

        # Use appropriate separator
        separator = ";" if system == "Windows" else ":"
        return separator.join(sorted(filter(None, paths)))
