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
