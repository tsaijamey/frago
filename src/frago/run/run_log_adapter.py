"""
Run log adapter.

Relocated from cli/commands.py: maps CLI-level status / action-type
strings to the run model enums and delegates to RunLogger.write_log.

This is an adapter layer (string -> enum mapping + delegation), not a
duplicate of RunLogger.  RunLogger itself is on the deprecated path
(being replaced by run/insights.py); this adapter keeps the CLI decoupled
from that detail.
"""

from pathlib import Path
from typing import Any, Dict, Optional


def get_run_logger(run_dir: Path):
    """Get logger for the given run directory."""
    try:
        from .logger import RunLogger
        return RunLogger(run_dir)
    except Exception:
        return None


def write_run_log(
    run_dir: Path,
    step: str,
    status: str,
    action_type: str = "other",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Write to run log (if a logger can be constructed for run_dir).

    Args:
        run_dir: Run directory to log into
        step: Step description
        status: Status (success/error/warning)
        action_type: Action type
        data: Additional data
    """
    logger = get_run_logger(run_dir)
    if not logger:
        return

    try:
        from .models import ActionType, ExecutionMethod, LogStatus

        # Map status
        status_map = {
            "success": LogStatus.SUCCESS,
            "error": LogStatus.ERROR,
            "warning": LogStatus.WARNING,
            "debug": LogStatus.SUCCESS,
        }
        log_status = status_map.get(status, LogStatus.SUCCESS)

        # Map action type
        action_map = {
            "navigation": ActionType.NAVIGATION,
            "interaction": ActionType.INTERACTION,
            "screenshot": ActionType.SCREENSHOT,
            "extraction": ActionType.EXTRACTION,
            "other": ActionType.OTHER,
        }
        log_action = action_map.get(action_type, ActionType.OTHER)

        logger.write_log(
            step=step,
            status=log_status,
            action_type=log_action,
            execution_method=ExecutionMethod.COMMAND,
            data=data or {},
        )
    except Exception:
        # Log write failure should not affect command execution
        pass
