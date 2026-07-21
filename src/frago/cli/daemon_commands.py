"""Recipe daemon management commands (spec 20260624-recipe-daemon-supervisor).

The CLI face of the daemon supervisor. Capability lives in the recipe
(``metadata.daemon`` / ``metadata.restart_policy``, shipped with the recipe);
activation lives in ``config.json`` under a top-level ``daemons`` section
(per-host opt-in + override). These commands write that activation declaration
and surface runtime state.

Why raw JSON rather than ``load_config()`` / ``save_config()``: the ``daemons``
section is read directly as a raw dict by the server lifespan
(``app._start_daemon_service``) and is *not* a field on the ``Config`` pydantic
model. Round-tripping through ``Config`` would silently drop it. So daemon
declarations are read/written as raw JSON, mutating only the ``daemons`` key and
preserving every other top-level key untouched.

Cross-process note: the live supervisors run *inside* the server process. The
CLI is a separate process, so ``status``/``restart`` cannot reach them directly
without a server API endpoint (deferred to a later spec). ``status`` reads an
in-process ``DaemonService`` instance when one exists (same-process/test path),
otherwise falls back to reporting the config declaration plus whether the
server (their supervisor) is running. ``restart`` validates the declaration and
points the user at ``frago server restart``, which reloads daemons.
"""

from __future__ import annotations

import json

import click

from frago.cli.agent_friendly import AgentFriendlyCommand, AgentFriendlyGroup

_VALID_POLICIES = ("always", "on-failure", "never")

_RESTART_HINT = (
    "Restart server for changes to take effect:\n  frago server restart"
)


def _config_path():
    # Reference the module attribute at call time so tests can monkeypatch it.
    import frago.init.config_manager as cm

    return cm.CONFIG_PATH


def _load_raw() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise click.ClickException(f"Failed to read config.json: {e}") from e
    return data if isinstance(data, dict) else {}


