"""Persistent storage for Execution records.

Stores execution records as JSON files under ~/.frago/executions/.
Uses a lightweight index.json for fast list queries.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .execution import Execution, ExecutionStatus

logger = logging.getLogger(__name__)

MAX_STORED_DATA_SIZE = 100 * 1024  # 100KB
DEFAULT_INDEX_LIMIT = 200  # Max entries in index.json
AUTO_CLEANUP_INTERVAL = 100  # Trigger cleanup every N creates
AUTO_CLEANUP_MAX_COUNT = 1000  # Keep at most this many records


class ExecutionStore:
    """Execution persistence layer backed by JSON files."""

    def __init__(self, store_dir: Path | None = None):
        self.store_dir = store_dir or (Path.home() / ".frago" / "executions")
        self.index_file = self.store_dir / "index.json"
        self._create_count = 0

    def create(
        self,
        recipe_name: str,
        params: dict[str, Any],
        source: str | None = None,
        timeout_seconds: int | None = None,
        workflow_id: str | None = None,
        step_index: int | None = None,
    ) -> Execution:
        """Register a new Execution in PENDING state and persist it."""
        execution = Execution.create(
            recipe_name=recipe_name,
            params=params,
            source=source,
            timeout_seconds=timeout_seconds,
            workflow_id=workflow_id,
            step_index=step_index,
        )
        self._save_execution(execution)
        self._update_index(execution)
        self._maybe_cleanup()
        return execution

    def transition(self, execution_id: str, new_status: ExecutionStatus) -> Execution:
        """Transition execution to a new status and persist."""
        execution = self.get(execution_id)
        if execution is None:
            raise ValueError(f"Execution not found: {execution_id}")
        execution.transition_to(new_status)
        self._save_execution(execution)
        self._update_index(execution)
        return execution

    def complete(
        self,
        execution_id: str,
        status: ExecutionStatus,
        data: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        runtime: str | None = None,
    ) -> Execution:
        """Write terminal state for an execution."""
        execution = self.get(execution_id)
        if execution is None:
            raise ValueError(f"Execution not found: {execution_id}")

        execution.transition_to(status)
        execution.completed_at = datetime.now(UTC)
        execution.exit_code = exit_code
        execution.duration_ms = duration_ms
        if runtime is not None:
            execution.runtime = runtime

        # Truncate large data
        if data is not None:
            try:
                serialized = json.dumps(data)
                if len(serialized) > MAX_STORED_DATA_SIZE:
                    data = {
                        "_truncated": True,
                        "keys": list(data.keys()) if isinstance(data, dict) else None,
                    }
            except (TypeError, ValueError):
                data = {"_truncated": True, "keys": None}
        execution.data = data
        execution.error = error

        self._save_execution(execution)
        self._update_index(execution)
        return execution

    def get(self, execution_id: str) -> Execution | None:
        """Load a single Execution by ID."""
        # Search in index first to find the month directory
        index = self._load_index()
        for entry in index:
            if entry.get("id") == execution_id:
                file_path = self._file_path_from_entry(entry)
                if file_path and file_path.exists():
                    return self._load_execution_file(file_path)

        # Fallback: scan directories (for entries not yet in index)
        for json_file in self.store_dir.rglob(f"{execution_id}.json"):
            return self._load_execution_file(json_file)
        return None

    def list_recent(
        self,
        recipe_name: str | None = None,
        limit: int = 20,
        status: ExecutionStatus | None = None,
    ) -> list[Execution]:
        """Query recent executions from the index."""
        index = self._load_index()
        results = []
        for entry in index:
            if recipe_name and entry.get("recipe_name") != recipe_name:
                continue
            if status and entry.get("status") != status.value:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        # Load full execution objects
        executions = []
        for entry in results:
            file_path = self._file_path_from_entry(entry)
            if file_path and file_path.exists():
                ex = self._load_execution_file(file_path)
                if ex:
                    executions.append(ex)
        return executions

    def list_by_workflow(self, workflow_id: str) -> list[Execution]:
        """List all executions belonging to a workflow, ordered by step_index.

        Args:
            workflow_id: The parent workflow execution ID.

        Returns:
            List of Execution objects sorted by step_index (nulls last).
        """
        index = self._load_index()
        executions = []
        for entry in index:
            if entry.get("workflow_id") != workflow_id:
                continue
            file_path = self._file_path_from_entry(entry)
            if file_path and file_path.exists():
                ex = self._load_execution_file(file_path)
                if ex:
                    executions.append(ex)
        # Sort by step_index (None sorts last)
        executions.sort(key=lambda e: (e.step_index is None, e.step_index or 0))
        return executions

    def cleanup(self, _max_age_days: int = 30, max_count: int = 1000) -> int:
        """Remove old execution records. Returns count of removed entries."""
        index = self._load_index()
        if len(index) <= max_count:
            return 0

        removed = 0
        new_index = []

        for i, entry in enumerate(index):
            if i < max_count:
                new_index.append(entry)
            else:
                # Remove the file
                file_path = self._file_path_from_entry(entry)
                if file_path and file_path.exists():
                    try:
                        file_path.unlink()
                        removed += 1
                    except OSError:
                        new_index.append(entry)

        self._save_index(new_index)
        return removed

    def _maybe_cleanup(self) -> None:
        """Periodically trigger cleanup to prevent unbounded file growth."""
        self._create_count += 1
        if self._create_count % AUTO_CLEANUP_INTERVAL == 0:
            try:
                removed = self.cleanup(max_count=AUTO_CLEANUP_MAX_COUNT)
                if removed > 0:
                    logger.info("Auto-cleanup removed %d old execution records", removed)
            except Exception:
                logger.debug("Auto-cleanup failed", exc_info=True)

    # --- Private helpers ---

    def _execution_dir(self, created_at: datetime) -> Path:
        """Get the month-based subdirectory for an execution."""
        return self.store_dir / str(created_at.year) / f"{created_at.month:02d}"

    def _execution_file_path(self, execution: Execution) -> Path:
        """Get the file path for an execution."""
        d = self._execution_dir(execution.created_at)
        return d / f"{execution.id}.json"

    def _file_path_from_entry(self, entry: dict) -> Path | None:
        """Reconstruct file path from an index entry."""
        created_at_str = entry.get("created_at")
        exec_id = entry.get("id")
        if not created_at_str or not exec_id:
            return None
        try:
            dt = datetime.fromisoformat(created_at_str)
            d = self._execution_dir(dt)
            return d / f"{exec_id}.json"
        except (ValueError, TypeError):
            return None

    def _save_execution(self, execution: Execution) -> None:
        """Write execution to its JSON file."""
        file_path = self._execution_file_path(execution)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(execution.to_dict(), indent=2, ensure_ascii=False)
            file_path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to save execution %s: %s", execution.id, e)

    def _load_execution_file(self, file_path: Path) -> Execution | None:
        """Load an Execution from a JSON file."""
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
            return Execution.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("Failed to load execution from %s: %s", file_path, e)
            return None

    def _load_index(self) -> list[dict]:
        """Load the index file."""
        if not self.index_file.exists():
            return []
        try:
            content = self.index_file.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, index: list[dict]) -> None:
        """Write the index file."""
        try:
            self.index_file.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(index, indent=2, ensure_ascii=False)
            self.index_file.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to save execution index: %s", e)

    def _update_index(self, execution: Execution) -> None:
        """Update or insert an entry in the index (sorted by created_at desc)."""
        index = self._load_index()

        entry = {
            "id": execution.id,
            "recipe_name": execution.recipe_name,
            "status": execution.status.value,
            "created_at": execution.created_at.isoformat(),
            "workflow_id": execution.workflow_id,
        }

        # Update existing or prepend
        updated = False
        for i, existing in enumerate(index):
            if existing.get("id") == execution.id:
                index[i] = entry
                updated = True
                break

        if not updated:
            index.insert(0, entry)

        # Trim index
        if len(index) > DEFAULT_INDEX_LIMIT:
            index = index[:DEFAULT_INDEX_LIMIT]

        self._save_index(index)
