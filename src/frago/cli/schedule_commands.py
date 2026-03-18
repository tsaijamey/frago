"""Recipe schedule management commands."""

import json
from typing import Optional

import click

from frago.server.services.recipe_scheduler_service import (
    RecipeSchedulerService,
    _parse_interval,
)


@click.group(name="schedule")
def schedule_group():
    """Manage scheduled recipe executions."""
    pass


@schedule_group.command(name="add")
@click.argument("recipe_name")
@click.option(
    "--every",
    required=True,
    help="Run interval: e.g. 30s, 10m, 2h",
)
@click.option("--params", default=None, help="JSON params for the recipe")
@click.option("--start", default=None, help="Start time (ISO 8601), default: now")
@click.option("--end", default=None, help="End time (ISO 8601), default: never")
def schedule_add(recipe_name: str, every: str, params: Optional[str], start: Optional[str], end: Optional[str]):
    """Add a scheduled recipe execution.

    Example: frago recipe schedule add my-recipe --every 10m
    """
    try:
        interval = _parse_interval(every)
    except (ValueError, IndexError):
        click.echo(f"Invalid interval: {every}. Use format like 30s, 10m, 2h")
        raise SystemExit(1)

    parsed_params = None
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid params JSON: {e}")
            raise SystemExit(1)

    # Verify recipe exists
    from frago.recipes.registry import get_registry
    from frago.recipes.exceptions import RecipeError

    registry = get_registry()
    try:
        registry.find(recipe_name)
    except RecipeError:
        click.echo(f"Recipe not found: {recipe_name}")
        raise SystemExit(1)

    service = RecipeSchedulerService.get_instance()
    schedule = service.add_schedule(
        recipe_name=recipe_name,
        interval_seconds=interval,
        params=parsed_params,
        start_at=start,
        end_at=end,
    )

    click.echo(f"Schedule created: {schedule['id']}")
    click.echo(f"  Recipe: {recipe_name}")
    click.echo(f"  Interval: {every} ({interval}s)")
    if start:
        click.echo(f"  Start: {start}")
    if end:
        click.echo(f"  End: {end}")
    click.echo(f"\nSchedule will be active when the frago server is running.")


@schedule_group.command(name="list")
def schedule_list():
    """List all scheduled recipes."""
    service = RecipeSchedulerService.get_instance()
    schedules = service.list_schedules()

    if not schedules:
        click.echo("No schedules configured.")
        return

    # Header
    click.echo(f"{'ID':<16} {'Enabled':<9} {'Recipe':<35} {'Interval':<12} {'Runs':<6} {'Last Status':<12} {'Last Run'}")
    click.echo("-" * 120)

    for s in schedules:
        interval = s.get("interval_seconds", 0)
        if interval >= 3600:
            interval_str = f"{interval // 3600}h"
        elif interval >= 60:
            interval_str = f"{interval // 60}m"
        else:
            interval_str = f"{interval}s"

        enabled = "✓" if s.get("enabled", True) else "✗"
        last_run = s.get("last_run_at", "—")
        if last_run and last_run != "—":
            last_run = last_run[:19]  # trim to readable
        last_status = s.get("last_status", "—") or "—"
        run_count = s.get("run_count", 0)

        click.echo(
            f"{s['id']:<16} {enabled:<9} {s['recipe_name']:<35} {interval_str:<12} {run_count:<6} {last_status:<12} {last_run}"
        )


@schedule_group.command(name="remove")
@click.argument("schedule_id")
def schedule_remove(schedule_id: str):
    """Remove a schedule by ID."""
    service = RecipeSchedulerService.get_instance()
    if service.remove_schedule(schedule_id):
        click.echo(f"Schedule {schedule_id} removed.")
    else:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)


@schedule_group.command(name="toggle")
@click.argument("schedule_id")
def schedule_toggle(schedule_id: str):
    """Enable or disable a schedule."""
    service = RecipeSchedulerService.get_instance()
    result = service.toggle_schedule(schedule_id)
    if result is None:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)
    state = "enabled" if result else "disabled"
    click.echo(f"Schedule {schedule_id} is now {state}.")
