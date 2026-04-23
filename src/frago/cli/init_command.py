"""
frago init command implementation

Provides interactive environment initialization features:
- Parallel dependency checking (Node.js, Claude Code)
- Smart installation of missing components
- Authentication method configuration (official vs custom endpoint)
- Configuration persistence and updates
"""

import sys
from typing import Dict, Optional

import click

from .agent_friendly import AgentFriendlyCommand

# ASCII Art Banner - using block characters for fill effect
FRAGO_BANNER = """\
███████╗██████╗  █████╗  ██████╗  ██████╗
██╔════╝██╔══██╗██╔══██╗██╔════╝ ██╔═══██╗
█████╗  ██████╔╝███████║██║  ███╗██║   ██║
██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║
██║     ██║  ██║██║  ██║╚██████╔╝╚██████╔╝
╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝
"""

# Gradient color configuration: transition from cyan to blue to purple
GRADIENT_COLORS = [
    (0, 255, 255),    # cyan
    (0, 191, 255),    # deep sky blue
    (65, 105, 225),   # royal blue
    (138, 43, 226),   # blue violet
    (148, 0, 211),    # dark violet
    (186, 85, 211),   # medium orchid
]


def _rgb_to_ansi(r: int, g: int, b: int) -> str:
    """Convert RGB to ANSI 256-color escape sequence"""
    return f"\033[38;2;{r};{g};{b}m"


def _interpolate_color(color1: tuple, color2: tuple, t: float) -> tuple:
    """Linear interpolation between two colors"""
    return tuple(int(c1 + (c2 - c1) * t) for c1, c2 in zip(color1, color2))


def _get_gradient_color(position: float) -> tuple:
    """Get gradient color based on position (0-1)"""
    if position >= 1.0:
        return GRADIENT_COLORS[-1]

    n = len(GRADIENT_COLORS) - 1
    idx = position * n
    lower_idx = int(idx)
    t = idx - lower_idx

    return _interpolate_color(GRADIENT_COLORS[lower_idx], GRADIENT_COLORS[lower_idx + 1], t)


def print_banner() -> None:
    """Print gradient ASCII art banner.

    Skipped on non-TTY stdout: the block characters (█╔═╗║╝╚) are UTF-8 but
    downstream pipe readers on Windows often decode with cp936/cp1252, producing
    mojibake. Branding is only meaningful in an interactive terminal anyway.
    """
    if not sys.stdout.isatty():
        return
    lines = FRAGO_BANNER.rstrip().split("\n")
    total_lines = len(lines)

    click.echo()
    for i, line in enumerate(lines):
        position = i / max(total_lines - 1, 1)
        r, g, b = _get_gradient_color(position)
        color_code = _rgb_to_ansi(r, g, b)
        reset_code = "\033[0m"
        click.echo(f"{color_code}{line}{reset_code}")
    click.echo()

from frago.init.checker import (
    parallel_dependency_check,
)
from frago.init.config_manager import load_config, save_config
from frago.init.configurator import (
    config_exists,
    display_config_summary,
    get_config_path,
    prompt_config_update,
    run_auth_configuration,
    warn_auth_switch,
)
from frago.init.exceptions import InitErrorCode
from frago.init.installer import install_claude_code_auto
from frago.init.models import Config, DependencyCheckResult
from frago.init.ui import (
    ProgressReporter,
    print_section,
    print_summary,
    spinner_context,
)


