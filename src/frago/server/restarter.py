#!/usr/bin/env python3
"""Independent restarter script for frago server.

This script is launched by UpdateService to restart the server
after an update. It runs as an independent process to:
1. Wait for the old server process to exit
2. Start a new server instance

Usage: python restarter.py <old_pid>
"""

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


def start_new_server() -> bool:
    """Start a new frago server instance.

    Returns:
        True if server started successfully
    """
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

        log_file = Path.home() / ".frago" / "server.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file, "a") as log_f:
            if platform.system() == "Windows":
                # Windows-specific flags
                CREATE_NO_WINDOW = 0x08000000
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                )
            else:
                subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )

        print(f"[restarter] New server started")
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
        print(f"[restarter] Warning: Old server did not exit within timeout")
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
