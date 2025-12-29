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
    """Print gradient ASCII art banner"""
    lines = FRAGO_BANNER.rstrip().split("\n")
    total_lines = len(lines)
    use_color = sys.stdout.isatty()

    click.echo()
    for i, line in enumerate(lines):
        if use_color:
            position = i / max(total_lines - 1, 1)
            r, g, b = _get_gradient_color(position)
            color_code = _rgb_to_ansi(r, g, b)
            reset_code = "\033[0m"
            click.echo(f"{color_code}{line}{reset_code}")
        else:
            click.echo(line)
    click.echo()

from frago.init.checker import (
    parallel_dependency_check,
    get_missing_dependencies,
    format_check_results,
)
from frago.init.installer import (
    get_installation_order,
    install_dependency,
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
from frago.init.models import Config, DependencyCheckResult
from frago.init.exceptions import CommandError, InitErrorCode
from frago.init.resources import (
    install_all_resources,
    format_install_summary,
    format_resources_status,
)
from frago.init.ui import (
    spinner_context,
    print_section,
    print_summary,
    ProgressReporter,
)


@click.command("init")
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
@click.option(
    "--skip-resources",
    is_flag=True,
    help="Skip resource installation (Claude Code commands and sample recipes)",
)
@click.option(
    "--update-resources",
    is_flag=True,
    help="Force update all resources (including overwriting existing recipes)",
)
def init(
    skip_deps: bool = False,
    show_config: bool = False,
    reset: bool = False,
    non_interactive: bool = False,
    skip_resources: bool = False,
    update_resources: bool = False,
) -> None:
    """
    Initialize Frago development environment

    Check and install necessary dependencies (Node.js, Claude Code),
    configure authentication method and related settings.
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

    # 1. Dependency check
    deps_satisfied = True
    if not skip_deps:
        deps_satisfied = _check_and_install_dependencies(non_interactive)
    else:
        click.secho("Skipped dependency check", dim=True)
        click.echo()

    # 2. Install resource files (Claude Code commands and sample recipes)
    resources_success = False
    if deps_satisfied and not skip_resources:
        resources_success = _install_resources(force_update=update_resources)
    elif skip_resources:
        click.secho("Skipped resource installation", dim=True)
        click.echo()

    # 3. Configuration process
    if deps_satisfied:
        if not non_interactive:
            click.echo()  # Empty line separator
        config = _handle_configuration(existing_config, non_interactive)

        # 4. Update resource installation status and save configuration
        config.init_completed = True
        if resources_success:
            from datetime import datetime
            from frago import __version__
            config.resources_installed = True
            config.resources_version = __version__
            config.last_resource_update = datetime.now()

        with spinner_context("Saving configuration", "Configuration saved"):
            save_config(config)

        # 5. Display completion summary
        _print_completion_summary(config)

    sys.exit(InitErrorCode.SUCCESS)


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
    Check and install dependencies

    Args:
        non_interactive: Non-interactive mode

    Returns:
        True if all dependencies are satisfied or user chooses to skip installation
    """
    with spinner_context("Checking dependencies", "Resolved dependencies") as reporter:
        results = parallel_dependency_check()

    # Display check results
    reporter = ProgressReporter()
    for name, result in results.items():
        if result.installed:
            version = result.version or "unknown"
            reporter.item_added(name, version)
        else:
            reporter.item_error(name, "not found")

    click.echo()

    # Get missing dependencies
    missing = get_missing_dependencies(results)

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
    """
    Handle missing dependencies

    Args:
        results: Dependency check results
        missing: List of missing dependencies
        non_interactive: Non-interactive mode
    """
    # Display missing information
    click.echo("[!]  The following dependencies need to be installed:")
    for name in missing:
        result = results.get(name)
        if result:
            click.echo(f"  - {result.display_status()}")
    click.echo()

    # Non-interactive mode: auto install
    if non_interactive:
        click.echo("Installing dependencies automatically (non-interactive mode)\n")
    elif not click.confirm("Install missing dependencies?", default=True):
        click.secho("Skipped dependency installation", dim=True)
        click.echo()
        return

    # Install in order
    node_needed = "node" in missing
    claude_code_needed = "claude-code" in missing
    install_order = get_installation_order(node_needed, claude_code_needed)

    click.echo()

    # Track whether Node.js was just installed and npm is not in PATH
    node_installed_needs_activation = False

    for name in install_order:
        # For claude-code: if node was just installed and npm is unavailable, use nvm fallback
        use_nvm = node_installed_needs_activation and name == "claude-code"

        requires_restart = _install_with_progress(
            name,
            use_nvm_fallback=use_nvm,
            node_just_installed=node_installed_needs_activation,
        )

        if name == "node" and requires_restart:
            # Node.js installed successfully but npm is not in PATH
            node_installed_needs_activation = True

            # Check if there are remaining dependencies
            remaining = install_order[install_order.index(name) + 1:]
            if remaining:
                # Try to install remaining dependencies using nvm fallback instead of requiring restart
                click.echo()
                click.secho(
                    "npm not yet active in current terminal, attempting to continue installation via nvm environment...",
                    fg="cyan",
                )
                continue

        # If not node, but requires restart (shouldn't happen in theory)
        if requires_restart and name != "node":
            _show_restart_required_message([])
            sys.exit(0)


def _show_restart_required_message(remaining_deps: list) -> None:
    """
    Display terminal restart required message

    Args:
        remaining_deps: Remaining dependencies to install
    """
    from frago.init.installer import _get_shell_config_file

    click.echo()
    click.secho("[!]  Node.js installed, but needs to be activated to continue", fg="yellow")
    click.echo()

    shell_config = _get_shell_config_file()
    if shell_config:
        click.echo("Please perform one of the following operations:")
        click.echo()
        click.echo(f"  1. Activate current terminal (recommended):")
        click.echo(f"     source {shell_config}")
        click.echo()
        click.echo("  2. Restart terminal")
        click.echo()
    else:
        click.echo("Please restart terminal or run:")
        click.echo("    source ~/.nvm/nvm.sh")
        click.echo()

    click.echo("Then run again:")
    click.secho("    frago init", fg="cyan")
    click.echo()

    remaining_names = ", ".join(
        "Claude Code" if d == "claude-code" else d for d in remaining_deps
    )
    click.echo(f"(Remaining dependencies: {remaining_names})")


def _install_with_progress(
    name: str,
    use_nvm_fallback: bool = False,
    node_just_installed: bool = False,
) -> bool:
    """
    Installation with progress indication

    Args:
        name: Dependency name
        use_nvm_fallback: For claude-code, whether to use nvm environment when npm is unavailable
        node_just_installed: Whether Node.js was just installed (for error messages)

    Returns:
        requires_restart: Whether terminal restart is required to continue
    """
    display_name = "Node.js" if name == "node" else "Claude Code"

    click.echo(f"Installing {display_name}...")

    try:
        success, warning, requires_restart = install_dependency(
            name,
            use_nvm_fallback=use_nvm_fallback,
        )
        click.echo(f"[OK] {display_name} installed successfully")

        # Display Windows PATH warning (if any)
        if warning:
            click.secho(warning, fg="yellow")

        click.echo()
        return requires_restart

    except CommandError as e:
        click.echo(f"\n[X] {display_name} installation failed")
        click.echo(str(e))

        # If npm is unavailable due to just installing Node.js, give more friendly message
        if name == "claude-code" and node_just_installed:
            click.echo()
            _show_restart_required_message(["claude-code"])

        sys.exit(e.code)


def _install_resources(force_update: bool = False) -> bool:
    """
    Install resource files (Claude Code commands and sample recipes)

    Args:
        force_update: Force update all resources (overwrite existing recipes)

    Returns:
        True if resource installation succeeded (no errors)

    Called after dependency check, before configuration
    """
    try:
        with spinner_context("Installing resources", "Installed resources") as reporter:
            status = install_all_resources(force_update=force_update)

        # Display installation details (uv style)
        reporter = ProgressReporter()

        # Commands
        if status.commands:
            for name in status.commands.installed:
                reporter.item_added(name)
            for error in status.commands.errors:
                click.secho(f" [X] {error}", fg="red")

        # Skills
        if status.skills:
            for name in status.skills.installed:
                reporter.item_added(f"skill/{name}")
            for name in status.skills.skipped:
                reporter.item_skipped(f"skill/{name}")

        # Recipes
        if status.recipes:
            for name in status.recipes.installed:
                reporter.item_added(f"recipe/{name}")
            for name in status.recipes.skipped:
                reporter.item_skipped(f"recipe/{name}")

        click.echo()

        # Check for errors
        if not status.all_success:
            click.secho("Warning: Some resources failed to install", fg="yellow")
            return False

        return True

    except Exception as e:
        click.secho(f"Error: Resource installation failed - {e}", fg="red", err=True)
        click.secho("  Ensure write permissions for ~/.claude/ and ~/.frago/", dim=True, err=True)
        return False
