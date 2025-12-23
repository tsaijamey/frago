"""Cross-platform compatibility utilities"""
import platform
import shutil
from typing import List


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
