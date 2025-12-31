"""Background daemon process management for Frago Web Service.

Provides cross-platform background process spawning, PID file management,
and server lifecycle control (start/stop/status).
"""

import os
import platform
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import psutil

# Fixed port for Frago server
SERVER_PORT = 8093
SERVER_HOST = "127.0.0.1"

# PID and log file paths
FRAGO_DIR = Path.home() / ".frago"
PID_FILE = FRAGO_DIR / "server.pid"
LOG_FILE = FRAGO_DIR / "server.log"


def get_pid_file() -> Path:
    """Get the PID file path, ensuring parent directory exists."""
    FRAGO_DIR.mkdir(parents=True, exist_ok=True)
    return PID_FILE


def get_log_file() -> Path:
    """Get the log file path, ensuring parent directory exists."""
    FRAGO_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_FILE


def read_pid() -> Optional[int]:
    """Read PID from the PID file.

    Returns:
        PID if file exists and is valid, None otherwise
    """
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None

    try:
        pid_str = pid_file.read_text().strip()
        return int(pid_str)
    except (ValueError, OSError):
        return None


def write_pid(pid: int) -> None:
    """Write PID to the PID file.

    Args:
        pid: Process ID to write
    """
    pid_file = get_pid_file()
    pid_file.write_text(str(pid))


def clear_pid() -> None:
    """Remove the PID file."""
    pid_file = get_pid_file()
    pid_file.unlink(missing_ok=True)


def is_frago_process(proc: psutil.Process) -> bool:
    """Check if a process is a Frago server process.

    Args:
        proc: psutil.Process to check

    Returns:
        True if process appears to be a Frago server
    """
    try:
        cmdline = proc.cmdline()
        cmdline_str = " ".join(cmdline).lower()
        # Check for frago server runner in command line
        return "frago" in cmdline_str and ("server" in cmdline_str or "runner" in cmdline_str)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def is_server_running() -> Tuple[bool, Optional[int]]:
    """Check if the Frago server is currently running.

    Uses PID file and process validation to determine status.

    Returns:
        Tuple of (is_running, pid). pid is None if not running.
    """
    pid = read_pid()
    if pid is None:
        return False, None

    try:
        proc = psutil.Process(pid)
        if proc.is_running() and is_frago_process(proc):
            return True, pid
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    # Stale PID file - clean up
    clear_pid()
    return False, None


