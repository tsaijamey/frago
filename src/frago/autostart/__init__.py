"""Cross-platform autostart management for Frago server.

Provides unified interface for enabling/disabling autostart on:
- macOS: LaunchAgents
- Linux: systemd user service
- Windows: Registry Run key
"""

import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import AutostartManager


def get_autostart_manager() -> "AutostartManager":
    """Get the appropriate autostart manager for the current platform.

    Returns:
        Platform-specific AutostartManager instance

    Raises:
        NotImplementedError: If platform is not supported
    """
    system = platform.system()

    if system == "Darwin":
        from .macos import MacOSAutostartManager
        return MacOSAutostartManager()
    elif system == "Linux":
        from .linux import LinuxAutostartManager
        return LinuxAutostartManager()
    elif system == "Windows":
        from .windows import WindowsAutostartManager
        return WindowsAutostartManager()
    else:
        raise NotImplementedError(f"Autostart not supported on {system}")


__all__ = ["get_autostart_manager"]
