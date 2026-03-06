"""Execution model for recipe runs.

An Execution represents a single recipe run — analogous to a Unix process.
It has a unique ID, tracks state transitions, and stores results.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ExecutionStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# Valid state transitions (terminal states have empty sets)
VALID_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.PENDING: {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED},
    ExecutionStatus.RUNNING: {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.SUCCEEDED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.TIMEOUT: set(),
    ExecutionStatus.CANCELLED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current: ExecutionStatus, target: ExecutionStatus):
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid state transition: {current.value} -> {target.value}"
        )


def _generate_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex[:12]}"


@dataclass
class Execution:
    id: str
    recipe_name: str
    status: ExecutionStatus
    params: dict[str, Any]
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    exit_code: int | None = None
    runtime: str | None = None
    duration_ms: int | None = None
    timeout_seconds: int | None = None
    source: str | None = None
    workflow_id: str | None = None
    step_index: int | None = None

    def transition_to(self, new_status: ExecutionStatus) -> None:
        """Transition to a new status, validating the transition is legal."""
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidTransitionError(self.status, new_status)
        self.status = new_status
        if new_status == ExecutionStatus.RUNNING:
            self.started_at = datetime.now(UTC)

    def is_terminal(self) -> bool:
        return len(VALID_TRANSITIONS.get(self.status, set())) == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        def _dt(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        return {
            "id": self.id,
            "recipe_name": self.recipe_name,
            "status": self.status.value,
            "params": self.params,
            "created_at": _dt(self.created_at),
            "started_at": _dt(self.started_at),
            "completed_at": _dt(self.completed_at),
            "data": self.data,
            "error": self.error,
            "exit_code": self.exit_code,
            "runtime": self.runtime,
            "duration_ms": self.duration_ms,
            "timeout_seconds": self.timeout_seconds,
            "source": self.source,
            "workflow_id": self.workflow_id,
            "step_index": self.step_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Execution":
        """Deserialize from a dict."""
        def _parse_dt(val: str | None) -> datetime | None:
            if val is None:
                return None
            return datetime.fromisoformat(val)

        return cls(
            id=d["id"],
            recipe_name=d["recipe_name"],
            status=ExecutionStatus(d["status"]),
            params=d.get("params", {}),
            created_at=_parse_dt(d["created_at"]),
            started_at=_parse_dt(d.get("started_at")),
            completed_at=_parse_dt(d.get("completed_at")),
            data=d.get("data"),
            error=d.get("error"),
            exit_code=d.get("exit_code"),
            runtime=d.get("runtime"),
            duration_ms=d.get("duration_ms"),
            timeout_seconds=d.get("timeout_seconds"),
            source=d.get("source"),
            workflow_id=d.get("workflow_id"),
            step_index=d.get("step_index"),
        )

    @classmethod
    def create(
        cls,
        recipe_name: str,
        params: dict[str, Any],
        source: str | None = None,
        timeout_seconds: int | None = None,
        workflow_id: str | None = None,
        step_index: int | None = None,
    ) -> "Execution":
        """Factory method to create a new PENDING Execution."""
        return cls(
            id=_generate_execution_id(),
            recipe_name=recipe_name,
            status=ExecutionStatus.PENDING,
            params=params,
            created_at=datetime.now(UTC),
            source=source,
            timeout_seconds=timeout_seconds,
            workflow_id=workflow_id,
            step_index=step_index,
        )
