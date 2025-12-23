"""
Interrupt Recovery Module

Provides graceful Ctrl+C interrupt handling and state recovery:
- GracefulInterruptHandler: Signal handler
- Temporary state save/load/delete
- Recovery prompts
"""

import json
import os
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import click

from frago.init.models import TemporaryState


# Temporary state expiry time (days)
TEMP_STATE_EXPIRY_DAYS = 7


def get_temp_state_path() -> Path:
    """
    Get temporary state file path

    Returns:
        Temporary state file path (~/.frago/.init_state.json)
    """
    return Path.home() / ".frago" / ".init_state.json"


def load_temp_state() -> Optional[TemporaryState]:
    """
    Load temporary state

    Returns:
        TemporaryState object, or None if not exists or expired
    """
    state_file = get_temp_state_path()

    if not state_file.exists():
        return None

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle datetime
        if "interrupted_at" in data and isinstance(data["interrupted_at"], str):
            data["interrupted_at"] = datetime.fromisoformat(data["interrupted_at"])

        state = TemporaryState(**data)

        # Check if expired
        if state.is_expired(days=TEMP_STATE_EXPIRY_DAYS):
            delete_temp_state()
            return None

        return state

    except (json.JSONDecodeError, TypeError, ValueError):
        # State file corrupted, delete it
        delete_temp_state()
        return None


def save_temp_state(state: TemporaryState) -> None:
    """
    Save temporary state

    Args:
        state: TemporaryState object
    """
    state_file = get_temp_state_path()

    # Ensure directory exists
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Serialize
    data = {
        "completed_steps": state.completed_steps,
        "current_step": state.current_step,
        "interrupted_at": state.interrupted_at.isoformat(),
        "recoverable": state.recoverable,
    }

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def delete_temp_state() -> bool:
    """
    Delete temporary state file

    Returns:
        True if successfully deleted or file does not exist
    """
    state_file = get_temp_state_path()

    try:
        if state_file.exists():
            state_file.unlink()
        return True
    except OSError:
        return False


def prompt_resume(state: TemporaryState) -> bool:
    """
    Ask user if they want to resume interrupted installation

    Args:
        state: TemporaryState object

    Returns:
        True if user chooses to resume
    """
    click.echo("\n[!]  Detected interrupted installation")
    click.echo(f"   Interrupted at: {state.interrupted_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if state.current_step:
        click.echo(f"   Interrupted step: {state.current_step}")

    # Show completed steps
    if state.completed_steps:
        click.echo("\n   Completed steps:")
        for step in state.completed_steps:
            click.echo(f"     [OK] {step}")

    click.echo()
    return click.confirm("Resume from interruption?", default=True)


def format_resume_summary(state: TemporaryState) -> str:
    """
    Format recovery summary

    Args:
        state: TemporaryState object

    Returns:
        Formatted summary string
    """
    lines = ["Recovery information:"]

    completed = len(state.completed_steps)
    if completed:
        lines.append(f"  Completed: {completed} steps")
    if state.current_step:
        lines.append(f"  Current step: {state.current_step}")

    return "\n".join(lines)


class GracefulInterruptHandler:
    """
    Graceful interrupt handler

    Used to capture Ctrl+C signal and perform cleanup operations

    Usage:
        with GracefulInterruptHandler() as handler:
            # Long-running operation
            if handler.interrupted:
                break
    """

    def __init__(self, on_interrupt: Optional[Callable[[], None]] = None):
        """
        Initialize interrupt handler

        Args:
            on_interrupt: Callback function to execute on interrupt
        """
        self.interrupted = False
        self.on_interrupt = on_interrupt
        self._original_handler = None

    def __enter__(self):
        self._original_handler = signal.signal(signal.SIGINT, self._handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.signal(signal.SIGINT, self._original_handler)
        return False

    def _handler(self, signum, frame):
        """Signal handler function"""
        self.interrupted = True
        if self.on_interrupt:
            self.on_interrupt()

        click.echo("\n\n[!]  Interrupt signal received, saving state...")


def create_initial_state() -> TemporaryState:
    """
    Create initial temporary state

    Returns:
        TemporaryState object
    """
    return TemporaryState(
        completed_steps=[],
        current_step=None,
        interrupted_at=datetime.now(),
        recoverable=True,
    )


def mark_step_completed(state: TemporaryState, step_name: str) -> None:
    """
    Mark step as completed

    Args:
        state: TemporaryState object
        step_name: Step name
    """
    state.add_step(step_name)


def set_current_step(state: TemporaryState, step_name: str) -> None:
    """
    Set current step

    Args:
        state: TemporaryState object
        step_name: Step name
    """
    state.set_current_step(step_name)
