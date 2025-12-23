"""
Formatter Module

Provides standardized message formatting functionality:
- Error message formatting
- Success message formatting
- Dependency status formatting
- Progress prompts
"""

from typing import Dict, Optional

import click

from frago.init.models import DependencyCheckResult


# Color constants
class Colors:
    """ANSI Colors"""
    SUCCESS = "green"
    ERROR = "red"
    WARNING = "yellow"
    INFO = "blue"
    MUTED = "bright_black"


def format_error_message(
    title: str,
    details: Optional[str] = None,
    suggestion: Optional[str] = None,
) -> str:
    """
    Format error message

    Args:
        title: Error title
        details: Error details (optional)
        suggestion: Solution suggestion (optional)

    Returns:
        Formatted error message string
    """
    lines = [f"[X] {title}"]

    if details:
        lines.append("")
        for line in details.split("\n"):
            lines.append(f"   {line}")

    if suggestion:
        lines.append("")
        lines.append(f"[TIP] Suggestion: {suggestion}")

    return "\n".join(lines)


def format_success_message(
    title: str,
    details: Optional[str] = None,
) -> str:
    """
    Format success message

    Args:
        title: Success title
        details: Details (optional)

    Returns:
        Formatted success message string
    """
    lines = [f"[OK] {title}"]

    if details:
        lines.append(f"   {details}")

    return "\n".join(lines)


def format_warning_message(
    title: str,
    details: Optional[str] = None,
) -> str:
    """
    Format warning message

    Args:
        title: Warning title
        details: Details (optional)

    Returns:
        Formatted warning message string
    """
    lines = [f"[!]  {title}"]

    if details:
        lines.append(f"   {details}")

    return "\n".join(lines)


def format_info_message(title: str) -> str:
    """
    Format info message

    Args:
        title: Info title

    Returns:
        Formatted info message string
    """
    return f"ℹ️  {title}"


def format_dependency_status(results: Dict[str, DependencyCheckResult]) -> str:
    """
    Format dependency check status

    Args:
        results: Dependency check result dictionary

    Returns:
        Formatted status string
    """
    lines = ["Dependency Check Results:", ""]

    for name, result in results.items():
        if result.installed:
            status = "[OK]"
            version_info = f"v{result.version}" if result.version else "Installed"
        else:
            status = "[X]"
            version_info = "Not installed"

        display_name = format_dependency_name(name)
        lines.append(f"  {status} {display_name}: {version_info}")

        # Display version requirement warning
        if result.installed and not result.version_sufficient:
            lines.append(f"     [!]  Version requirement not met: requires >= {result.required_version}")

    return "\n".join(lines)


def format_dependency_name(name: str) -> str:
    """
    Format dependency name for display

    Args:
        name: Dependency internal name

    Returns:
        User-friendly display name
    """
    name_map = {
        "node": "Node.js",
        "claude-code": "Claude Code",
        "ccr": "Claude Code Router",
    }
    return name_map.get(name, name)


def format_progress(current: int, total: int, message: str) -> str:
    """
    Format progress information

    Args:
        current: Current step
        total: Total steps
        message: Progress message

    Returns:
        Formatted progress string
    """
    return f"[{current}/{total}] {message}"


def format_step_start(step_name: str) -> str:
    """
    Format step start message

    Args:
        step_name: Step name

    Returns:
        Formatted message
    """
    return f"📦 {step_name}..."


def format_step_complete(step_name: str) -> str:
    """
    Format step complete message

    Args:
        step_name: Step name

    Returns:
        Formatted message
    """
    return f"[OK] {step_name} completed"


def format_step_failed(step_name: str, error: Optional[str] = None) -> str:
    """
    Format step failed message

    Args:
        step_name: Step name
        error: Error message (optional)

    Returns:
        Formatted message
    """
    msg = f"[X] {step_name} failed"
    if error:
        msg += f"\n   {error}"
    return msg


def echo_error(title: str, details: Optional[str] = None, suggestion: Optional[str] = None) -> None:
    """
    Output error message (with color)

    Args:
        title: Error title
        details: Error details
        suggestion: Solution suggestion
    """
    click.secho(format_error_message(title, details, suggestion), fg=Colors.ERROR)


def echo_success(title: str, details: Optional[str] = None) -> None:
    """
    Output success message (with color)

    Args:
        title: Success title
        details: Details
    """
    click.secho(format_success_message(title, details), fg=Colors.SUCCESS)


def echo_warning(title: str, details: Optional[str] = None) -> None:
    """
    Output warning message (with color)

    Args:
        title: Warning title
        details: Details
    """
    click.secho(format_warning_message(title, details), fg=Colors.WARNING)


def echo_info(title: str) -> None:
    """
    Output info message (with color)

    Args:
        title: Info title
    """
    click.secho(format_info_message(title), fg=Colors.INFO)
