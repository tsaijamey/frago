"""Schedule management commands."""

import json

import click

from frago.server.services.scheduler_service import (
    SchedulerService,
    _parse_interval,
)


@click.group(name="schedule")
def schedule_group():
    """Manage scheduled tasks."""
    pass


@schedule_group.command(name="add")
@click.argument("recipe_name", required=False, default=None)
@click.option(
    "--every",
    default=None,
    help="Run interval: e.g. 30s, 10m, 2h (mutually exclusive with --cron)",
)
@click.option(
    "--cron",
    default=None,
    help="Cron expression: e.g. '0 8 * * *' (mutually exclusive with --every)",
)
@click.option("--name", default=None, help="Human-readable schedule name")
@click.option("--prompt", default=None, help="Task prompt for PA (what to do)")
@click.option("--params", default=None, help="JSON params for the recipe")
@click.option("--start", default=None, help="Start time (ISO 8601), default: now")
@click.option("--end", default=None, help="End time (ISO 8601), default: never")
@click.option(
    "--overlap",
    type=click.Choice(["skip", "queue"]),
    default="skip",
    help="Overlap control: skip (default) or queue",
)
@click.option("--timeout", type=int, default=300, help="Execution timeout in seconds (default: 300)")
def schedule_add(
    recipe_name: str | None,
    every: str | None,
    cron: str | None,
    name: str | None,
    prompt: str | None,
    params: str | None,
    start: str | None,
    end: str | None,
    overlap: str,
    timeout: int,
):
    """Add a scheduled task.

    Examples:
      frago schedule add my-recipe --every 10m
      frago schedule add --prompt "汇总昨天飞书消息" --cron "0 8 * * *" --name "每日飞书汇总"
      frago schedule add slow_recipe --every 30s --overlap skip
    """
    # Validate: --every and --cron are mutually exclusive, one is required
    if every and cron:
        click.echo("Error: --every and --cron are mutually exclusive. Use one or the other.")
        raise SystemExit(1)
    if not every and not cron:
        click.echo("Error: either --every or --cron is required.")
        raise SystemExit(1)

    # Must have either recipe_name or --prompt
    if not recipe_name and not prompt:
        click.echo("Error: either RECIPE_NAME or --prompt is required.")
        raise SystemExit(1)

    interval = None
    if every:
        try:
            interval = _parse_interval(every)
        except (ValueError, IndexError) as e:
            click.echo(f"Invalid interval: {every}. Use format like 30s, 10m, 2h")
            raise SystemExit(1) from e

    if cron:
        try:
            from croniter import croniter
            croniter(cron)  # validate expression
        except (ValueError, KeyError) as e:
            click.echo(f"Invalid cron expression: {e}")
            raise SystemExit(1) from e

    parsed_params = None
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid params JSON: {e}")
            raise SystemExit(1) from e

    # Verify recipe exists (if provided)
    if recipe_name:
        from frago.recipes.exceptions import RecipeError
        from frago.recipes.registry import get_registry

        registry = get_registry()
        try:
            registry.find(recipe_name)
        except RecipeError as e:
            click.echo(f"Recipe not found: {recipe_name}")
            raise SystemExit(1) from e

    service = SchedulerService.get_instance()
    schedule = service.add_schedule(
        recipe_name=recipe_name,
        interval_seconds=interval,
        params=parsed_params,
        start_at=start,
        end_at=end,
        name=name,
        prompt=prompt,
        cron=cron,
        overlap=overlap,
        timeout=timeout,
    )

    click.echo(f"Schedule created: {schedule['id']}")
    click.echo(f"  Name: {schedule['name']}")
    if recipe_name:
        click.echo(f"  Recipe: {recipe_name}")
    if prompt:
        click.echo(f"  Prompt: {prompt}")
    if every:
        click.echo(f"  Interval: {every} ({interval}s)")
    if cron:
        click.echo(f"  Cron: {cron}")
    click.echo(f"  Overlap: {overlap}")
    if start:
        click.echo(f"  Start: {start}")
    if end:
        click.echo(f"  End: {end}")
    click.echo("\nSchedule will be active when the frago server is running.")