@click.command("init", cls=AgentFriendlyCommand)
@click.option(
    "--skip-deps",
    is_flag=True,
    help="Skip dependency check (only update configuration)",
)
@click.option(
    "--show-config",
    is_flag=True,
    help="Show current configuration and exit",
)
@click.option(
    "--reset",
    is_flag=True,
    help="Reset configuration (delete existing configuration and reinitialize)",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Non-interactive mode (use default values, suitable for CI/CD)",
)
def init(
    skip_deps: bool = False,
    show_config: bool = False,
    reset: bool = False,
    non_interactive: bool = False,
) -> None:
    """
    Initialize Frago development environment

    Check and install Claude Code via the official installer, then configure
    authentication and channel setup.
    """
    # Show configuration only
    if show_config:
        _show_current_config()
        sys.exit(InitErrorCode.SUCCESS)

    # Reset mode
    if reset:
        _handle_reset()

    # Print colored banner
    print_banner()
    print_section("Frago Environment Initialization")

    # Load existing configuration
    existing_config = load_config() if config_exists() else None

    # 1. Dependency check (Claude Code)
    deps_satisfied = True
    if not skip_deps:
        deps_satisfied = _check_and_install_dependencies(non_interactive)
    else:
        click.secho("Skipped dependency check", dim=True)
        click.echo()

    # 2. Configuration process
    if deps_satisfied:
        if not non_interactive:
            click.echo()  # Empty line separator
        config = _handle_configuration(existing_config, non_interactive)

        # 3. Optional channel wizard (mutates config.task_ingestion in place)
        from frago.init.channel_wizard import offer_channel_setup

        config = offer_channel_setup(config, non_interactive=non_interactive)

        # 4. Save configuration
        config.init_completed = True

        with spinner_context("Saving configuration", "Configuration saved"):
            save_config(config)

        # 5. Offer autostart configuration (unless non-interactive)
        if not non_interactive:
            _offer_autostart_configuration()

        # 6. Display completion summary
        _print_completion_summary(config)

    sys.exit(InitErrorCode.SUCCESS)


def _offer_autostart_configuration() -> None:
    """Offer to configure frago server autostart on system boot."""
    try:
        from frago.autostart import get_autostart_manager
        from frago.init.ui import ask_question

        manager = get_autostart_manager()
        is_enabled = manager.is_enabled()

        # Build options based on current state
        if is_enabled:
            options = [
                {
                    "label": "Keep enabled",
                    "description": "Keep autostart enabled (current setting)"
                },
                {
                    "label": "Disable",
                    "description": "Disable autostart on system boot"
                }
            ]
        else:
            options = [
                {
                    "label": "Enable",
                    "description": "Start frago server automatically on system boot"
                },
                {
                    "label": "Skip",
                    "description": "Configure later with 'frago autostart enable'"
                }
            ]

        answer = ask_question(
            question="Configure frago server autostart?",
            header="Autostart Configuration",
            options=options,
            default_index=0
        )

        # Handle user choice
        if answer == "Enable":
            success, message = manager.enable()
            if success:
                click.secho(f"✓ {message}", fg="green")
            else:
                click.secho(f"✗ {message}", fg="red")
        elif answer == "Disable":
            success, message = manager.disable()
            if success:
                click.secho(f"✓ {message}", fg="green")
            else:
                click.secho(f"✗ {message}", fg="red")
        elif answer == "Keep enabled":
            click.secho("✓ Autostart remains enabled", fg="green")
        else:  # Skip
            click.secho("Skipped autostart configuration", dim=True)
            click.echo("  Run 'frago autostart enable' to configure later")

    except NotImplementedError:
        # Platform not supported, silently skip
        pass
    except Exception as e:
        # Don't fail init if autostart fails
        click.secho(f"Warning: Could not configure autostart: {e}", fg="yellow")


def _print_completion_summary(config: Config) -> None:
    """
    Print initialization completion summary (uv style)

    Args:
        config: Configuration object
    """
    print_section("Initialization Complete")

    items = []

    # Dependency information
    if config.node_version:
        items.append(("Node.js", config.node_version))
    if config.claude_code_version:
        items.append(("Claude Code", config.claude_code_version))

    # Authentication method
    if config.auth_method == "official":
        items.append(("Authentication", "User configured"))
    else:
        endpoint_type = config.api_endpoint.type if config.api_endpoint else "custom"
        items.append(("Authentication", f"Frago managed ({endpoint_type})"))

    # Task ingestion channels
    channel_count = len(config.task_ingestion.channels)
    if channel_count:
        state = "enabled" if config.task_ingestion.enabled else "disabled"
        items.append(
            ("Ingestion channels", f"{channel_count} configured ({state})")
        )

    print_summary(items, "Configuration")

    click.secho("Run 'frago --help' to get started", fg="cyan")
    click.echo()


def _show_current_config() -> None:
    """Show current configuration and resource status"""
    if not config_exists():
        print_section("Frago Configuration")
        click.secho("Not initialized. Run 'frago init' to configure.", dim=True)
        click.echo()
        return

    config = load_config()
    print_section("Frago Configuration")
    click.echo(display_config_summary(config))
    click.echo()


