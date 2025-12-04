"""Utility functions for Frago GUI."""

import os
import platform
import sys
from pathlib import Path
from typing import Optional


def can_start_gui() -> bool:
    """Check if GUI can be started in current environment.

    Returns:
        True if GUI can be started, False otherwise.
    """
    system = platform.system()

    if system == "Linux":
        display = os.environ.get("DISPLAY")
        wayland = os.environ.get("WAYLAND_DISPLAY")
        if not display and not wayland:
            return False

    elif system == "Darwin":
        pass

    elif system == "Windows":
        pass

    return True


def get_gui_unavailable_reason() -> Optional[str]:
    """Get the reason why GUI is unavailable.

    Returns:
        Reason string if GUI is unavailable, None otherwise.
    """
    system = platform.system()

    if system == "Linux":
        display = os.environ.get("DISPLAY")
        wayland = os.environ.get("WAYLAND_DISPLAY")
        if not display and not wayland:
            return "No display server found. Set $DISPLAY or $WAYLAND_DISPLAY."

    return None


def get_assets_dir() -> Path:
    """Get the path to GUI assets directory.

    Returns:
        Path to assets directory.
    """
    return Path(__file__).parent / "assets"


def get_asset_path(relative_path: str) -> Path:
    """Get the full path to a GUI asset.

    Args:
        relative_path: Path relative to assets directory.

    Returns:
        Full path to the asset.
    """
    return get_assets_dir() / relative_path


def format_bytes(size: int) -> str:
    """Format bytes to human-readable string.

    Args:
        size: Size in bytes.

    Returns:
        Formatted string (e.g., "1.5 MB").
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def format_duration(ms: int) -> str:
    """Format milliseconds to human-readable string.

    Args:
        ms: Duration in milliseconds.

    Returns:
        Formatted string (e.g., "2.5s", "1m 30s").
    """
    if ms < 1000:
        return f"{ms}ms"
    elif ms < 60000:
        return f"{ms / 1000:.1f}s"
    else:
        minutes = ms // 60000
        seconds = (ms % 60000) / 1000
        return f"{minutes}m {seconds:.0f}s"


def is_debug_mode() -> bool:
    """Check if running in debug mode.

    Returns:
        True if debug mode is enabled.
    """
    return os.environ.get("FRAGO_DEBUG", "").lower() in ("1", "true", "yes")
