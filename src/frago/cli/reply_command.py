"""Reply command — lets Primary Agent send replies through ingestion channels.

Usage:
    frago reply --channel email --params '{"status": "completed", "result_summary": "...", "reply_context": {...}}'

This exposes the notify_recipe of a configured channel as a CLI command,
so the Primary Agent can proactively reply to message sources.
"""

import json
import sys
from pathlib import Path

import click

CONFIG_FILE = Path.home() / ".frago" / "config.json"


def _load_channel_notify_recipe(channel_name: str) -> str:
    """Look up the notify_recipe for a channel from config.json.

    Returns the recipe name or raises click.ClickException.
    """
    if not CONFIG_FILE.exists():
        raise click.ClickException("config.json not found")

    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise click.ClickException(f"Error reading config: {e}")

    channels = raw.get("task_ingestion", {}).get("channels", [])
    matched = next(
        (ch for ch in channels if ch.get("name") == channel_name), None
    )
    if matched is None:
        available = [ch.get("name", "?") for ch in channels]
        raise click.ClickException(
            f"Channel '{channel_name}' not found. Available: {available}"
        )

    notify_recipe = matched.get("notify_recipe")
    if not notify_recipe:
        raise click.ClickException(
            f"Channel '{channel_name}' has no notify_recipe configured"
        )
    return notify_recipe


@click.command(name="reply")
@click.option(
    "--channel",
    required=True,
    help="Channel name (must match a configured ingestion channel)",
)
@click.option(
    "--params",
    "params_str",
    default="{}",
    help="JSON params to pass to the notify recipe",
)
def reply_cmd(channel: str, params_str: str):
    """Send a reply through an ingestion channel's notify recipe."""
    notify_recipe = _load_channel_notify_recipe(channel)

    try:
        params = json.loads(params_str)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid params JSON: {e}")

    from frago.recipes import RecipeRunner

    runner = RecipeRunner()
    result = runner.run(notify_recipe, params=params)

    if result.get("success"):
        click.echo(f"Reply sent via {channel}")
    else:
        raise click.ClickException(
            f"Reply failed: {result.get('error', 'unknown error')}"
        )
