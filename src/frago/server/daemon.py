"""Background daemon process management for Frago Web Service.

Provides cross-platform background process spawning, PID file management,
and server lifecycle control (start/stop/status).
"""

import contextlib
import http.client
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from frago.compat import get_windows_subprocess_kwargs

_SYSTEMD_SERVICE_NAME = "frago-server.service"


def _is_systemd_managed() -> bool:
    """Check if frago-server.service is enabled and systemd is available.

    When True, start/stop/restart should delegate to systemctl
    instead of managing processes directly via PID files.
    """
    if platform.system() != "Linux":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", _SYSTEMD_SERVICE_NAME],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    """Run systemctl --user with given arguments."""
    return subprocess.run(
        ["systemctl", "--user", *args, _SYSTEMD_SERVICE_NAME],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _wait_for_healthy(timeout: int = 30) -> tuple[bool, str]:
    """Poll /api/status until server responds 200 or timeout.

    Returns (success, detail_message).
    """
    from frago.server.daemon import get_server_port

    port = get_server_port()
    deadline = time.time() + timeout
    attempt = 0
    last_error = ""
    while time.time() < deadline:
        attempt += 1
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/api/status")
            resp = conn.getresponse()
            if resp.status == 200:
                return True, f"port={port}, attempts={attempt}"
            last_error = f"HTTP {resp.status}"
            conn.close()
        except (ConnectionRefusedError, OSError, http.client.HTTPException) as e:
            last_error = str(e)
        time.sleep(1)
    return False, f"timeout after {timeout}s ({last_error})"


# Default server configuration
DEFAULT_SERVER_PORT = 8093
DEFAULT_SERVER_HOST = "127.0.0.1"


def get_server_port() -> int:
    """Get the server port from environment or default.

    Priority: FRAGO_SERVER_PORT env var > default (8093)
    """
    port_str = os.environ.get("FRAGO_SERVER_PORT")
    if port_str:
        try:
            port = int(port_str)
            if 1 <= port <= 65535:
                return port
        except ValueError:
            pass
    return DEFAULT_SERVER_PORT


def get_server_host() -> str:
    """Get the server host from environment or default.

    Priority: FRAGO_SERVER_HOST env var > default (127.0.0.1)
    """
    return os.environ.get("FRAGO_SERVER_HOST", DEFAULT_SERVER_HOST)


# Runtime server configuration (for backward compatibility)
SERVER_PORT = get_server_port()
SERVER_HOST = get_server_host()

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


def read_pid() -> int | None:
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


def cleanup_stale_pid() -> bool:
    """Proactively clean stale PID file on startup.

    Checks if the PID file points to a valid frago process.
    If not (process died, wrong process, etc.), removes the stale file.

    Returns:
        True if a stale PID was cleaned up, False otherwise
    """
    pid = read_pid()
    if pid is None:
        return False

    try:
        proc = psutil.Process(pid)
        if proc.is_running() and is_frago_process(proc):
            return False  # Process is valid, nothing to clean
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

    # Stale PID - clean up
    clear_pid()
    return True


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


def find_frago_process_on_port() -> int | None:
    """Find a Frago server process listening on the server port.

    Checks network connections for a process on SERVER_PORT that
    matches frago command line patterns.

    Returns:
        PID if found, None otherwise
    """
    try:
        for conn in psutil.net_connections(kind="inet"):
            if (
                hasattr(conn, "laddr")
                and conn.laddr
                and conn.laddr.port == SERVER_PORT
                and conn.status == "LISTEN"
                and conn.pid
            ):
                try:
                    proc = psutil.Process(conn.pid)
                    if is_frago_process(proc):
                        return conn.pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except psutil.AccessDenied:
        # macOS requires root for psutil.net_connections(); fall back to lsof
        return _find_frago_pid_via_lsof()
    return None


def _find_frago_pid_via_lsof() -> int | None:
    """Fallback: use lsof to find a frago process on SERVER_PORT (macOS)."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{SERVER_PORT}", "-t", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.strip().splitlines():
            pid = int(line.strip())
            try:
                proc = psutil.Process(pid)
                if is_frago_process(proc):
                    return pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def is_server_running() -> tuple[bool, int | None]:
    """Check if the Frago server is currently running.

    Uses PID file first, then falls back to port scanning for processes
    started via systemd or other external methods.

    Returns:
        Tuple of (is_running, pid). pid is None if not running.
    """
    # First, check PID file
    pid = read_pid()
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if proc.is_running() and is_frago_process(proc):
                return True, pid
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        # Stale PID file - clean up
        clear_pid()

    # Fallback: check for frago process on the port (e.g., systemd-started)
    port_pid = find_frago_process_on_port()
    if port_pid is not None:
        return True, port_pid

    return False, None


def get_server_uptime() -> float | None:
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


