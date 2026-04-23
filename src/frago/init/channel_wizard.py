"""Optional channel-setup prompt shown during `frago init`.

Lives in init/ rather than cli/ because it mutates a `Config` object in
memory — the surrounding init flow handles the actual `save_config()` call.
Never raises, never exits; any failure path returns the original config
unchanged and prints guidance on how the user can configure channels later.

Flow:
    non-interactive / non-TTY  → skip + pointer
    no recipes installed       → print "install a recipe first" hint
    interactive + recipes       → confirm → prompt name/poll/notify/interval
                                   → optionally set enabled=true
"""

from __future__ import annotations

import sys

import click

from frago.init.models import Config, TaskIngestionChannel
from frago.recipes.lookup import list_recipe_names


_SKIP_POINTER = (
    "  Skipped. Configure later with `frago channel add <name> --poll <recipe> "
    "--notify <recipe>` or via the Web Settings panel."
)


def offer_channel_setup(config: Config, *, non_interactive: bool) -> Config:
    """Interactive channel setup step. Mutates `config.task_ingestion` in place.

    Returns the same `Config` so the caller can chain into `save_config()`.
    All failure modes return the original config without changes.
    """
    if non_interactive or not sys.stdout.isatty():
        click.echo()
        click.echo(_SKIP_POINTER)
        return config

    available = list_recipe_names()
    if not available:
        _print_no_recipe_hint()
        return config

    existing = config.task_ingestion.channels
    if existing:
        click.echo()
        click.echo(
            f"Already configured: {', '.join(c.name for c in existing)}"
        )
        prompt_text = "Add another task ingestion channel?"
        default_yes = False
    else:
        prompt_text = "Configure a task ingestion channel?"
        default_yes = True

    if not click.confirm(prompt_text, default=default_yes):
        click.echo(_SKIP_POINTER)
        return config

    try:
        channel = _collect_channel_from_user(existing, available)
    except click.Abort:
        click.echo()
        click.echo("Wizard aborted. No channel was saved.")
        return config
    except Exception as e:
        click.secho(f"Channel wizard failed: {e}", fg="yellow")
        click.echo(_SKIP_POINTER)
        return config

    config.task_ingestion.channels.append(channel)

    if not config.task_ingestion.enabled:
        if click.confirm(
            "Enable task ingestion globally? (takes effect after server restart)",
            default=True,
        ):
            config.task_ingestion.enabled = True

    click.secho(f"[OK] Channel '{channel.name}' added", fg="green")
    return config


def _collect_channel_from_user(
    existing: list[TaskIngestionChannel],
    available_recipes: list[str],
) -> TaskIngestionChannel:
    taken = {c.name for c in existing}

    while True:
        name = click.prompt("Channel name (e.g. feishu, email)").strip()
        if not name:
            click.secho("Name cannot be empty.", fg="yellow")
            continue
        if name in taken:
            click.secho(f"Name '{name}' is already used.", fg="yellow")
            continue
        break

    poll = _pick_recipe(available_recipes, label="poll recipe (receives messages)")
    notify = _pick_recipe(
        available_recipes, label="notify recipe (sends replies)"
    )

    # Always prompt for interval / timeout with defaults visible; pressing Enter
    # accepts the default. Avoids the two-step "do you want to customise?" dead
    # end where answering No leaves the user with no way to revisit the value.
    interval = click.prompt("Poll interval (seconds)", type=int, default=120)
    timeout = click.prompt("Poll timeout (seconds)", type=int, default=20)

    return TaskIngestionChannel(
        name=name,
        poll_recipe=poll,
        notify_recipe=notify,
        poll_interval_seconds=interval,
        poll_timeout_seconds=timeout,
    )


def _pick_recipe(available_recipes: list[str], *, label: str) -> str:
    """Prompt the user to choose a recipe name.

    For large catalogs (208+ installed is typical), questionary.select becomes
    unwieldy. Use autocomplete — the user types a partial name and picks from
    filtered completions. Loops on unknown input so we never persist a bogus
    name.
    """
    import questionary

    while True:
        answer = questionary.autocomplete(
            f"Select {label}:",
            choices=available_recipes,
            ignore_case=True,
            validate=lambda v: v in available_recipes or "Unknown recipe",
            meta_information={},
        ).ask()
        if answer is None:
            # Ctrl+C inside the prompt — propagate so the wizard can abort cleanly
            raise click.Abort()
        if answer in available_recipes:
            return answer
        click.secho(
            f"'{answer}' is not an installed recipe. Try again.",
            fg="yellow",
        )


def _print_no_recipe_hint() -> None:
    click.echo()
    click.secho(
        "Task ingestion is available but no recipes are installed yet.",
        fg="yellow",
    )
    click.echo(
        "  Channels need two recipes: one that polls for incoming messages and"
    )
    click.echo(
        "  one that sends replies. Write or install them first, then:"
    )
    click.echo("    frago channel add <name> --poll <recipe> --notify <recipe>")
    click.echo()