def get_server_uptime() -> Optional[float]:
    """Get the server uptime in seconds.

    Returns:
        Uptime in seconds if server is running, None otherwise
    """
    running, pid = is_server_running()
    if not running or pid is None:
        return None

    try:
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        return datetime.now().timestamp() - create_time
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def format_uptime(seconds: float) -> str:
    """Format uptime seconds into human-readable string.

    Args:
        seconds: Uptime in seconds

    Returns:
        Formatted string like "2h 30m" or "5m 20s"
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def check_port_available() -> Tuple[bool, Optional[str]]:
    """Check if port 8093 is available.

    Uses SO_REUSEADDR to allow binding even if port is in TIME_WAIT state.
    This matches Uvicorn's behavior which also sets SO_REUSEADDR.

    Returns:
        Tuple of (is_available, conflicting_process_info).
        conflicting_process_info is None if available.
    """
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1)
        sock.bind((SERVER_HOST, SERVER_PORT))
        sock.close()
        return True, None
    except OSError:
        # Port is in use, try to identify the process
        # Note: psutil.net_connections() requires elevated permissions on macOS
        try:
            for conn in psutil.net_connections():
                if hasattr(conn, 'laddr') and conn.laddr and conn.laddr.port == SERVER_PORT:
                    try:
                        proc = psutil.Process(conn.pid)
                        return False, f"{proc.name()} (PID: {conn.pid})"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return False, f"Unknown process (PID: {conn.pid})"
        except psutil.AccessDenied:
            # macOS requires root to enumerate all network connections
            pass
        return False, "another process"


def start_daemon() -> Tuple[bool, str]:
    """Start the Frago server as a background daemon.

    Uses platform-specific subprocess flags for proper daemonization:
    - Unix: start_new_session=True to detach from terminal
    - Windows: CREATE_NO_WINDOW and DETACHED_PROCESS flags

    Returns:
        Tuple of (success, message)
    """
    # Check if already running
    running, existing_pid = is_server_running()
    if running:
        return False, f"Frago server is already running (PID: {existing_pid})"

    # Check port availability
    port_available, conflict_info = check_port_available()
    if not port_available:
        return False, f"Port {SERVER_PORT} is in use by {conflict_info}"

    # Prepare log file
    log_file = get_log_file()

    # Build command to run the server
    # Use python -m to run the runner module directly
    cmd = [
        sys.executable,
        "-m",
        "frago.server.runner",
        "--daemon",
    ]

    try:
        # Platform-specific subprocess creation
        if platform.system() == "Windows":
            # Windows: use CREATE_NO_WINDOW and DETACHED_PROCESS
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            with open(log_file, "a") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                    close_fds=True,
                )
        else:
            # Unix: use start_new_session to detach from terminal
            with open(log_file, "a") as log_f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )

        # Write PID file
        write_pid(proc.pid)

        return True, f"Frago server started on http://{SERVER_HOST}:{SERVER_PORT} (PID: {proc.pid})"

    except Exception as e:
        return False, f"Failed to start server: {e}"


def stop_daemon() -> Tuple[bool, str]:
    """Stop the running Frago server daemon.

    Terminates the main process and all child processes to ensure
    complete cleanup and immediate port release.

    Returns:
        Tuple of (success, message)
    """
    running, pid = is_server_running()
    if not running or pid is None:
        return False, "Frago server is not running"

    try:
        proc = psutil.Process(pid)

        # Get all child processes before terminating parent
        children = proc.children(recursive=True)

        # Send SIGTERM for graceful shutdown
        if platform.system() == "Windows":
            proc.terminate()
        else:
            os.kill(pid, signal.SIGTERM)

        # Wait for main process to terminate (max 3 seconds)
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            # Force kill if graceful shutdown fails
            proc.kill()
            proc.wait(timeout=2)

        # Terminate any remaining child processes
        for child in children:
            try:
                if child.is_running():
                    child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait a moment then force kill any stubborn children
        gone, alive = psutil.wait_procs(children, timeout=2)
        for child in alive:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Clean up PID file
        clear_pid()

        return True, f"Frago server stopped (PID: {pid})"

    except psutil.NoSuchProcess:
        clear_pid()
        return True, f"Frago server stopped (PID: {pid})"
    except Exception as e:
        return False, f"Failed to stop server: {e}"


def restart_daemon(force: bool = False) -> Tuple[bool, str]:
    """Restart the Frago server daemon.

    Stops the running server (if any) and starts a new instance.

    Args:
        force: Force restart even if graceful shutdown fails

    Returns:
        Tuple of (success, message)
    """
    running, pid = is_server_running()

    # If server is running, stop it first
    if running:
        success, stop_msg = stop_daemon()
        if not success and not force:
            return False, f"Failed to stop server: {stop_msg}"

    # Start the server
    success, start_msg = start_daemon()

    if running:
        return success, f"Server restarted. {start_msg}"
    else:
        return success, f"Server was not running. {start_msg}"


def get_server_status() -> dict:
    """Get detailed server status information.

    Returns:
        Dictionary with status, pid, url, uptime, etc.
    """
    running, pid = is_server_running()

    if not running:
        return {
            "status": "stopped",
            "running": False,
            "pid": None,
            "url": None,
            "uptime": None,
            "uptime_formatted": None,
        }

    uptime = get_server_uptime()

    return {
        "status": "running",
        "running": True,
        "pid": pid,
        "url": f"http://{SERVER_HOST}:{SERVER_PORT}",
        "uptime": uptime,
        "uptime_formatted": format_uptime(uptime) if uptime else None,
    }
