"""Uvicorn server runner for Frago Web Service.

Provides functions to start and manage the Uvicorn server
for hosting the Frago GUI web application.
"""

import logging
import signal
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from typing import Optional

import uvicorn

from frago.server.utils import find_available_port, get_server_url, is_port_available, set_server_state

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
    host: str = "127.0.0.1",
    port: int = 8080,
    auto_open: bool = True,
    auto_port: bool = True,
    log_level: str = "info",
) -> None:
    """Start the Uvicorn server.

    Args:
        host: Host to bind to (default: 127.0.0.1 for security)
        port: Port to listen on (default: 8080)
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
