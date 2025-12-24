"""Base service utilities.

Provides common functionality for all services including:
- Cross-platform subprocess execution with Windows compatibility
- UTF-8 environment variable setup
- Logging configuration
"""

import logging
import os
import subprocess
from typing import Any, Dict, List, Optional

from frago.compat import prepare_command_for_windows

logger = logging.getLogger(__name__)


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

    return subprocess.run(
        prepare_command_for_windows(cmd),
        capture_output=capture_output,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=timeout,
        check=check,
        cwd=cwd,
    )


def run_subprocess_background(
    cmd: List[str],
    stdout: Optional[Any] = subprocess.DEVNULL,
    stderr: Optional[Any] = subprocess.DEVNULL,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    start_new_session: bool = True,
) -> subprocess.Popen:
    """Start a subprocess in background (non-blocking).

    Used for long-running processes like agent tasks.

    Args:
        cmd: Command and arguments as list
        stdout: stdout handling (default DEVNULL)
        stderr: stderr handling (default DEVNULL)
        cwd: Working directory for the subprocess
        env: Environment variables (if None, uses get_utf8_env())
        start_new_session: Whether to start in new session (default True)

    Returns:
        Popen instance for the background process
    """
    if env is None:
        env = get_utf8_env()

    return subprocess.Popen(
        prepare_command_for_windows(cmd),
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        start_new_session=start_new_session,
    )
