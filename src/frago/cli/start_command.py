"""Frago start command - User-friendly entry point.

Provides a simple 'frago start' command that launches the server
and opens the browser for immediate access to the Web UI.
"""

import logging
import platform
import subprocess
import time
import webbrowser

import click

logger = logging.getLogger(__name__)


def wait_for_server(url: str, timeout: int = 10) -> bool:
    """Wait for server to be ready by checking status endpoint.

    Args:
        url: Base URL of the server
        timeout: Maximum seconds to wait

    Returns:
        True if server is ready, False if timeout
    """
    import requests

    status_url = f"{url}/api/status"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(status_url, timeout=1)
            if response.status_code == 200:
                return True
        except (requests.RequestException, ConnectionError):
            pass
        time.sleep(0.3)

    return False


def open_browser(url: str) -> bool:
    """Open URL in default browser with cross-platform support.

    On Windows, webbrowser.open() can fail silently in some contexts.
    This function provides fallback mechanisms.

    Returns:
        True if browser was opened successfully, False otherwise.
    """
    system = platform.system()

    if system == "Windows":
        # On Windows, use start command which is more reliable
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", url],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.SubprocessError:
            pass

        # Fallback to webbrowser
        try:
            return webbrowser.open(url)
        except Exception:
            return False

    elif system == "Darwin":
        # macOS: use open command
        try:
            subprocess.run(["open", url], check=True, capture_output=True)
            return True
        except subprocess.SubprocessError:
            return webbrowser.open(url)

    else:
        # Linux and others: try xdg-open first, then webbrowser
        try:
            subprocess.run(
                ["xdg-open", url],
                check=True,
                capture_output=True,
                start_new_session=True,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return webbrowser.open(url)


def launch_chrome_app_mode(url: str) -> bool:
    """Launch URL in Chrome app mode (borderless window).

    This provides a native desktop app experience with:
    - Borderless window (no browser UI chrome)
    - Fixed window size (1280x960)
    - Auto-centered on screen
    - Window controls (minimize, maximize, close)

    Falls back to default browser if Chrome is not available or fails to launch.

    Args:
        url: URL to open in app mode

    Returns:
        True if Chrome app mode was launched successfully, False if fallback was used
    """
    try:
        from frago.cdp.commands.chrome import ChromeLauncher

        launcher = ChromeLauncher(
            app_mode=True,
            app_url=url,
            width=1280,
            height=960,
        )

        # Launch Chrome without killing existing instances
        # This allows users to have multiple frago windows open
        if launcher.launch(kill_existing=False):
            return True
        else:
            # Chrome found but CDP failed to start
            logger.warning("Chrome app mode failed to initialize, using default browser")
            return open_browser(url)

    except ImportError as e:
        # ChromeLauncher module not available (should not happen)
        logger.warning(f"ChromeLauncher not available: {e}")
        return open_browser(url)
    except Exception as e:
        # Chrome not found or other launch error
        logger.warning(f"Failed to launch Chrome app mode: {e}")
        return open_browser(url)


@click.command("start")
@click.option(
    "--no-browser",
    is_flag=True,
    help="Start server without opening browser",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Run in foreground with verbose logging (press Ctrl+C to stop)",
)
def start(no_browser: bool, debug: bool) -> None:
    """Start frago and open the Web UI in your browser.

    This is the main entry point for users. It starts the background
    server and opens the Web UI for immediate access.

    \b
    Examples:
        frago start              # Start server and open browser
        frago start --no-browser # Start server only
        frago start --debug      # Run in foreground with logs

    \b
    The Web UI handles first-time setup automatically with an
    initialization wizard if this is a fresh installation.
    """
    from frago.server.daemon import (
        SERVER_HOST,
        SERVER_PORT,
        is_server_running,
        start_daemon,
    )
    from frago.server.runner import run_server

    url = f"http://{SERVER_HOST}:{SERVER_PORT}"

    if debug:
        # Debug mode: run in foreground
        click.echo("  frago Web Service (Debug Mode)")
        click.echo("  " + "-" * 35)
        click.echo(f"  Local:   {url}")
        click.echo(f"  API:     {url}/api/docs")
        click.echo()
        click.echo("  Press Ctrl+C to stop")
        click.echo()

        run_server(
            host=SERVER_HOST,
            port=SERVER_PORT,
            auto_open=not no_browser,
            auto_port=False,
            log_level="debug",
            reload=False,
        )
    else:
        # Normal mode: start background daemon
        running, existing_pid = is_server_running()

        if running:
            click.echo(f"frago is already running (PID: {existing_pid})")
            click.echo(f"  URL: {url}")

            if not no_browser:
                click.echo("Opening in app mode...")
                if not launch_chrome_app_mode(url):
                    click.echo(f"  Opened in default browser: {url}")
        else:
            success, message = start_daemon()
            click.echo(message)

            if success and not no_browser:
                # Wait for server to be ready
                click.echo("Waiting for server to start...")
                if wait_for_server(url, timeout=10):
                    click.echo("Opening in app mode...")
                    if not launch_chrome_app_mode(url):
                        click.echo(f"  Opened in default browser: {url}")
                else:
                    click.echo("Warning: Server did not respond in time, opening anyway...")
                    if not launch_chrome_app_mode(url):
                        click.echo(f"  Opened in default browser: {url}")
            elif not success:
                raise SystemExit(1)
