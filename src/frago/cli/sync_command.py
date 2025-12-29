"""sync command - Synchronize ~/.frago/ resources to your repository"""

import sys
from typing import Optional

import click

from frago.init.config_manager import load_config, save_config
from frago.tools.sync_repo import SyncResult, sync


def _format_result(result: SyncResult, dry_run: bool) -> None:
    """Format and output sync results"""
    # Warning messages (already output in real-time by sync(), not repeated here)

    # Conflict information
    if result.conflicts:
        click.echo()
        click.echo("[!]  Resource conflicts detected:")
        for conflict in result.conflicts:
            click.echo(f"  - {conflict}")
        click.echo()
        click.echo("Please manually resolve conflicts in ~/.frago/ directory and sync again")

    # Error messages
    if result.errors:
        click.echo()
        for error in result.errors:
            click.echo(f"[X] {error}", err=True)

    # Summary
    click.echo()
    if dry_run:
        click.echo("(Preview mode) The above operations will be executed in actual run")
    elif result.success:
        summary_parts = []
        if result.local_changes:
            summary_parts.append(f"Saved {len(result.local_changes)} local change(s)")
        if result.remote_updates:
            summary_parts.append(f"Fetched {len(result.remote_updates)} repository update(s)")
        if result.pushed_to_remote:
            summary_parts.append("Pushed to your repository")

        if summary_parts:
            click.echo(f"[OK] Sync completed: {' | '.join(summary_parts)}")
        else:
            click.echo("[OK] Sync completed: Local resources are already up to date")

        # Remind again if it's a public repository
        if result.is_public_repo:
            click.echo()
            click.echo("[!]  Reminder: Your sync repository is public. Please consider changing it to private to protect sensitive information.")
    else:
        click.echo("[X] Sync failed", err=True)


def _get_configured_repo_url() -> Optional[str]:
    """Get the configured repository URL"""
    config = load_config()
    return config.sync_repo_url


@click.command(name="sync")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Only preview operations to be executed, do not actually sync",
)
@click.option(
    "--no-push",
    is_flag=True,
    help="Only save local changes, do not push to your repository",
)
@click.option(
    "--message",
    "-m",
    type=str,
    help="Custom commit message",
)
@click.option(
    "--set-repo",
    type=str,
    help="Set repository URL",
)
def sync_cmd(
    dry_run: bool,
    no_push: bool,
    message: Optional[str],
    set_repo: Optional[str],
):
    """
    Synchronize local resources to your repository

    Sync Frago resources from ~/.frago/ and ~/.claude/ to the configured repository,
    enabling resource sharing across multiple devices.

    \b
    Sync workflow:
      1. Check local resource modifications to ensure no content is lost
      2. Fetch updates from your repository made on other devices
      3. Update local resources used by Claude Code
      4. Push local modifications to your repository

    \b
    First-time usage:
      frago sync --set-repo https://github.com/user/my-resources.git

    \b
    Daily usage:
      frago sync              # Sync resources
      frago sync --dry-run    # Preview what will be synced
      frago sync --no-push    # Only fetch updates, do not push

    \b
    Synced content:
      ~/.claude/skills/frago-*        # Skills
      ~/.frago/recipes/               # Recipes

    \b
    Authentication:
      It's recommended to use HTTPS URL with GitHub CLI (gh) authentication.
      Please run `gh auth login` to authenticate with GitHub first.
    """
    try:
        # Handle --set-repo
        if set_repo:
            config = load_config()
            config.sync_repo_url = set_repo
            save_config(config)
            click.echo(f"[OK] Repository configuration saved: {set_repo}")

            # If no other operations, return directly
            if not dry_run and not no_push and not message:
                return

        # Get repository URL
        repo_url = set_repo or _get_configured_repo_url()

        if not repo_url:
            click.echo("Error: Repository not configured", err=True)
            click.echo("")
            click.echo("Please configure repository first:", err=True)
            click.echo("  frago sync --set-repo https://github.com/user/my-resources.git", err=True)
            sys.exit(1)

        if dry_run:
            click.echo("=== Preview Mode ===")
            click.echo()

        result = sync(
            repo_url=repo_url,
            message=message,
            dry_run=dry_run,
            no_push=no_push,
        )

        _format_result(result, dry_run)

        if not result.success:
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
