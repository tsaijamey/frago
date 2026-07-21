"""Uvicorn server runner for Frago Web Service.

Provides functions to start and manage the Uvicorn server
for hosting the Frago GUI web application.

Can be run as a module for daemon mode:
    python -m frago.server.runner --daemon
"""

import contextlib
import logging
import logging.config
import os
import signal
import sys
import threading
import webbrowser
from datetime import datetime
from typing import Any

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
    log_config: dict[str, Any] | None = None,
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
    print("  ---------------------------------")
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
    config_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": log_level == "debug",
    }
    # Pass log_config only when caller supplied one (daemon mode injects a
    # RotatingFileHandler-based dict). Omitting the kwarg lets uvicorn fall back
    # to its built-in stderr default — correct for foreground/dev mode.
    if log_config is not None:
        config_kwargs["log_config"] = log_config

    if reload:
        config = uvicorn.Config(
            app="frago.server.app:create_app",
            factory=True,
            reload=True,
            reload_dirs=["src/frago"],
            **config_kwargs,
        )
        primary_app = None  # reload forks workers; sidecar would orphan
    else:
        from frago.server.app import create_app
        primary_app = create_app()
        config = uvicorn.Config(app=primary_app, **config_kwargs)

    # Optional HTTPS sidecar (env-driven, additive — does NOT replace HTTP).
    # When FRAGO_SSL_CERTFILE + FRAGO_SSL_KEYFILE are both set to readable files,
    # we start a SECOND uvicorn.Server in a daemon thread sharing the SAME
    # FastAPI app, listening on FRAGO_SSL_PORT (default 8443). The primary
    # HTTP server on `port` stays exactly as-is — all existing recipes / scripts /
    # browser tabs that hit http://127.0.0.1:8093 keep working unchanged.
    # Only LAN / PWA / WSS consumers point at the new HTTPS port.
    #
    # Sidecar requires the primary app instance (sharing singletons / state).
    # Incompatible with reload mode → silently skipped if reload=True.
    if primary_app is not None:
        from frago.server.daemon import get_ssl_certfile, get_ssl_keyfile
        ssl_cert = get_ssl_certfile()
        ssl_key = get_ssl_keyfile()
        if ssl_cert and ssl_key:
            ssl_port = int(os.environ.get("FRAGO_SSL_PORT", "8443"))
            _start_https_sidecar(
                primary_app, host, ssl_port, ssl_cert, ssl_key, log_level, log_config,
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


def _start_https_sidecar(
    app,  # FastAPI app instance — MUST share with primary, not create a second one
    host: str,
    port: int,
    ssl_cert: str,
    ssl_key: str,
    log_level: str,
    log_config: dict[str, Any] | None,
) -> None:
    """Start a second uvicorn.Server for HTTPS, sharing the primary FastAPI app.

    Critical: the sidecar reuses the SAME app instance the primary uvicorn
    runs. Creating a second app via create_app() causes double initialization
    of singletons (state manager, sessions watcher, etc.) and dead-locks.
    """
    if not is_port_available(port, host):
        logger.warning(
            "FRAGO_SSL_PORT=%d is already in use; HTTPS sidecar not started", port
        )
        return

    cfg: dict[str, Any] = {
        "host": host,
        "port": port,
        "log_level": log_level,
        "access_log": log_level == "debug",
        "ssl_certfile": ssl_cert,
        "ssl_keyfile": ssl_key,
        # Critical: skip lifespan events. The primary uvicorn already ran
        # FastAPI's startup hooks (state manager init, sessions watcher, etc).
        # Running them again from this sidecar would double-init singletons
        # and dead-lock. The app's already-initialized state is fully shared.
        "lifespan": "off",
    }
    if log_config is not None:
        cfg["log_config"] = log_config

    def _run() -> None:
        try:
            srv = uvicorn.Server(uvicorn.Config(app=app, **cfg))
            logger.info(
                "HTTPS sidecar starting on https://%s:%d (cert=%s)",
                host, port, ssl_cert,
            )
            srv.run()
        except Exception as e:  # noqa: BLE001
            logger.error("HTTPS sidecar crashed: %s", e, exc_info=True)

    t = threading.Thread(target=_run, name="frago-https-sidecar", daemon=True)
    t.start()


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


def _build_daemon_log_config(log_file: str) -> dict[str, Any]:
    """Construct a uvicorn-compatible logging dictConfig backed by a single
    RotatingFileHandler.

    Why a single shared handler: two RotatingFileHandler instances pointing at
    the same file would race on rotation rename. Sharing one handler between
    root and the uvicorn loggers also keeps the file as the *only* writer to
    server.log, which is what makes rotation reliable on Windows (where
    rename-on-open fails if any other fd holds the file).
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            },
        },
        "handlers": {
            "rotating_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "mode": "a",
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 3,
                "encoding": "utf-8",
                "formatter": "default",
            },
        },
        "loggers": {
            # Uvicorn's default config attaches its own StreamHandler with
            # propagate=False; that path bypasses RotatingFileHandler entirely.
            # Re-route both loggers to the shared rotating handler.
            "uvicorn": {
                "handlers": ["rotating_file"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["rotating_file"],
                "level": "INFO",
                "propagate": False,
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["rotating_file"],
        },
    }


def run_daemon_server() -> None:
    """Run the server in daemon mode.

    This function is called when running as a module for background mode.
    It sets up rotating file logging and runs the server without interactive
    features. Stdin/stdout/stderr are expected to be DEVNULL'd by the parent
    spawner — this process owns server.log exclusively via Python logging.
    """
    from pathlib import Path

    from frago.server.launch_guard import assert_sanctioned_spawn, assert_system_install

    log_file = Path.home() / ".frago" / "server.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log_config = _build_daemon_log_config(str(log_file))
    logging.config.dictConfig(log_config)

    # Gate 1: refuse a raw `python -m frago.server.runner --daemon`. Must run
    # after logging is configured so the rejection lands in server.log.
    assert_sanctioned_spawn()

    # Gate 2 also holds at the daemon itself: paths that skip start_daemon
    # (e.g. a systemd unit generated from a repo venv) must still never run
    # the server out of the source checkout.
    assert_system_install()

    # Route uncaught exceptions through the rotating handler instead of the
    # process's stderr (which is /dev/null in daemon mode).
    from types import TracebackType

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("frago.daemon").critical(
            "Uncaught exception in daemon process",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _excepthook

    logger.info("Starting Frago server daemon on http://%s:%s", SERVER_HOST, SERVER_PORT)

    run_server(
        host=SERVER_HOST,
        port=SERVER_PORT,
        auto_open=False,  # Don't open browser in daemon mode
        auto_port=False,  # Fixed port, no auto-find
        log_level="info",
        reload=False,  # No reload in daemon mode
        log_config=log_config,
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
