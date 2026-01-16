"""Frago start command - User-friendly entry point.

Provides a simple 'frago start' command that launches the server
and opens the browser for immediate access to the Web UI.
"""

import platform
import subprocess
import webbrowser

import click


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
                click.echo("Opening browser...")
                if not open_browser(url):
                    click.echo(f"  Could not open browser. Visit: {url}")
        else:
            success, message = start_daemon()
            click.echo(message)

            if success and not no_browser:
                # Give server a moment to start before opening browser
                import time

                time.sleep(0.5)
                if not open_browser(url):
                    click.echo(f"  Could not open browser. Visit: {url}")
            elif not success:
                raise SystemExit(1)
