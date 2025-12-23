"""update command - self-update frago"""

import json
import subprocess
import sys
import urllib.request
from typing import Optional

import click

from frago.init.checker import compare_versions


PACKAGE_NAME = "frago-cli"  # PyPI package name
TOOL_NAME = "frago"  # CLI command name / entry point
REPO_URL = "git+https://github.com/tsaijamey/frago.git"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"


def is_tool_installed() -> bool:
    """Check if frago is installed via uv tool"""
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        # uv tool list displays entry point name, not package name
        return TOOL_NAME in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_current_version() -> str:
    """Get current version"""
    try:
        from frago import __version__
        return __version__
    except ImportError:
        return "unknown"


def get_latest_version() -> Optional[str]:
    """Get latest version from PyPI"""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
        return None


@click.command(name="update")
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    help="Only check for updates, do not perform update",
)
@click.option(
    "--reinstall",
    is_flag=True,
    help="Force reinstall",
)
@click.option(
    "--repo",
    "from_repo",
    is_flag=True,
    help="Install latest version from GitHub repository (instead of PyPI)",
)
def update(check_only: bool, reinstall: bool, from_repo: bool):
    """
    Update frago to the latest version

    Defaults to updating from PyPI, use --repo to install latest code from GitHub repository.

    \b
    Examples:
      frago update              # Update from PyPI
      frago update --repo       # Update from GitHub repository
      frago update --check      # Check if updates are available on PyPI
      frago update --reinstall  # Force reinstall
    """
    current_version = get_current_version()

    click.echo(f"Current version: {TOOL_NAME} v{current_version}")

    # Check if installed via uv tool
    if not is_tool_installed():
        click.echo()
        click.echo(f"Note: {TOOL_NAME} is not installed via uv tool", err=True)
        click.echo("If in development environment, please use git pull to update", err=True)
        click.echo()
        click.echo(f"Install as tool: uv tool install {PACKAGE_NAME}", err=True)
        sys.exit(1)

    if check_only:
        # Check latest version from PyPI
        click.echo("Checking for updates...")
        latest = get_latest_version()
        if latest:
            cmp = compare_versions(current_version, latest)
            if cmp >= 0:
                # Current version >= PyPI version
                if cmp > 0:
                    click.echo(f"Current is development version (v{current_version} > v{latest})")
                else:
                    click.echo(f"Already at latest version (v{current_version})")
            else:
                # Current version < PyPI version, update available
                click.echo(f"New version found: v{latest}")
                click.echo(f"Run 'frago update' to update")
        else:
            click.echo("Unable to check for updates (network issue or package not published)")
        return

    # Perform update
    if from_repo:
        click.echo(f"Updating from repository: {REPO_URL}")
    else:
        click.echo("Updating from PyPI...")
    click.echo()

    try:
        if from_repo:
            # Install from GitHub repository, needs --reinstall to overwrite existing installation
            cmd = ["uv", "tool", "install", "--reinstall", REPO_URL]
        else:
            # Update from PyPI
            cmd = ["uv", "tool", "upgrade", PACKAGE_NAME]
            if reinstall:
                cmd.append("--reinstall")

        # Execute directly, let output display to user
        result = subprocess.run(cmd)

        if result.returncode == 0:
            click.echo()
            click.echo(f"[OK] {TOOL_NAME} update completed")
        else:
            click.echo()
            click.echo(f"Update failed, exit code: {result.returncode}", err=True)
            sys.exit(result.returncode)

    except FileNotFoundError:
        click.echo("Error: uv command not found", err=True)
        click.echo("Please ensure uv is installed: https://docs.astral.sh/uv/", err=True)
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo("\nOperation cancelled")
        sys.exit(1)
