"""Task-ingestion channel management commands.

Maps 1:1 to fields on `TaskIngestionConfig` in init/models.py. All mutations
go through `load_config()` / `save_config()` so the CLI, Web Settings panel,
and init wizard stay in sync on the same JSON file.

After any mutation the user is reminded to restart the server — the
IngestionScheduler only reads config at boot.
"""

from __future__ import annotations

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup
from frago.init.config_manager import load_config, save_config
from frago.init.models import Config, TaskIngestionChannel
from frago.recipes.lookup import list_recipe_names, validate_recipe_exists


_RESTART_HINT = (
    "Restart server for changes to take effect:\n  uv run frago server restart"
)


def _find_channel(config: Config, name: str) -> TaskIngestionChannel | None:
    for ch in config.task_ingestion.channels:
        if ch.name == name:
            return ch
    return None


def _print_restart_hint() -> None:
    click.echo()
    click.secho(_RESTART_HINT, fg="cyan")


@click.group(name="channel", cls=AgentFriendlyGroup)
def channel_group() -> None:
    """Manage task ingestion channels (external task sources)."""


@channel_group.command(name="list", cls=AgentFriendlyCommand)
def channel_list() -> None:
    """List configured ingestion channels and global enabled state."""
    config = load_config()
    ti = config.task_ingestion

    state = "enabled" if ti.enabled else "disabled"
    click.secho(f"Task ingestion: {state}", fg="green" if ti.enabled else "yellow")

    if not ti.channels:
        click.echo("No channels configured.")
        click.echo("Add one with: frago channel add <name> --poll <recipe> --notify <recipe>")
        return

    click.echo()
    click.echo(f"{'NAME':<20} {'POLL RECIPE':<30} {'NOTIFY RECIPE':<30} {'INTERVAL':<10}")
    click.echo("-" * 95)
    for ch in ti.channels:
        click.echo(
            f"{ch.name:<20} {ch.poll_recipe:<30} {ch.notify_recipe:<30} {ch.poll_interval_seconds}s"
        )


@channel_group.command(name="add", cls=AgentFriendlyCommand)
@click.argument("name")
@click.option("--poll", "poll_recipe", required=True, help="Recipe that polls for new messages")
@click.option(
    "--notify", "notify_recipe", required=True, help="Recipe that sends replies back"
)
@click.option(
    "--interval",
    "interval",
    type=int,
    default=120,
    show_default=True,
    help="Poll interval in seconds",
)
@click.option(
    "--timeout",
    "timeout",
    type=int,
    default=20,
    show_default=True,
    help="Per-poll timeout in seconds",
)
def channel_add(
    name: str,
    poll_recipe: str,
    notify_recipe: str,
    interval: int,
    timeout: int,
) -> None:
    """Add a new ingestion channel."""
    config = load_config()

    if _find_channel(config, name) is not None:
        raise click.ClickException(f"Channel '{name}' already exists")

    try:
        validate_recipe_exists(poll_recipe)
        validate_recipe_exists(notify_recipe)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    try:
        new_channel = TaskIngestionChannel(
            name=name,
            poll_recipe=poll_recipe,
            notify_recipe=notify_recipe,
            poll_interval_seconds=interval,
            poll_timeout_seconds=timeout,
        )
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    config.task_ingestion.channels.append(new_channel)
    save_config(config)

    click.secho(f"[OK] Added channel '{name}'", fg="green")
    _print_restart_hint()


@channel_group.command(name="rm", cls=AgentFriendlyCommand)
@click.argument("name")
def channel_rm(name: str) -> None:
    """Remove an ingestion channel."""
    config = load_config()

    channel = _find_channel(config, name)
    if channel is None:
        raise click.ClickException(
            f"Channel '{name}' not found. Use `frago channel list` to see available channels."
        )

    config.task_ingestion.channels = [
        c for c in config.task_ingestion.channels if c.name != name
    ]
    save_config(config)

    click.secho(f"[OK] Removed channel '{name}'", fg="green")
    _print_restart_hint()


@channel_group.command(name="edit", cls=AgentFriendlyCommand)
@click.argument("name")
@click.option("--poll", "poll_recipe", default=None, help="New poll recipe")
@click.option("--notify", "notify_recipe", default=None, help="New notify recipe")
@click.option("--interval", "interval", type=int, default=None, help="New poll interval (seconds)")
@click.option("--timeout", "timeout", type=int, default=None, help="New poll timeout (seconds)")
def channel_edit(
    name: str,
    poll_recipe: str | None,
    notify_recipe: str | None,
    interval: int | None,
    timeout: int | None,
) -> None:
    """Edit an existing channel. Only provided flags are changed."""
    config = load_config()

    channel = _find_channel(config, name)
    if channel is None:
        raise click.ClickException(
            f"Channel '{name}' not found. Use `frago channel list` to see available channels."
        )

    if all(v is None for v in (poll_recipe, notify_recipe, interval, timeout)):
        raise click.ClickException(
            "Nothing to update. Provide at least one of --poll / --notify / --interval / --timeout."
        )

    updates: dict[str, object] = {}
    if poll_recipe is not None:
        try:
            validate_recipe_exists(poll_recipe)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        updates["poll_recipe"] = poll_recipe
    if notify_recipe is not None:
        try:
            validate_recipe_exists(notify_recipe)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        updates["notify_recipe"] = notify_recipe
    if interval is not None:
        updates["poll_interval_seconds"] = interval
    if timeout is not None:
        updates["poll_timeout_seconds"] = timeout

    try:
        new_channel = channel.model_copy(update=updates)
        # Re-validate via model construction (catches bad interval/timeout values).
        TaskIngestionChannel.model_validate(new_channel.model_dump())
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    config.task_ingestion.channels = [
        new_channel if c.name == name else c
        for c in config.task_ingestion.channels
    ]
    save_config(config)

    click.secho(f"[OK] Updated channel '{name}'", fg="green")
    _print_restart_hint()


@channel_group.command(name="enable", cls=AgentFriendlyCommand)
def channel_enable() -> None:
    """Enable task ingestion globally."""
    config = load_config()
    if config.task_ingestion.enabled:
        click.echo("Task ingestion is already enabled.")
        return
    config.task_ingestion.enabled = True
    save_config(config)
    click.secho("[OK] Task ingestion enabled", fg="green")
    _print_restart_hint()


@channel_group.command(name="disable", cls=AgentFriendlyCommand)
def channel_disable() -> None:
    """Disable task ingestion globally (channels remain configured)."""
    config = load_config()
    if not config.task_ingestion.enabled:
        click.echo("Task ingestion is already disabled.")
        return
    config.task_ingestion.enabled = False
    save_config(config)
    click.secho("[OK] Task ingestion disabled", fg="green")
    _print_restart_hint()


@channel_group.command(name="recipes", cls=AgentFriendlyCommand)
def channel_recipes() -> None:
    """List installed recipe names (candidates for --poll / --notify)."""
    names = list_recipe_names()
    if not names:
        click.echo("No recipes installed. Put recipes under ~/.frago/recipes/.")
        return
    for name in names:
        click.echo(name)