def check_port_available() -> tuple[bool, str | None]:
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
            # macOS: fall back to lsof for process identification
            pid = _find_frago_pid_via_lsof()
            if pid:
                try:
                    proc = psutil.Process(pid)
                    return False, f"{proc.name()} (PID: {pid})"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    return False, f"Unknown process (PID: {pid})"
        return False, "another process"


def start_daemon() -> tuple[bool, str]:
    """Start the Frago server as a background daemon.

    When systemd user service is enabled, delegates to systemctl.
    Otherwise uses platform-specific subprocess flags for daemonization.

    Returns:
        Tuple of (success, message)
    """
    if _is_systemd_managed():
        result = _systemctl("start")
        if result.returncode == 0:
            return True, f"Server started via systemd on http://{SERVER_HOST}:{SERVER_PORT}"
        return False, f"systemctl start failed: {result.stderr.strip()}"

    # Proactively clean up stale PID file from crashed processes
    cleanup_stale_pid()

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

    try:
        # Platform-specific subprocess creation
        if platform.system() == "Windows":
            # Windows: use pythonw.exe to avoid console window
            # Try multiple locations: venv Scripts, base Python install, shutil.which
            import shutil

            pythonw_candidates = [
                Path(sys.executable).parent / "pythonw.exe",  # Same dir as python.exe
                Path(sys.base_exec_prefix) / "pythonw.exe",   # Base Python install
            ]
            # Also try finding pythonw in PATH
            pythonw_in_path = shutil.which("pythonw")
            if pythonw_in_path:
                pythonw_candidates.append(Path(pythonw_in_path))

            executable = sys.executable  # Fallback to python.exe
            for pythonw in pythonw_candidates:
                if pythonw.exists():
                    executable = str(pythonw)
                    break

            cmd = [executable, "-m", "frago.server.runner", "--daemon"]

            # Open log file and keep it open (don't use 'with' block)
            # subprocess will inherit the handle
            log_f = open(log_file, "a")  # noqa: SIM115
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,  # Critical: close stdin to avoid console
                stdout=log_f,
                stderr=subprocess.STDOUT,
                **get_windows_subprocess_kwargs(detach=True),
            )
            # Close our handle - subprocess has its own copy
            log_f.close()
        else:
            # Unix: use start_new_session to detach from terminal
            cmd = [sys.executable, "-m", "frago.server.runner", "--daemon"]
            log_f = open(log_file, "a")  # noqa: SIM115
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            log_f.close()

        # Write PID file
        write_pid(proc.pid)

        return True, f"Frago server started on http://{SERVER_HOST}:{SERVER_PORT} (PID: {proc.pid})"

    except Exception as e:
        return False, f"Failed to start server: {e}"


