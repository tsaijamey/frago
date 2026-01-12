"""Cross-platform compatibility utilities"""
import os
import platform
import shutil
import sys
from typing import List


def _supports_unicode() -> bool:
    """Check if current terminal supports Unicode output"""
    if platform.system() != "Windows":
        return True

    # Must have UTF-8 stdout encoding to output Unicode
    try:
        encoding = sys.stdout.encoding or ""
        if encoding.lower() not in ("utf-8", "utf8"):
            return False
    except Exception:
        return False

    # Windows Terminal and modern consoles support Unicode
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return True

    return False


# Cross-platform symbols with fallback
_UNICODE_SUPPORTED = _supports_unicode()

SYMBOLS = {
    "clipboard": "📋" if _UNICODE_SUPPORTED else "[i]",
    "package": "📦" if _UNICODE_SUPPORTED else "[*]",
    "check": "✓" if _UNICODE_SUPPORTED else "[OK]",
    "cross": "✗" if _UNICODE_SUPPORTED else "[X]",
    "arrow": "→" if _UNICODE_SUPPORTED else "->",
    "info": "ℹ" if _UNICODE_SUPPORTED else "[i]",
}


def prepare_command_for_windows(cmd: List[str]) -> List[str]:
    """Adjust command format for Windows platform

    npm globally installed commands are .CMD batch files on Windows.
    Execute using full path directly instead of via cmd.exe /c (which truncates arguments at newlines).

    Args:
        cmd: Original command list

    Returns:
        Adjusted command list
    """
    if platform.system() != "Windows":
        return cmd

    if not cmd:
        return cmd

    # Find the full path to the executable
    executable = shutil.which(cmd[0])
    if executable:
        # Replace command name with full path
        # This allows subprocess to execute .CMD files directly without cmd.exe /c
        # Important: cmd.exe /c truncates arguments at newlines, losing multi-line prompts
        return [executable] + cmd[1:]

    return cmd


def get_windows_subprocess_kwargs(detach: bool = False) -> dict:
    """Get Windows-specific subprocess kwargs to hide console window.

    On Windows, subprocess calls to .CMD files or console applications
    can flash a console window. This function returns kwargs that prevent
    the window from appearing.

    Args:
        detach: If True, also detach process from parent (for daemons/background tasks)

    Returns:
        dict with creationflags and startupinfo for subprocess calls.
        Empty dict on non-Windows platforms.

    Example:
        subprocess.run(cmd, **get_windows_subprocess_kwargs())
        subprocess.Popen(cmd, **get_windows_subprocess_kwargs(detach=True))
    """
    if platform.system() != "Windows":
        return {}

    import subprocess

    CREATE_NO_WINDOW = 0x08000000
    kwargs: dict = {}

    if detach:
        DETACHED_PROCESS = 0x00000008
        kwargs["creationflags"] = CREATE_NO_WINDOW | DETACHED_PROCESS
    else:
        kwargs["creationflags"] = CREATE_NO_WINDOW

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo

    return kwargs
