"""Frago server command group - Background web service management.

Provides commands to start, stop, and check status of the Frago
web service running as a background daemon process.
"""

import click


@click.group("server", invoke_without_command=True)
@click.option(
    "--debug",
    is_flag=True,
    help="Run in foreground with verbose logging (instead of background daemon)",
)
@click.pass_context
def server_group(ctx: click.Context, debug: bool) -> None:
    """Manage the Frago web service.

    By default, starts the server as a background daemon process
    on port 8093. Use --debug to run in foreground mode.

    \b
    Examples:
        frago server              # Start in background
        frago server --debug      # Start in foreground with logs
        frago server stop         # Stop the running server
        frago server restart      # Restart the server
        frago server status       # Check server status

    \b
    The server binds to 127.0.0.1:8093 (localhost only for security).
    Access the GUI at: http://127.0.0.1:8093
    """
    # If no subcommand is invoked, default to starting the server
    if ctx.invoked_subcommand is None:
        ctx.invoke(start, debug=debug)


@server_group.command("start")
@click.option(
    "--debug",
    is_flag=True,
    help="Run in foreground with verbose logging",
)
def start(debug: bool) -> None:
    """Start the Frago web service.

    Without --debug: Starts as background daemon, returns to prompt immediately.
    With --debug: Runs in foreground showing live logs (press Ctrl+C to stop).
    """
    if debug:
        # Foreground mode with verbose logging
        _run_foreground()
    else:
        # Background daemon mode
        _run_background()


def _run_background() -> None:
    """Start server as background daemon."""
    from frago.server.daemon import start_daemon

    success, message = start_daemon()
    click.echo(message)

    if not success:
        raise SystemExit(1 if "already running" in message.lower() else 2)


def _run_foreground() -> None:
    """Start server in foreground with verbose logging."""
    from frago.server.daemon import SERVER_HOST, SERVER_PORT, is_server_running
    from frago.server.runner import run_server

    # Check if already running in background
    running, pid = is_server_running()
    if running:
        click.echo(f"Note: Background server is running (PID: {pid})")
        click.echo("Starting debug server on same port will fail if port is in use.")
        click.echo()

    click.echo("  Frago Web Service (Debug Mode)")
    click.echo("  ─────────────────────────────────")
    click.echo(f"  Local:   http://{SERVER_HOST}:{SERVER_PORT}")
    click.echo(f"  API:     http://{SERVER_HOST}:{SERVER_PORT}/api/docs")
    click.echo()
    click.echo("  Press Ctrl+C to stop")
    click.echo()

    run_server(
        host=SERVER_HOST,
        port=SERVER_PORT,
        auto_open=False,  # Don't auto-open browser in debug mode
        auto_port=False,  # Don't find alternative port
        log_level="debug",
        reload=False,  # No reload for server command
    )


@server_group.command("stop")
def stop() -> None:
    """Stop the running Frago web service."""
    from frago.server.daemon import stop_daemon

    success, message = stop_daemon()
    click.echo(message)

    if not success:
        raise SystemExit(1)


@server_group.command("restart")
@click.option(
    "--force",
    is_flag=True,
    help="Force restart even if graceful shutdown fails",
)
def restart(force: bool) -> None:
    """Restart the Frago web service.

    Stops the running server and starts a new instance.
    If the server is not running, starts it.
    """
    from frago.server.daemon import restart_daemon

    success, message = restart_daemon(force=force)
    click.echo(message)

    if not success:
        raise SystemExit(1)


@server_group.command("status")
def status() -> None:
    """Check if the Frago web service is running."""
    from frago.server.daemon import get_server_status

    status_info = get_server_status()

    if status_info["running"]:
        click.echo("Frago server is running")
        click.echo(f"  PID:     {status_info['pid']}")
        click.echo(f"  URL:     {status_info['url']}")
        if status_info["uptime_formatted"]:
            click.echo(f"  Uptime:  {status_info['uptime_formatted']}")
    else:
        click.echo("Frago server is not running")
        raise SystemExit(1)
