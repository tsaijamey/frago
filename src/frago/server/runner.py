"""Uvicorn server runner for Frago Web Service.

Provides functions to start and manage the Uvicorn server
for hosting the Frago GUI web application.

Can be run as a module for daemon mode:
    python -m frago.server.runner --daemon
"""

import contextlib
import logging
import signal
import sys
import threading
import webbrowser
from datetime import datetime

import uvicorn

from frago.server.utils import (
    SERVER_HOST,
    SERVER_PORT,
    find_available_port,
    get_server_url,
    is_port_available,
    set_server_state,
)

logger = logging.getLogger(__name__)


def open_browser(url: str, delay: float = 0.5) -> None:
    """Open the browser after a short delay.

    Args:
        url: URL to open
        delay: Delay in seconds before opening
    """
    import time

    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
            logger.info(f"Opened browser at {url}")
        except Exception as e:
            logger.warning(f"Failed to open browser: {e}")
            print(f"\nOpen your browser at: {url}")

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def run_server(
    host: str = SERVER_HOST,
    port: int = SERVER_PORT,
    auto_open: bool = True,
    auto_port: bool = True,
    log_level: str = "info",
    reload: bool = True,
) -> None:
    """Start the Uvicorn server.

    Args:
        host: Host to bind to (default: 127.0.0.1 for security)
        port: Port to listen on (default: 8093)
        auto_open: Whether to auto-open browser
        auto_port: Whether to find available port if specified is in use
        log_level: Uvicorn log level
        reload: Enable auto-reload on code changes (dev mode only)

    Raises:
        RuntimeError: If no available port found
    """
    # Configure Python logging for non-daemon mode (debug)
    # Daemon mode has its own file-based logging setup in start_daemon()
    if not logging.root.handlers:
        level = getattr(logging, log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            stream=sys.stderr,
        )

    # Port availability check
    if not is_port_available(port, host):
        if auto_port:
            logger.info(f"Port {port} is in use, finding available port...")
            port = find_available_port(port)
            logger.info(f"Using port {port}")
        else:
            # Fixed port mode (daemon): exit immediately before any expensive
            # initialization (PA session, ingestion, etc.) to avoid wasting
            # resources on every failed restart attempt.
            logger.error("Port %d is already in use, exiting immediately", port)
            sys.exit(1)

    # Detect and persist launcher info for frago-hook (Rust) to consume.
    # MUST run in the parent process before uvicorn reload forks a child
    # (child sys.argv[0] points to uvicorn internals, not the user command).
    try:
        from frago.init.launcher_detector import detect_launcher
        from frago.init.runtime_state import update_launcher

        launcher = detect_launcher()
        if launcher:
            update_launcher(launcher)
            logger.info(
                "Launcher detected: mode=%s command=%s",
                launcher.mode,
                launcher.command,
            )
        else:
            logger.warning(
                "Launcher detection failed; frago-hook will stay silent until next restart"
            )
    except Exception as e:
        logger.warning("Failed to persist launcher info: %s", e)

    # Ensure Claude Code hooks are installed
    try:
        from frago.init.resources import ensure_hooks
        installed = ensure_hooks()
        if installed:
            logger.info("Installed Claude Code hooks: %s", ", ".join(installed))
    except Exception as e:
        logger.warning("Failed to ensure hooks: %s", e)

    # Update global server state
    started_at = datetime.now().isoformat()
    set_server_state(host, port, started_at)

    # Get server URL
    url = get_server_url(host, port)

    # Print startup message
    print("\n  Frago Web Service")
    print("  ─────────────────────────────────")
    print(f"  Local:   {url}")
    print(f"  API:     {url}/api/docs")
    if reload:
        print("  Reload:  enabled")
    print("\n  Press Ctrl+C to stop\n")

    # Open browser if requested
    if auto_open:
        open_browser(url)

    # Configure Uvicorn
    # Note: reload requires app as import string, not instance
    if reload:
        config = uvicorn.Config(
            app="frago.server.app:create_app",
            factory=True,
            host=host,
            port=port,
            log_level=log_level,
            access_log=log_level == "debug",
            reload=True,
            reload_dirs=["src/frago"],
        )
    else:
        from frago.server.app import create_app
        app = create_app()
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level=log_level,
            access_log=log_level == "debug",
        )

    server = uvicorn.Server(config)

    # Handle graceful shutdown with child process cleanup
    def signal_handler(_signum, _frame):
        logger.info("Shutting down server...")
        server.should_exit = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        # Shut down background recipe executor (don't wait for running recipes)
        try:
            from frago.recipes.background import shutdown_executor
            shutdown_executor(wait=False)
        except Exception:
            pass
        # Clean up child processes (important for reload mode)
        _cleanup_child_processes()
        logger.info("Server shutdown complete")


def _cleanup_child_processes() -> None:
    """Terminate all child processes to release ports."""
    import os

    import psutil

    try:
        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)

        # Terminate children
        for child in children:
            try:
                if child.is_running():
                    child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Wait and force kill if needed
        gone, alive = psutil.wait_procs(children, timeout=2)
        for child in alive:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                child.kill()

        if children:
            logger.info(f"Cleaned up {len(children)} child process(es)")
    except Exception as e:
        logger.warning(f"Error cleaning up child processes: {e}")


def run_daemon_server() -> None:
    """Run the server in daemon mode.

    This function is called when running as a module for background mode.
    It sets up logging to file and runs the server without interactive features.
    """
    from pathlib import Path

    # Setup file logging for daemon mode
    log_file = Path.home() / ".frago" / "server.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    from logging.handlers import RotatingFileHandler

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                str(log_file), mode="a",
                maxBytes=5 * 1024 * 1024,  # 5MB per file
                backupCount=3,             # keep server.log.1 ~ .3
            ),
        ],
    )

    logger.info(f"Starting Frago server daemon on http://{SERVER_HOST}:{SERVER_PORT}")

    run_server(
        host=SERVER_HOST,
        port=SERVER_PORT,
        auto_open=False,  # Don't open browser in daemon mode
        auto_port=False,  # Fixed port, no auto-find
        log_level="info",
        reload=False,  # No reload in daemon mode
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Frago Web Service Runner")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    args = parser.parse_args()

    if args.daemon:
        run_daemon_server()
    else:
        # Default: run with auto-open browser
        run_server(
            host=SERVER_HOST,
            port=SERVER_PORT,
            auto_open=True,
            auto_port=False,
            log_level="info",
        )
