"""Frago serve command - Web service GUI.

Starts a local HTTP web server for the Frago GUI,
allowing access through any modern browser.
"""

import click


@click.command("serve")
@click.option(
    "--port",
    "-p",
    type=int,
    default=8080,
    help="Port to listen on (default: 8080)",
)
@click.option(
    "--host",
    "-h",
    type=str,
    default="127.0.0.1",
    help="Host to bind to (default: 127.0.0.1 for security)",
)
@click.option(
    "--open/--no-open",
    default=True,
    help="Auto-open browser (default: --open)",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Enable debug mode with verbose logging",
)
def serve(port: int, host: str, open: bool, debug: bool) -> None:
    """Start the Frago web service GUI.

    Launches a local HTTP server that serves the Frago GUI
    through your web browser. This replaces the need for
    platform-specific GUI dependencies.

    \b
    Examples:
        frago serve              # Start on default port 8080
        frago serve -p 3000      # Start on port 3000
        frago serve --no-open    # Don't auto-open browser

    \b
    The server binds to 127.0.0.1 by default for security.
    Access the GUI at: http://127.0.0.1:8080
    """
    from frago.server.runner import run_server

    log_level = "debug" if debug else "info"

    run_server(
        host=host,
        port=port,
        auto_open=open,
        auto_port=True,  # Find available port if specified is in use
        log_level=log_level,
    )
