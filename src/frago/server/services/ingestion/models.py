"""Data structures for the task ingestion layer."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class IngestedTask:
    """A task ingested from an external channel into frago."""

    id: str
    channel: str
    channel_message_id: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Filled after execution starts
    session_id: str | None = None
    result_summary: str | None = None
    completed_at: datetime | None = None
    error: str | None = None

    # Channel-specific context needed for reply (opaque to TaskStore/Scheduler)
    reply_context: dict[str, Any] = field(default_factory=dict)
