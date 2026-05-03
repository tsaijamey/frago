#!/usr/bin/env python3
"""Independent restarter script for frago server.

This script is launched by UpdateService to restart the server
after an update. It runs as an independent process to:
1. Wait for the old server process to exit
2. Start a new server instance

Usage: python restarter.py <old_pid>
"""

import http.client
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def wait_for_process_exit(pid: int, timeout: float = 10.0) -> bool:
    """Wait for a process to exit.

    Args:
        pid: Process ID to wait for
        timeout: Maximum time to wait in seconds

    Returns:
        True if process exited, False if timeout
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            # Check if process exists
            if platform.system() == "Windows":
                # On Windows, use tasklist to check
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                )
                if str(pid) not in result.stdout:
                    return True
            else:
                # On Unix, send signal 0 to check if process exists
                os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            # Process doesn't exist - it has exited
            return True

        time.sleep(0.5)

    return False


def _wait_for_healthy(port: int = 8093, timeout: int = 30) -> tuple[bool, str]:
    """Poll /api/status until server responds 200 or timeout."""
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


def _is_systemd_managed() -> bool:
    """Check if frago-server.service is enabled via systemd."""
    if platform.system() != "Linux":
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "frago-server.service"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def start_new_server() -> bool:
    """Start a new frago server instance and write PID file.

    When systemd user service is enabled, delegates to systemctl restart
    instead of spawning a new process directly.

    Returns:
        True if server started successfully
    """
    # Delegate to systemd if managed
    if _is_systemd_managed():
        print("[restarter] systemd service detected, delegating to systemctl restart")
        result = subprocess.run(
            ["systemctl", "--user", "restart", "frago-server.service"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[restarter] systemctl restart failed: {result.stderr}")
            return False
        print("[restarter] systemd accepted restart, waiting for server...")
        ok, detail = _wait_for_healthy(port=8093, timeout=30)
        if ok:
            print(f"[restarter] Server is healthy ({detail})")
            return True
        print(f"[restarter] Server failed health check: {detail}")
        return False

    try:
        # Use the same Python that ran this script
        python_exe = sys.executable

        # On Windows, try to use pythonw to avoid console window
        if platform.system() == "Windows":
            pythonw = Path(python_exe).parent / "pythonw.exe"
            if pythonw.exists():
                python_exe = str(pythonw)

        # Start server as daemon
        cmd = [python_exe, "-m", "frago.server.runner", "--daemon"]

        # Ensure ~/.frago exists so the daemon child can open server.log there.
        (Path.home() / ".frago").mkdir(parents=True, exist_ok=True)

        # stdout/stderr → DEVNULL: the daemon configures its own
        # RotatingFileHandler. Letting the parent inherit an open server.log fd
        # to the child would block rotation on Windows (rename-on-open) and
        # bypass rotation for any non-logging write (uvicorn StreamHandler,
        # raw print, child subprocess stdout).
        if platform.system() == "Windows":
            CREATE_NO_WINDOW = 0x08000000
            DETACHED_PROCESS = 0x00000008
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # Write PID file so daemon.py can track the new server
        pid_file = Path.home() / ".frago" / "server.pid"
        pid_file.write_text(str(proc.pid))

        print(f"[restarter] New server started (PID: {proc.pid})")
        return True

    except Exception as e:
        print(f"[restarter] Failed to start server: {e}")
        return False


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python restarter.py <old_pid>")
        sys.exit(1)

    try:
        old_pid = int(sys.argv[1])
    except ValueError:
        print(f"Invalid PID: {sys.argv[1]}")
        sys.exit(1)

    print(f"[restarter] Waiting for old server (PID {old_pid}) to exit...")

    # Wait for old server to exit
    if not wait_for_process_exit(old_pid):
        print("[restarter] Warning: Old server did not exit within timeout")
        # Try to kill it
        try:
            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/PID", str(old_pid)],
                             capture_output=True)
            else:
                os.kill(old_pid, 9)  # SIGKILL
        except Exception:
            pass
        time.sleep(1)

    print("[restarter] Old server exited, starting new server...")

    # Small delay to ensure port is released
    time.sleep(1)

    # Start new server
    if start_new_server():
        print("[restarter] Server restart complete")
        sys.exit(0)
    else:
        print("[restarter] Failed to restart server")
        sys.exit(1)


if __name__ == "__main__":
    main()
