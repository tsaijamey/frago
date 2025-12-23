"""
UI output module

Provides elegant terminal output tools, inspired by uv output style:
- Real-time progress updates
- Precise time display
- Clear status indicators
- Aligned output format
"""

import sys
import time
from contextlib import contextmanager
from typing import Optional

import click


class Spinner:
    """Simple spinner animation"""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = ""):
        self.message = message
        self.frame = 0
        self.is_tty = sys.stdout.isatty()

    def step(self) -> str:
        """Get next frame"""
        if not self.is_tty:
            return ""
        frame = self.FRAMES[self.frame % len(self.FRAMES)]
        self.frame += 1
        return frame

    def clear(self):
        """Clear current line"""
        if self.is_tty:
            click.echo("\r" + " " * 80 + "\r", nl=False)


class ProgressReporter:
    """Progress reporter - uv style output"""

    def __init__(self):
        self.start_time = time.time()
        self.is_tty = sys.stdout.isatty()

    def _elapsed_time(self) -> str:
        """Get elapsed time (milliseconds)"""
        elapsed = (time.time() - self.start_time) * 1000
        if elapsed < 1000:
            return f"{int(elapsed)}ms"
        else:
            return f"{elapsed / 1000:.1f}s"

    def step(self, message: str, spinner: Optional[Spinner] = None):
        """Display in-progress step (will be overwritten)"""
        if not self.is_tty:
            return

        frame = spinner.step() if spinner else ""
        output = f"\r{frame} {message}" if frame else f"\r{message}"
        click.echo(output + " " * 20, nl=False)

    def success(self, message: str, detail: Optional[str] = None):
        """Display success message (persistent)"""
        elapsed = self._elapsed_time()
        if detail:
            click.echo(f"\r{message} in {elapsed}")
            click.secho(f"  {detail}", dim=True)
        else:
            click.echo(f"\r{message} in {elapsed}")

    def info(self, message: str):
        """Display information (persistent)"""
        click.echo(f"\r{message}")

    def item_added(self, name: str, version: Optional[str] = None):
        """Display added item (uv style)"""
        if version:
            click.secho(f" + {name}=={version}", fg="green")
        else:
            click.secho(f" + {name}", fg="green")

    def item_skipped(self, name: str, reason: str = "already exists"):
        """Display skipped item"""
        click.secho(f" ~ {name}", fg="yellow", dim=True, nl=False)
        click.secho(f" ({reason})", dim=True)

    def item_error(self, name: str, error: str):
        """Display error item"""
        click.secho(f" [X] {name}", fg="red", nl=False)
        click.secho(f" - {error}", dim=True)


@contextmanager
def spinner_context(message: str, success_message: Optional[str] = None):
    """
    Spinner context manager

    Usage:
        with spinner_context("Checking dependencies", "Dependencies satisfied"):
            # Execute time-consuming operation
            pass
    """
    spinner = Spinner(message)
    reporter = ProgressReporter()
    start_time = time.time()

    if sys.stdout.isatty():
        # TTY mode: show spinner
        reporter.step(message, spinner)
        try:
            yield reporter
            # Success: display final message
            spinner.clear()
            elapsed = int((time.time() - start_time) * 1000)
            final_msg = success_message or message
            click.echo(f"{final_msg} in {elapsed}ms")
        except Exception as e:
            # Failure: clear and re-raise
            spinner.clear()
            raise e
    else:
        # Non-TTY mode: direct output
        click.echo(message)
        try:
            yield reporter
            if success_message:
                click.echo(success_message)
        except Exception:
            raise


def print_header(text: str):
    """Print paragraph header"""
    click.echo()
    click.secho(text, bold=True)


def print_section(title: str):
    """Print section title"""
    click.echo()
    click.secho(f"━━━ {title} ━━━", fg="cyan", bold=True)
    click.echo()


def print_summary(items: list[tuple[str, str]], title: str = "Summary"):
    """
    Print summary information (key-value pairs)

    Args:
        items: List of [(key, value), ...]
        title: Summary title
    """
    click.echo()
    click.secho(title, bold=True)
    click.echo()

    max_key_len = max(len(k) for k, _ in items) if items else 0

    for key, value in items:
        # Align key-value pairs
        padded_key = key.ljust(max_key_len)
        click.echo(f"  {padded_key}  {value}")

    click.echo()


def print_error(message: str, detail: Optional[str] = None):
    """Print error message"""
    click.secho(f"Error: {message}", fg="red", err=True)
    if detail:
        click.secho(f"  {detail}", dim=True, err=True)


def print_warning(message: str):
    """Print warning message"""
    click.secho(f"Warning: {message}", fg="yellow")


def confirm(message: str, default: bool = True) -> bool:
    """
    Simple confirmation prompt

    Args:
        message: Prompt message
        default: Default value

    Returns:
        User's choice
    """
    default_hint = "Y/n" if default else "y/N"
    return click.confirm(f"{message} [{default_hint}]", default=default, show_default=False)


def ask_question(
    question: str,
    header: str,
    options: list[dict],
    default_index: int = 0,
    multi_select: bool = False
) -> str:
    """
    Interactive menu (with arrow key navigation support)

    Args:
        question: Question description
        header: Menu title
        options: List of options, each containing label and description
        default_index: Default option index
        multi_select: Whether to allow multiple selection (not yet supported)

    Returns:
        Label of user's selected option

    Example:
        answer = ask_question(
            question="Which authentication method?",
            header="Auth",
            options=[
                {"label": "Default", "description": "Use current config"},
                {"label": "Custom", "description": "Configure API endpoint"}
            ]
        )
    """
    import questionary
    from questionary import Style

    # If not in interactive terminal, use default value
    if not sys.stdout.isatty():
        return options[default_index]["label"]

    # Custom style (simple style, similar to uv)
    custom_style = Style([
        ('qmark', 'fg:cyan bold'),           # Question mark
        ('question', 'bold'),                 # Question text
        ('answer', 'fg:cyan bold'),           # User answer
        ('pointer', 'fg:cyan bold'),          # Current option pointer >
        ('highlighted', 'fg:cyan bold'),      # Currently highlighted option
        ('selected', 'fg:green'),             # Selected items (multi-select)
        ('instruction', 'fg:#858585'),        # Instruction text (gray)
    ])

    # Display title
    click.echo()
    click.secho(f"━━━ {header} ━━━", fg="cyan", bold=True)
    click.echo()

    # Build questionary options (with descriptions)
    choices = []
    for i, opt in enumerate(options):
        # Format: "Label - Description" (single line display)
        display_text = f"{opt['label']} - {opt['description']}"
        choices.append(
            questionary.Choice(
                title=display_text,
                value=opt['label'],  # Return value uses only label
            )
        )

    # Use questionary.select
    try:
        answer = questionary.select(
            question,
            choices=choices,
            default=choices[default_index],  # Use Choice object as default value
            style=custom_style,
            use_shortcuts=True,
            use_indicator=True,
            instruction="(Use arrow keys, j/k, or number keys)"
        ).ask()
    except KeyboardInterrupt:
        # Use default value on Ctrl+C
        click.echo()
        click.secho("Using default option", dim=True)
        return options[default_index]["label"]

    return answer if answer else options[default_index]["label"]
