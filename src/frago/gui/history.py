"""History persistence for Frago GUI.

Handles loading and saving command history to ~/.frago/gui_history.jsonl.
"""

import json
from pathlib import Path
from typing import List, Optional

from frago.gui.config import ensure_config_dir
from frago.gui.models import CommandRecord, CommandType, TaskStatus

HISTORY_FILE = Path.home() / ".frago" / "gui_history.jsonl"


def append_record(record: CommandRecord) -> None:
    """Append a command record to history.

    Args:
        record: CommandRecord to append.
    """
    ensure_config_dir()
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def get_history(
    limit: int = 50,
    offset: int = 0,
    command_type: Optional[CommandType] = None,
    status: Optional[TaskStatus] = None,
) -> List[CommandRecord]:
    """Get command history with optional filtering.

    Args:
        limit: Maximum number of records to return.
        offset: Number of records to skip.
        command_type: Filter by command type.
        status: Filter by task status.

    Returns:
        List of CommandRecord instances.
    """
    if not HISTORY_FILE.exists():
        return []

    records = []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    record = CommandRecord.from_dict(data)

                    if command_type and record.command_type != command_type:
                        continue
                    if status and record.status != status:
                        continue

                    records.append(record)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
    except OSError:
        return []

    records.reverse()
    return records[offset : offset + limit]


def get_history_count(
    command_type: Optional[CommandType] = None,
    status: Optional[TaskStatus] = None,
) -> int:
    """Get total count of history records.

    Args:
        command_type: Filter by command type.
        status: Filter by task status.

    Returns:
        Total count of matching records.
    """
    if not HISTORY_FILE.exists():
        return 0

    count = 0
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if command_type and data.get("command_type") != command_type.value:
                        continue
                    if status and data.get("status") != status.value:
                        continue
                    count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
    except OSError:
        return 0

    return count


def clear_history() -> int:
    """Clear all history records.

    Returns:
        Number of records cleared.
    """
    if not HISTORY_FILE.exists():
        return 0

    count = get_history_count()
    HISTORY_FILE.unlink()
    return count


def trim_history(max_items: int) -> int:
    """Trim history to keep only the most recent records.

    Args:
        max_items: Maximum number of records to keep.

    Returns:
        Number of records removed.
    """
    if not HISTORY_FILE.exists():
        return 0

    records = []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(line)
    except OSError:
        return 0

    if len(records) <= max_items:
        return 0

    removed = len(records) - max_items
    records = records[-max_items:]

    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        for line in records:
            f.write(line + "\n")

    return removed


def update_record_status(record_id: str, status: TaskStatus) -> bool:
    """Update the status of a history record.

    Args:
        record_id: ID of the record to update.
        status: New status to set.

    Returns:
        True if record was found and updated, False otherwise.
    """
    if not HISTORY_FILE.exists():
        return False

    updated = False
    lines = []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    lines.append("")
                    continue
                try:
                    data = json.loads(line)
                    if data.get("id") == record_id:
                        data["status"] = status.value
                        updated = True
                    lines.append(json.dumps(data, ensure_ascii=False))
                except (json.JSONDecodeError, KeyError):
                    lines.append(line)
    except OSError:
        return False

    if updated:
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            for line in lines:
                if line:
                    f.write(line + "\n")

    return updated