def _handle_reset() -> None:
    """
    Handle configuration reset

    Delete existing configuration, allowing reinitialization
    """
    if not config_exists():
        click.secho("No configuration to reset", dim=True)
        click.echo()
        return

    config = load_config()
    print_section("Reset Configuration")
    click.secho("The following configuration will be removed:", fg="yellow")
    click.echo()
    click.echo(display_config_summary(config))
    click.echo()

    if not click.confirm("Confirm reset?", default=False):
        click.secho("Reset cancelled", dim=True)
        sys.exit(InitErrorCode.USER_CANCELLED)

    # Delete configuration file
    config_path = get_config_path()
    if config_path.exists():
        config_path.unlink()
        click.secho("Configuration reset successfully", fg="green")
        click.echo()


def _check_and_install_dependencies(non_interactive: bool = False) -> bool:
    """
    Check and install dependencies (Claude Code only)

    Args:
        non_interactive: Non-interactive mode

    Returns:
        True if all dependencies are satisfied or user chooses to skip installation
    """
    with spinner_context("Checking dependencies", "Resolved dependencies") as reporter:
        results = parallel_dependency_check()

    # Display check results - only show Claude Code, ignore Node.js
    reporter = ProgressReporter()
    claude_result = results.get("claude-code")
    if claude_result:
        if claude_result.installed:
            version = claude_result.version or "unknown"
            reporter.item_added("claude-code", version)
        else:
            reporter.item_error("claude-code", "not found")

    click.echo()

    # Get missing dependencies - only consider Claude Code
    missing = []
    if claude_result and claude_result.needs_install():
        missing.append("claude-code")

    if missing:
        _handle_missing_dependencies(results, missing, non_interactive)

    return True


def _handle_configuration(
    existing_config: Optional[Config],
    non_interactive: bool = False,
) -> Config:
    """
    Handle configuration process

    Args:
        existing_config: Existing configuration (if exists)
        non_interactive: Non-interactive mode

    Returns:
        Configured Config object
    """
    # Non-interactive mode: use default configuration (official authentication)
    if non_interactive:
        click.secho("Using default configuration", dim=True)
        if existing_config:
            return existing_config
        return Config(auth_method="official")

    if existing_config and existing_config.init_completed:
        # Have complete configuration, show summary and ask if update needed
        print_section("Current Configuration")
        click.echo(display_config_summary(existing_config))

        if not prompt_config_update():
            return existing_config

        # User chose to update, warn about authentication method switch
        current_method = existing_config.auth_method
        config = run_auth_configuration(existing_config)

        if config.auth_method != current_method:
            if not warn_auth_switch(current_method, config.auth_method):
                click.secho("Configuration update cancelled", dim=True)
                return existing_config

        return config
    else:
        # New configuration or incomplete configuration
        print_section("Configuration")
        config = run_auth_configuration(existing_config)

        return config


def _handle_missing_dependencies(
    results: Dict[str, DependencyCheckResult],
    missing: list[str],
    non_interactive: bool = False,
) -> None:
    """Handle missing dependencies.

    Claude Code is the only dependency init installs automatically. Non-Claude
    items in `missing` are surfaced for user visibility but not auto-installed.
    """
    click.echo("[!]  The following dependencies need to be installed:")
    for name in missing:
        result = results.get(name)
        if result:
            click.echo(f"  - {result.display_status()}")
    click.echo()

    if non_interactive:
        click.echo("Installing dependencies automatically (non-interactive mode)\n")
    elif not click.confirm("Install missing dependencies?", default=True):
        click.secho("Skipped dependency installation", dim=True)
        click.echo()
        return

    if "claude-code" in missing:
        _install_claude_code_with_progress()


def _install_claude_code_with_progress() -> None:
    """Install Claude Code via the official curl script, with graceful fallback.

    Does not raise or exit — init should keep going so the user still gets
    auth configuration and channel setup even if Claude Code install fails.
    The manual install hint (printed by `install_claude_code_auto` on failure)
    tells the user how to finish the job themselves.
    """
    click.echo("Installing Claude Code via official installer...")
    success, message = install_claude_code_auto()
    if success:
        click.echo("[OK] Claude Code installed successfully")
    else:
        click.secho(
            f"[!]  Claude Code install skipped: {message}",
            fg="yellow",
        )
    click.echo()


