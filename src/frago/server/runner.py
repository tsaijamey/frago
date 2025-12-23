"""Uvicorn server runner for Frago Web Service.

Provides functions to start and manage the Uvicorn server
for hosting the Frago GUI web application.

Can be run as a module for daemon mode:
    python -m frago.server.runner --daemon
"""

import logging
import signal
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from typing import Optional

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
) -> None:
    """Start the Uvicorn server.

    Args:
        host: Host to bind to (default: 127.0.0.1 for security)
        port: Port to listen on (default: 8093)
        auto_open: Whether to auto-open browser
        auto_port: Whether to find available port if specified is in use
        log_level: Uvicorn log level

    Raises:
        RuntimeError: If no available port found
    """
    # Find available port if needed
    if auto_port and not is_port_available(port, host):
        logger.info(f"Port {port} is in use, finding available port...")
        port = find_available_port(port)
        logger.info(f"Using port {port}")

    # Update global server state
    started_at = datetime.now(timezone.utc).isoformat()
    set_server_state(host, port, started_at)

    # Import here to avoid circular import
    from frago.server.app import create_app
    app = create_app()

    # Get server URL
    url = get_server_url(host, port)

    # Print startup message
    print(f"\n  Frago Web Service")
    print(f"  ─────────────────────────────────")
    print(f"  Local:   {url}")
    print(f"  API:     {url}/api/docs")
    print(f"\n  Press Ctrl+C to stop\n")

    # Open browser if requested
    if auto_open:
        open_browser(url)

    # Configure and run Uvicorn
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=log_level == "debug",
        # Bind to localhost only for security
        # Users can use a reverse proxy for external access
    )

    server = uvicorn.Server(config)

    # Handle graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Shutting down server...")
        server.should_exit = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    finally:
        logger.info("Server shutdown complete")


def run_daemon_server() -> None:
    """Run the server in daemon mode.

    This function is called when running as a module for background mode.
    It sets up logging to file and runs the server without interactive features.
    """
    from pathlib import Path

    # Setup file logging for daemon mode
    log_file = Path.home() / ".frago" / "server.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), mode="a"),
        ],
    )

    logger.info(f"Starting Frago server daemon on http://{SERVER_HOST}:{SERVER_PORT}")

    run_server(
        host=SERVER_HOST,
        port=SERVER_PORT,
        auto_open=False,  # Don't open browser in daemon mode
        auto_port=False,  # Fixed port, no auto-find
        log_level="info",
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