@schedule_group.command(name="list")
def schedule_list():
    """List all scheduled tasks."""
    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    if not schedules:
        click.echo("No schedules configured.")
        return

    # Header
    click.echo(
        f"{'ID':<16} {'Enabled':<9} {'Name':<25} {'Schedule':<16} "
        f"{'Runs':<6} {'Last Status':<12} {'Next Run'}"
    )
    click.echo("-" * 120)

    for s in schedules:
        # Schedule expression
        cron_expr = s.get("cron")
        interval = s.get("interval_seconds")
        if cron_expr:
            schedule_str = cron_expr
        elif interval:
            if interval >= 3600:
                schedule_str = f"every {interval // 3600}h"
            elif interval >= 60:
                schedule_str = f"every {interval // 60}m"
            else:
                schedule_str = f"every {interval}s"
        else:
            schedule_str = "—"

        enabled = "✓" if s.get("enabled", True) else "✗"
        schedule_name = s.get("name", s.get("recipe_name", "—"))
        last_status = s.get("last_status", "—") or "—"
        run_count = s.get("run_count", 0)

        # Calculate next run
        next_run_dt = service._next_run_at(s)
        next_run = next_run_dt.strftime("%Y-%m-%d %H:%M:%S") if next_run_dt else "—"
        if not s.get("enabled", True):
            next_run = "(disabled)"

        click.echo(
            f"{s['id']:<16} {enabled:<9} {schedule_name:<25} {schedule_str:<16} "
            f"{run_count:<6} {last_status:<12} {next_run}"
        )


@schedule_group.command(name="remove")
@click.argument("schedule_id")
def schedule_remove(schedule_id: str):
    """Remove a schedule by ID."""
    service = SchedulerService.get_instance()
    if service.remove_schedule(schedule_id):
        click.echo(f"Schedule {schedule_id} removed.")
    else:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)


@schedule_group.command(name="toggle")
@click.argument("schedule_id")
def schedule_toggle(schedule_id: str):
    """Enable or disable a schedule."""
    service = SchedulerService.get_instance()
    result = service.toggle_schedule(schedule_id)
    if result is None:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)
    state = "enabled" if result else "disabled"
    click.echo(f"Schedule {schedule_id} is now {state}.")


@schedule_group.command(name="history")
@click.argument("schedule_id")
def schedule_history(schedule_id: str):
    """Show execution history for a schedule."""
    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    target = None
    for s in schedules:
        if s["id"] == schedule_id:
            target = s
            break

    if not target:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)

    history = target.get("history", [])
    if not history:
        click.echo(f"No execution history for {schedule_id}.")
        return

    click.echo(f"Execution history for {schedule_id} ({target.get('name', '')}):")
    click.echo(f"{'#':<4} {'Triggered At':<22} {'Status':<14} {'Task ID'}")
    click.echo("-" * 70)

    for i, entry in enumerate(reversed(history), 1):
        triggered = entry.get("triggered_at", "—")
        if triggered and triggered != "—":
            triggered = triggered[:19]
        status = entry.get("status", "—")
        task_id = entry.get("task_id") or "—"
        click.echo(f"{i:<4} {triggered:<22} {status:<14} {task_id}")


@schedule_group.command(name="run")
@click.argument("schedule_id")
def schedule_run(schedule_id: str):
    """Manually trigger a schedule once (does not affect regular schedule cycle)."""
    import asyncio

    service = SchedulerService.get_instance()
    schedules = service.list_schedules()

    target = None
    for s in schedules:
        if s["id"] == schedule_id:
            target = s
            break

    if not target:
        click.echo(f"Schedule {schedule_id} not found.")
        raise SystemExit(1)

    if not service._pa_enqueue:
        click.echo("Error: PA enqueue not available (server not running?).")
        raise SystemExit(1)

    click.echo(f"Triggering schedule {schedule_id} ({target.get('name', '')})...")
    try:
        asyncio.get_event_loop().run_until_complete(service._execute(target))
        click.echo("Message enqueued to PA.")
    except RuntimeError:
        # No running event loop — create one
        asyncio.run(service._execute(target))
        click.echo("Message enqueued to PA.")