def _get_self_and_ancestors() -> set:
    """Get PIDs of the current process and all its ancestors.

    Used to avoid killing the process that's calling stop_daemon()
    (e.g., an agent task running 'frago server restart').
    """
    protected = set()
    try:
        current = psutil.Process(os.getpid())
        protected.add(current.pid)
        for ancestor in current.parents():
            protected.add(ancestor.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return protected


def stop_daemon() -> tuple[bool, str]:
    """Stop the running Frago server daemon.

    When systemd user service is enabled, delegates to systemctl.
    Otherwise terminates the main process and all child processes.

    Returns:
        Tuple of (success, message)
    """
    if _is_systemd_managed():
        result = _systemctl("stop")
        if result.returncode == 0:
            clear_pid()
            return True, "Server stopped via systemd"
        return False, f"systemctl stop failed: {result.stderr.strip()}"

    running, pid = is_server_running()
    if not running or pid is None:
        return False, "Frago server is not running"

    try:
        proc = psutil.Process(pid)

        # Get all child processes before terminating parent,
        # excluding the current process and its ancestors to avoid
        # killing the caller (e.g., agent task running restart)
        protected_pids = _get_self_and_ancestors()
        children = [
            child for child in proc.children(recursive=True)
            if child.pid not in protected_pids
        ]

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
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                child.kill()

        # Clean up PID file
        clear_pid()

        return True, f"Frago server stopped (PID: {pid})"

    except psutil.NoSuchProcess:
        clear_pid()
        return True, f"Frago server stopped (PID: {pid})"
    except Exception as e:
        return False, f"Failed to stop server: {e}"


def _spawn_restarter_daemonized(server_pid: int) -> None:
    """Spawn restarter.py fully detached from the process tree via double fork.

    On Unix, uses double fork so the restarter is reparented to init/systemd,
    making it invisible to psutil.children(recursive=True). This is critical
    because the server's _cleanup_child_processes() kills all descendants on
    shutdown — a simple start_new_session=True Popen does NOT change the PPID.

    On Windows, uses DETACHED_PROCESS + CREATE_NO_WINDOW flags (no fork needed).
    """
    restarter_script = str(Path(__file__).parent / "restarter.py")
    log_file = str(get_log_file())

    if platform.system() == "Windows":
        log_f = open(log_file, "a")  # noqa: SIM115
        subprocess.Popen(
            [sys.executable, restarter_script, str(server_pid)],
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            **get_windows_subprocess_kwargs(detach=True),
        )
        log_f.close()
        return

    # Unix: double fork to fully detach from process tree
    first_child = os.fork()
    if first_child > 0:
        # Parent: wait for first child to exit (it exits immediately)
        os.waitpid(first_child, 0)
        return

    # First child: create new session and fork again
    os.setsid()
    second_child = os.fork()
    if second_child > 0:
        # First child exits immediately, second child is reparented to init
        os._exit(0)

    # Second child (grandchild): this is the actual restarter process,
    # now fully detached (PPID = 1/init, new session)
    try:
        # Redirect stdin/stdout/stderr
        devnull = os.open(os.devnull, os.O_RDWR)
        log_fd = os.open(log_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        os.dup2(devnull, 0)  # stdin
        os.dup2(log_fd, 1)   # stdout
        os.dup2(log_fd, 2)   # stderr
        os.close(devnull)
        os.close(log_fd)

        os.execvp(sys.executable, [sys.executable, restarter_script, str(server_pid)])
    except Exception:
        os._exit(1)


def restart_daemon(force: bool = False) -> tuple[bool, str]:
    """Restart the Frago server daemon.

    When systemd user service is enabled, delegates to systemctl restart.
    Otherwise spawns restarter.py via double fork then stops the server.

    Args:
        force: Force restart even if graceful shutdown fails

    Returns:
        Tuple of (success, message)
    """
    if _is_systemd_managed():
        print("[restart] Sending restart to systemd...")
        result = _systemctl("restart")
        if result.returncode != 0:
            return False, f"systemctl restart failed: {result.stderr.strip()}"
        print("[restart] systemd accepted restart, waiting for server...")
        ok, detail = _wait_for_healthy(timeout=60)
        if ok:
            print(f"[restart] Server is healthy ({detail})")
            return True, f"Server restarted via systemd ({detail})"
        print(f"[restart] Server failed health check: {detail}")
        return False, f"systemd restart issued but server unhealthy: {detail}"

    running, pid = is_server_running()

    if not running:
        # Server not running, just start it
        success, start_msg = start_daemon()
        return success, f"Server was not running. {start_msg}"

    # Spawn restarter fully detached from the process tree
    try:
        _spawn_restarter_daemonized(pid)
    except Exception as e:
        return False, f"Failed to launch restarter: {e}"

    # Now stop the server — the restarter will handle starting a new one
    success, stop_msg = stop_daemon()
    if not success and not force:
        return False, f"Failed to stop server: {stop_msg}"

    return True, f"Server restart initiated (old PID: {pid}). Restarter will start new instance."


def _is_pid_alive(pid: int | None) -> bool:
    """Check if a process with the given PID is still running."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def check_active_tasks() -> dict[str, Any]:
    """Check if there are active tasks that would be killed by server stop/restart.

    Checks TaskStore for EXECUTING tasks and verifies their PIDs are alive.
    Tasks whose PIDs are dead are auto-cleaned to FAILED (zombie recovery).

    Returns dict with keys: has_active, executing_tasks, message.
    """
    from frago.server.services.ingestion.models import TaskStatus
    from frago.server.services.ingestion.store import TaskStore

    result: dict[str, Any] = {
        "has_active": False,
        "executing_tasks": [],
        "message": "",
    }
    reasons: list[str] = []

    # Check EXECUTING tasks, verify PID liveness
    try:
        store = TaskStore()
        executing = store.get_by_status(TaskStatus.EXECUTING)
        zombie_count = 0
        for task in executing:
            if _is_pid_alive(task.pid):
                result["executing_tasks"].append({
                    "id": task.id,
                    "channel": task.channel,
                })
            else:
                # PID dead — auto-clean zombie task
                store.update_status(
                    task.id,
                    TaskStatus.FAILED,
                    error="zombie: process not found at restart check",
                )
                zombie_count += 1
        if result["executing_tasks"]:
            result["has_active"] = True
            reasons.append(f"{len(result['executing_tasks'])} task(s) executing")
        if zombie_count:
            reasons.append(f"{zombie_count} zombie task(s) auto-cleaned to FAILED")
    except Exception:
        pass  # TaskStore unreadable should not block guard

    if reasons:
        result["message"] = "Active tasks detected:\n" + "\n".join(
            f"  • {r}" for r in reasons
        )

    return result


def force_cleanup_active_tasks(report: dict[str, Any]) -> None:
    """Graceful cleanup before forced stop/restart.

    Marks EXECUTING tasks as FAILED.
    """
    from frago.server.services.ingestion.models import TaskStatus
    from frago.server.services.ingestion.store import TaskStore

    if report["executing_tasks"]:
        try:
            store = TaskStore()
            for task_info in report["executing_tasks"]:
                store.update_status(
                    task_info["id"],
                    TaskStatus.FAILED,
                    error="server force stop/restart",
                )
        except Exception:
            pass  # best-effort


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
