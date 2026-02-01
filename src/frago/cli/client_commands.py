"""CLI commands for frago desktop client management.

Commands:
    frago client status   - Show client installation status
    frago client start    - Start the desktop client (auto-download if needed)
    frago client update   - Update the client to latest version
    frago client uninstall - Remove the installed client
"""

import click

from frago import client_manager


@click.group(name="client")
def client_group():
    """Manage the frago desktop client.

    The desktop client is a Tauri-based application that provides
    a native desktop experience for frago. It connects to the local
    frago server via HTTP/WebSocket.

    \b
    Quick Start:
      frago client start    # Download (if needed) and launch the client

    The client is downloaded from GitHub Releases on first run.
    """
    pass


@client_group.command(name="status")
def client_status():
    """Show the desktop client installation status."""
    status = client_manager.get_status()

    if not status["supported"]:
        click.echo(f"⚠️  Platform not supported: {status['platform']} ({status['architecture']})")
        click.echo("Supported platforms: macOS (arm64, x86_64), Linux (x86_64), Windows (x86_64)")
        return

    click.echo("frago Desktop Client Status")
    click.echo("=" * 40)

    if status["installed"]:
        click.echo(f"✓ Installed: Yes")
        click.echo(f"  Version:   {status['installed_version']}")
        click.echo(f"  Location:  {status['client_path']}")

        if status["update_available"]:
            click.echo(f"\n⬆️  Update available: v{status['latest_version']}")
            click.echo("  Run 'frago client update' to update")
    else:
        click.echo("✗ Installed: No")
        click.echo("\n  Run 'frago client start' to download and install")

    if status["latest_version"]:
        click.echo(f"\nLatest version: v{status['latest_version']}")

    click.echo(f"\nPlatform: {status['platform']} ({status['architecture']})")
    click.echo(f"Install dir: {status['install_dir']}")


@client_group.command(name="start")
@click.option(
    "--no-download",
    is_flag=True,
    help="Don't download if not installed, just show error",
)
def client_start(no_download: bool):
    """Start the desktop client (downloads if not installed).

    This command will:
    1. Check if the client is installed
    2. Download from GitHub Releases if not installed (unless --no-download)
    3. Launch the desktop client
    4. The client connects to http://127.0.0.1:8093

    Note: Make sure 'frago server' is running before starting the client.
    """
    # Check if installed
    if not client_manager.is_installed():
        if no_download:
            click.echo("Client not installed. Use 'frago client start' without --no-download to install.")
            raise SystemExit(1)

        click.echo("Client not installed. Downloading...")
        if not client_manager.download_client():
            click.echo("Failed to download client.", err=True)
            raise SystemExit(1)

    # Launch the client
    click.echo("Starting frago client...")
    if client_manager.launch():
        click.echo("✓ Client started!")
        click.echo("\nMake sure 'frago server' is running.")
    else:
        click.echo("Failed to start client.", err=True)
        raise SystemExit(1)


@client_group.command(name="update")
@click.option(
    "--version",
    type=str,
    default=None,
    help="Specific version to install (e.g., '0.39.0')",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force reinstall even if already up to date",
)
def client_update(version: str, force: bool):
    """Update the desktop client to the latest version.

    Downloads and installs the latest client from GitHub Releases.
    Use --version to install a specific version.
    """
    status = client_manager.get_status()

    if not force and not version:
        # Check if update is needed
        if status["installed"] and not status["update_available"]:
            click.echo(f"Already up to date (v{status['installed_version']})")
            return

    click.echo("Updating frago client...")
    if client_manager.download_client(version=version):
        new_version = client_manager.get_installed_version()
        click.echo(f"✓ Updated to v{new_version}")
    else:
        click.echo("Failed to update client.", err=True)
        raise SystemExit(1)


@client_group.command(name="uninstall")
@click.confirmation_option(
    prompt="Are you sure you want to uninstall the frago client?"
)
def client_uninstall():
    """Remove the installed desktop client.

    \b
    Installation locations by platform:
    - macOS: ~/Applications/frago.app
    - Linux: ~/.local/bin/frago.AppImage
    - Windows: %LOCALAPPDATA%\\Programs\\frago\\

    You can reinstall anytime with 'frago client start'.
    """
    if client_manager.uninstall():
        click.echo("✓ Client uninstalled")
    else:
        click.echo("Failed to uninstall client.", err=True)
        raise SystemExit(1)
