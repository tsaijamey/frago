#!/usr/bin/env python3
"""
Browser detection - Chromium-based browser discovery

Provides cross-platform detection of Chrome, Edge, and Chromium executables.
"""

import os
import platform
import shutil
from enum import Enum
from typing import Optional


class BrowserType(Enum):
    """Supported browser types (all Chromium-based for CDP compatibility)"""
    CHROME = "chrome"
    EDGE = "edge"
    CHROMIUM = "chromium"


# Commands to try with shutil.which (highest priority)
BROWSER_COMMANDS: dict[BrowserType, list[str]] = {
    BrowserType.CHROME: ["google-chrome", "google-chrome-stable", "chrome"],
    BrowserType.EDGE: ["microsoft-edge", "microsoft-edge-stable", "msedge"],
    BrowserType.CHROMIUM: ["chromium", "chromium-browser"],
}

# Platform-specific default paths (fallback)
PLATFORM_PATHS: dict[str, dict[BrowserType, list[str]]] = {
    "Darwin": {  # macOS
        BrowserType.CHROME: [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ],
        BrowserType.EDGE: [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ],
        BrowserType.CHROMIUM: [
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
    },
    "Linux": {
        BrowserType.CHROME: [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
        ],
        BrowserType.EDGE: [
            "/usr/bin/microsoft-edge",
            "/usr/bin/microsoft-edge-stable",
            "/opt/microsoft/msedge/msedge",
        ],
        BrowserType.CHROMIUM: [
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ],
    },
    "Windows": {
        BrowserType.CHROME: [
            "${LOCALAPPDATA}\\Google\\Chrome\\Application\\chrome.exe",
            "${PROGRAMFILES}\\Google\\Chrome\\Application\\chrome.exe",
            "${PROGRAMFILES(X86)}\\Google\\Chrome\\Application\\chrome.exe",
        ],
        BrowserType.EDGE: [
            "${PROGRAMFILES(X86)}\\Microsoft\\Edge\\Application\\msedge.exe",
            "${PROGRAMFILES}\\Microsoft\\Edge\\Application\\msedge.exe",
            "${LOCALAPPDATA}\\Microsoft\\Edge\\Application\\msedge.exe",
        ],
        BrowserType.CHROMIUM: [
            "${LOCALAPPDATA}\\Chromium\\Application\\chrome.exe",
        ],
    },
}

# Windows registry paths for browser detection
REGISTRY_PATHS: dict[BrowserType, list[tuple[int, str]]] = {
    # Values are (HKEY constant, subkey path)
    # HKEY_LOCAL_MACHINE = 0x80000002, HKEY_CURRENT_USER = 0x80000001
    BrowserType.CHROME: [
        (0x80000002, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
        (0x80000001, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"),
    ],
    BrowserType.EDGE: [
        (0x80000002, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        (0x80000001, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
    ],
    BrowserType.CHROMIUM: [],  # Chromium typically doesn't register in App Paths
}


def _find_browser_from_registry(browser_type: BrowserType) -> Optional[str]:
    """Query Windows registry for browser installation path"""
    if platform.system() != "Windows":
        return None

    try:
        import winreg
    except ImportError:
        return None

    for hkey, subkey in REGISTRY_PATHS.get(browser_type, []):
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                path, _ = winreg.QueryValueEx(key, "")  # Default value
                if path and os.path.exists(path):
                    return path
        except (FileNotFoundError, OSError, PermissionError):
            continue

    return None


def find_browser(browser_type: BrowserType, system: Optional[str] = None) -> Optional[str]:
    """
    Find browser executable using three-layer detection strategy:
    1. shutil.which - User's PATH (highest priority, respects custom installations)
    2. Platform default paths - Standard installation locations
    3. Windows registry - For non-standard installations (Windows only)

    Args:
        browser_type: The type of browser to find
        system: Operating system name (defaults to platform.system())

    Returns:
        Path to browser executable, or None if not found
    """
    if system is None:
        system = platform.system()

    # Layer 1: PATH environment variable (respects user customization)
    for cmd in BROWSER_COMMANDS.get(browser_type, []):
        if path := shutil.which(cmd):
            return path

    # Layer 2: Platform default paths
    for path in PLATFORM_PATHS.get(system, {}).get(browser_type, []):
        expanded = os.path.expandvars(path)
        if os.path.exists(expanded):
            return expanded

    # Layer 3: Windows registry query (last resort for non-standard installations)
    if system == "Windows":
        if path := _find_browser_from_registry(browser_type):
            return path

    return None


def detect_available_browsers(system: Optional[str] = None) -> dict[BrowserType, Optional[str]]:
    """
    Detect all available browsers on the system.

    Returns:
        Dictionary mapping BrowserType to executable path (or None if not found)
    """
    return {
        browser_type: find_browser(browser_type, system)
        for browser_type in BrowserType
    }


def get_default_browser(system: Optional[str] = None) -> tuple[Optional[BrowserType], Optional[str]]:
    """
    Get the default browser (first available in priority order: Chrome > Edge > Chromium).

    Returns:
        Tuple of (BrowserType, path) or (None, None) if no browser found
    """
    for browser_type in [BrowserType.CHROME, BrowserType.EDGE, BrowserType.CHROMIUM]:
        if path := find_browser(browser_type, system):
            return browser_type, path
    return None, None
