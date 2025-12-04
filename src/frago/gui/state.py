"""Application state management for Frago GUI.

Provides thread-safe singleton state manager for the GUI application.
"""

import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from frago.gui.exceptions import TaskAlreadyRunningError
from frago.gui.models import AppState, ConnectionStatus, PageType, TaskStatus


class AppStateManager:
    """Thread-safe singleton state manager for the GUI application."""

    _instance: Optional["AppStateManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AppStateManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._state = AppState()
        self._state_lock = threading.RLock()
        self._listeners: Dict[str, List[Callable[[str, Any], None]]] = {}
        self._task_process: Optional[Any] = None
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "AppStateManager":
        """Get the singleton instance.

        Returns:
            AppStateManager instance.
        """
        return cls()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def get_state(self) -> AppState:
        """Get current application state.

        Returns:
            Copy of current AppState.
        """
        with self._state_lock:
            return AppState(
                current_page=self._state.current_page,
                task_status=self._state.task_status,
                connection_status=self._state.connection_status,
                current_task_id=self._state.current_task_id,
                current_task_progress=self._state.current_task_progress,
                last_error=self._state.last_error,
            )

    def get_task_status(self) -> Dict[str, Any]:
        """Get current task status for JavaScript.

        Returns:
            Dictionary with task status information.
        """
        with self._state_lock:
            return {
                "status": self._state.task_status.value,
                "progress": self._state.current_task_progress,
                "task_id": self._state.current_task_id,
                "error": self._state.last_error,
            }

    def set_page(self, page: PageType) -> None:
        """Set current page.

        Args:
            page: New page to navigate to.
        """
        with self._state_lock:
            old_page = self._state.current_page
            self._state.current_page = page
            self._notify("page_changed", {"old": old_page.value, "new": page.value})

    def start_task(self, process: Optional[Any] = None) -> str:
        """Start a new task.

        Args:
            process: Optional subprocess reference.

        Returns:
            Task ID.

        Raises:
            TaskAlreadyRunningError: If a task is already running.
        """
        with self._state_lock:
            if self._state.task_status == TaskStatus.RUNNING:
                raise TaskAlreadyRunningError(self._state.current_task_id or "")

            task_id = str(uuid.uuid4())
            self._state.task_status = TaskStatus.RUNNING
            self._state.current_task_id = task_id
            self._state.current_task_progress = 0.0
            self._state.last_error = None
            self._task_process = process

            self._notify("task_started", {"task_id": task_id})
            return task_id

    def update_progress(self, progress: float, step: str = "") -> None:
        """Update current task progress.

        Args:
            progress: Progress value between 0.0 and 1.0.
            step: Optional step description.
        """
        with self._state_lock:
            if self._state.task_status != TaskStatus.RUNNING:
                return

            self._state.current_task_progress = max(0.0, min(1.0, progress))
            self._notify(
                "progress_updated",
                {
                    "progress": self._state.current_task_progress,
                    "step": step,
                },
            )

    def complete_task(self) -> None:
        """Mark current task as completed."""
        with self._state_lock:
            task_id = self._state.current_task_id
            self._state.task_status = TaskStatus.COMPLETED
            self._state.current_task_progress = 1.0
            self._task_process = None
            self._notify("task_completed", {"task_id": task_id})

            self._state.task_status = TaskStatus.IDLE
            self._state.current_task_id = None

    def error_task(self, error: str) -> None:
        """Mark current task as failed.

        Args:
            error: Error message.
        """
        with self._state_lock:
            task_id = self._state.current_task_id
            self._state.task_status = TaskStatus.ERROR
            self._state.last_error = error
            self._task_process = None
            self._notify("task_error", {"task_id": task_id, "error": error})

            self._state.task_status = TaskStatus.IDLE
            self._state.current_task_id = None

    def cancel_task(self) -> bool:
        """Cancel the current running task.

        Returns:
            True if task was cancelled, False if no task running.
        """
        with self._state_lock:
            if self._state.task_status != TaskStatus.RUNNING:
                return False

            task_id = self._state.current_task_id

            if self._task_process:
                try:
                    self._task_process.terminate()
                except Exception:
                    pass

            self._state.task_status = TaskStatus.CANCELLED
            self._task_process = None
            self._notify("task_cancelled", {"task_id": task_id})

            self._state.task_status = TaskStatus.IDLE
            self._state.current_task_id = None
            self._state.current_task_progress = 0.0

            return True

    def set_connection_status(self, status: ConnectionStatus) -> None:
        """Set Chrome connection status.

        Args:
            status: New connection status.
        """
        with self._state_lock:
            self._state.connection_status = status
            self._notify("connection_changed", {"status": status.value})

    def is_task_running(self) -> bool:
        """Check if a task is currently running.

        Returns:
            True if a task is running.
        """
        with self._state_lock:
            return self._state.task_status == TaskStatus.RUNNING

    def add_listener(self, event: str, callback: Callable[[str, Any], None]) -> None:
        """Add an event listener.

        Args:
            event: Event name.
            callback: Callback function.
        """
        with self._state_lock:
            if event not in self._listeners:
                self._listeners[event] = []
            self._listeners[event].append(callback)

    def remove_listener(self, event: str, callback: Callable[[str, Any], None]) -> None:
        """Remove an event listener.

        Args:
            event: Event name.
            callback: Callback function to remove.
        """
        with self._state_lock:
            if event in self._listeners:
                try:
                    self._listeners[event].remove(callback)
                except ValueError:
                    pass

    def _notify(self, event: str, data: Any) -> None:
        """Notify listeners of an event.

        Args:
            event: Event name.
            data: Event data.
        """
        listeners = self._listeners.get(event, [])
        for callback in listeners:
            try:
                callback(event, data)
            except Exception:
                pass