def _save_raw(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _daemons_section(data: dict) -> dict:
    section = data.get("daemons")
    if not isinstance(section, dict):
        section = {"enabled": False, "items": []}
        data["daemons"] = section
    if not isinstance(section.get("items"), list):
        section["items"] = []
    return section


def _recipe_daemon_metadata(recipe_name: str):
    """Return the recipe's metadata, raising ClickException with actionable
    feedback when the recipe is missing or does not declare ``daemon: true``.
    """
    from frago.recipes.registry import get_registry

    try:
        recipe = get_registry().find(recipe_name)
    except Exception as e:
        raise click.ClickException(
            f"Recipe '{recipe_name}' not found under ~/.frago/recipes/ ({e})"
        ) from e

    metadata = recipe.metadata
    if not getattr(metadata, "daemon", False):
        raise click.ClickException(
            f"Recipe '{recipe_name}' does not declare 'daemon: true' in its metadata, "
            "so it cannot be supervised as a daemon. Only recipes meant to run as a "
            "long-lived background process should set daemon:true."
        )
    return metadata


def _print_restart_hint() -> None:
    click.echo()
    click.secho(_RESTART_HINT, fg="cyan")


def _find_item(section: dict, recipe_name: str) -> dict | None:
    for item in section["items"]:
        if isinstance(item, dict) and item.get("recipe") == recipe_name:
            return item
    return None


@click.group(name="daemon", cls=AgentFriendlyGroup)
def daemon_group() -> None:
    """Manage supervised recipe daemons (long-lived background recipes)."""


@daemon_group.command(name="enable", cls=AgentFriendlyCommand)
@click.argument("recipe")
@click.option(
    "--restart-policy",
    type=click.Choice(_VALID_POLICIES),
    default=None,
    help="Override the recipe's default restart policy.",
)
@click.option(
    "--max-backoff",
    type=int,
    default=None,
    help="Override the restart backoff ceiling (seconds).",
)
def daemon_enable(recipe: str, restart_policy: str | None, max_backoff: int | None) -> None:
    """Declare RECIPE as an active daemon (must declare daemon:true in metadata)."""
    metadata = _recipe_daemon_metadata(recipe)

    data = _load_raw()
    section = _daemons_section(data)
    section["enabled"] = True

    item = _find_item(section, recipe)
    if item is None:
        item = {"recipe": recipe, "enabled": True}
        section["items"].append(item)
    else:
        item["enabled"] = True
    if restart_policy is not None:
        item["restart_policy"] = restart_policy
    if max_backoff is not None:
        item["max_backoff"] = max_backoff

    _save_raw(data)

    effective_policy = item.get("restart_policy") or getattr(
        metadata, "restart_policy", "on-failure"
    )
    click.secho(f"[OK] Daemon '{recipe}' enabled (restart_policy={effective_policy})", fg="green")
    _print_restart_hint()


@daemon_group.command(name="disable", cls=AgentFriendlyCommand)
@click.argument("recipe")
def daemon_disable(recipe: str) -> None:
    """Remove RECIPE from the daemon declarations."""
    data = _load_raw()
    section = _daemons_section(data)

    if _find_item(section, recipe) is None:
        raise click.ClickException(
            f"Daemon '{recipe}' is not declared. Use `frago daemon ls` to list daemons."
        )

    section["items"] = [
        item for item in section["items"]
        if not (isinstance(item, dict) and item.get("recipe") == recipe)
    ]
    _save_raw(data)

    click.secho(f"[OK] Daemon '{recipe}' removed", fg="green")
    _print_restart_hint()


@daemon_group.command(name="ls", cls=AgentFriendlyCommand)
def daemon_ls() -> None:
    """List declared recipe daemons and their activation state."""
    data = _load_raw()
    section = data.get("daemons") or {}
    items = section.get("items") if isinstance(section, dict) else None
    items = items if isinstance(items, list) else []

    global_state = "enabled" if (isinstance(section, dict) and section.get("enabled")) else "disabled"
    click.secho(f"Daemon supervision: {global_state}", fg="green" if global_state == "enabled" else "yellow")

    if not items:
        click.echo("No daemons declared.")
        click.echo("Add one with: frago daemon enable <recipe>")
        return

    click.echo()
    click.echo(f"{'RECIPE':<30} {'ENABLED':<10} {'RESTART POLICY':<16}")
    click.echo("-" * 56)
    for item in items:
        if not isinstance(item, dict):
            continue
        recipe = item.get("recipe", "?")
        enabled = "yes" if item.get("enabled", True) else "no"
        policy = item.get("restart_policy", "(metadata default)")
        click.echo(f"{recipe:<30} {enabled:<10} {policy:<16}")


@daemon_group.command(name="status", cls=AgentFriendlyCommand)
def daemon_status() -> None:
    """Show runtime state of supervised daemons."""
    from frago.server.services.daemon_service import DaemonService

    instance = DaemonService.get_instance()
    if instance is not None:
        rows = instance.status()
        if not rows:
            click.echo("No daemons under supervision.")
            return
        click.echo(f"{'NAME':<24} {'PID':<8} {'ALIVE':<7} {'RESTARTS':<9} {'POLICY':<12}")
        click.echo("-" * 60)
        for r in rows:
            click.echo(
                f"{str(r.get('name')):<24} {str(r.get('pid') or '-'):<8} "
                f"{('yes' if r.get('alive') else 'no'):<7} "
                f"{str(r.get('restarts', 0)):<9} {str(r.get('restart_policy', '')):<12}"
            )
        return

    # No in-process supervisor — the live daemons (if any) run inside the server.
    from frago.server.daemon import is_server_running

    running, pid = is_server_running()
    data = _load_raw()
    section = data.get("daemons") or {}
    items = section.get("items") if isinstance(section, dict) else None
    items = items if isinstance(items, list) else []

    if not running:
        click.secho("Server is not running — no daemons are being supervised.", fg="yellow")
        click.echo("Start it with: frago server start")
    else:
        click.secho(f"Server is running (PID: {pid}); it supervises the declared daemons.", fg="green")
        click.echo("Live per-daemon pid/restarts are not yet exposed over the API.")

    if not items:
        click.echo("No daemons declared.")
        return
    click.echo()
    click.echo("Declared daemons:")
    for item in items:
        if not isinstance(item, dict):
            continue
        recipe = item.get("recipe", "?")
        enabled = "enabled" if item.get("enabled", True) else "disabled"
        click.echo(f"  - {recipe} ({enabled})")


@daemon_group.command(name="restart", cls=AgentFriendlyCommand)
@click.argument("recipe")
def daemon_restart(recipe: str) -> None:
    """Restart a declared daemon (applied by restarting the server)."""
    data = _load_raw()
    section = data.get("daemons") or {}
    items = section.get("items") if isinstance(section, dict) else None
    items = items if isinstance(items, list) else []

    declared = any(
        isinstance(item, dict) and item.get("recipe") == recipe for item in items
    )
    if not declared:
        raise click.ClickException(
            f"Daemon '{recipe}' is not declared. Use `frago daemon ls` to list daemons, "
            "or `frago daemon enable {recipe}` first."
        )

    click.secho(
        f"Daemon '{recipe}' is supervised inside the server process.", fg="cyan"
    )
    click.echo("To restart it, restart the server (reloads all daemons):")
    click.echo("  frago server restart")
