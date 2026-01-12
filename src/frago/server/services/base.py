"""Base service utilities.

Provides common functionality for all services including:
- Cross-platform subprocess execution with Windows compatibility
- UTF-8 environment variable setup
- Logging configuration
"""

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from frago.compat import get_windows_subprocess_kwargs, prepare_command_for_windows

logger = logging.getLogger(__name__)


def get_claude_command() -> List[str]:
    """Get the command to run Claude CLI without console window flash on Windows.

    On Windows, claude is installed as a .CMD file which causes console window flash.
    This function returns the direct node.exe + cli.js command to avoid that.

    Returns:
        Command list to execute Claude CLI
    """
    if platform.system() != "Windows":
        return ["claude"]

    # Find claude.cmd location
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        return ["claude"]

    claude_path = Path(claude_cmd)

    # Check if it's a .cmd file
    if claude_path.suffix.lower() != ".cmd":
        return ["claude"]

    # Look for the cli.js file relative to claude.cmd
    cli_js = claude_path.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    if not cli_js.exists():
        return ["claude"]

    # Find node.exe
    node_exe = claude_path.parent / "node.exe"
    if not node_exe.exists():
        node_exe_path = shutil.which("node")
        if not node_exe_path:
            return ["claude"]
        node_exe = Path(node_exe_path)

    return [str(node_exe), str(cli_js)]


def get_gh_command() -> List[str]:
    """Get the command to run gh CLI without console window flash on Windows.

    On Windows, gh might be installed as a .CMD file which causes console window flash.
    This function returns the direct executable path to avoid that.

    Returns:
        Command list to execute gh CLI
    """
    if platform.system() != "Windows":
        return ["gh"]

    gh_path = shutil.which("gh")
    if not gh_path:
        return ["gh"]

    gh_path_obj = Path(gh_path)

    # If it's a .cmd file, look for gh.exe in the same directory
    if gh_path_obj.suffix.lower() == ".cmd":
        gh_exe = gh_path_obj.with_suffix(".exe")
        if gh_exe.exists():
            return [str(gh_exe)]
        # Try parent directory (common for scoop installs)
        gh_exe = gh_path_obj.parent / "gh.exe"
        if gh_exe.exists():
            return [str(gh_exe)]

    return [str(gh_path_obj)]


def resolve_command_path(cmd: List[str]) -> List[str]:
    """Resolve command to full path on all platforms.

    Ensures subprocess can find the executable regardless of PATH inheritance issues.

    Args:
        cmd: Command and arguments as list

    Returns:
        Command list with first element resolved to full path if found
    """
    if not cmd:
        return cmd

    executable = shutil.which(cmd[0])
    if executable:
        return [executable] + cmd[1:]

    return cmd


def get_utf8_env() -> Dict[str, str]:
    """Get environment variables with UTF-8 encoding for Windows compatibility.

    Returns:
        Copy of os.environ with PYTHONIOENCODING and PYTHONUTF8 set to utf-8/1.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def run_subprocess(
    cmd: List[str],
    timeout: int = 30,
    capture_output: bool = True,
    check: bool = False,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Run subprocess with Windows compatibility.

    Wraps subprocess.run with:
    - Windows command path resolution via prepare_command_for_windows
    - UTF-8 encoding for output
    - Configurable timeout
    - Hidden console window on Windows

    Args:
        cmd: Command and arguments as list
        timeout: Timeout in seconds (default 30)
        capture_output: Whether to capture stdout/stderr (default True)
        check: Whether to raise on non-zero return code (default False)
        cwd: Working directory for the subprocess
        env: Environment variables (if None, uses get_utf8_env())

    Returns:
        CompletedProcess instance with returncode, stdout, stderr

    Raises:
        subprocess.TimeoutExpired: If command exceeds timeout
        subprocess.CalledProcessError: If check=True and command fails
    """
    if env is None:
        env = get_utf8_env()

    kwargs: Dict[str, Any] = {
        "capture_output": capture_output,
        "text": True,
        "encoding": "utf-8",
        "env": env,
        "timeout": timeout,
        "check": check,
        "cwd": cwd,
        **get_windows_subprocess_kwargs(),
    }

    return subprocess.run(resolve_command_path(cmd), **kwargs)


def run_subprocess_background(
    cmd: List[str],
    stdout: Optional[Any] = subprocess.DEVNULL,
    stderr: Optional[Any] = subprocess.DEVNULL,
    stdin: Optional[Any] = subprocess.DEVNULL,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    start_new_session: bool = True,
) -> subprocess.Popen:
    """Start a subprocess in background (non-blocking).

    Used for long-running processes like agent tasks.
    On Windows, uses CREATE_NO_WINDOW flag to prevent console window popup.

    Args:
        cmd: Command and arguments as list
        stdout: stdout handling (default DEVNULL)
        stderr: stderr handling (default DEVNULL)
        stdin: stdin handling (default DEVNULL)
        cwd: Working directory for the subprocess
        env: Environment variables (if None, uses get_utf8_env())
        start_new_session: Whether to start in new session (default True, Unix only)

    Returns:
        Popen instance for the background process
    """
    if env is None:
        env = get_utf8_env()

    kwargs: Dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "stdin": stdin,
        "cwd": cwd,
        "env": env,
        **get_windows_subprocess_kwargs(),
    }

    if platform.system() != "Windows":
        # Unix: use start_new_session to detach from terminal
        kwargs["start_new_session"] = start_new_session

    return subprocess.Popen(resolve_command_path(cmd), **kwargs)


def run_subprocess_interactive(
    cmd: List[str],
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.Popen:
    """Start an interactive subprocess with stdin/stdout/stderr pipes.

    Used for interactive processes like Claude CLI console sessions.
    On Windows, uses CREATE_NO_WINDOW flag to prevent console window popup.

    Args:
        cmd: Command and arguments as list
        cwd: Working directory for the subprocess
        env: Environment variables (if None, uses get_utf8_env())

    Returns:
        Popen instance with stdin, stdout, stderr pipes
    """
    if env is None:
        env = get_utf8_env()

    kwargs: Dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "bufsize": 1,
        "cwd": cwd,
        "env": env,
        **get_windows_subprocess_kwargs(),
    }

    return subprocess.Popen(resolve_command_path(cmd), **kwargs)
