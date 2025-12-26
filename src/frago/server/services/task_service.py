"""Task/Session management service.

Provides functionality for listing and viewing tasks from session storage.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskService:
    """Service for task/session management."""

    @staticmethod
    def get_tasks(
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get task list.

        Reads session data from ~/.frago/sessions/.

        Args:
            limit: Maximum number to return (1-100).
            offset: Number of tasks to skip.
            status: Status filter (running/completed/error/cancelled).

        Returns:
            Dictionary with 'tasks' list and 'total' count.
        """
        try:
            from frago.session.models import AgentType, SessionStatus
            from frago.session.storage import list_sessions

            # Parameter validation
            limit = max(1, min(100, limit))
            offset = max(0, offset)

            # Convert status filter
            status_filter = None
            if status:
                try:
                    status_filter = SessionStatus(status)
                except ValueError:
                    pass  # Invalid status, ignore filter

            tasks = []

            # Request more sessions to compensate for filtering losses
            sessions = list_sessions(
                agent_type=AgentType.CLAUDE,
                limit=(limit + offset) * 3,
                status=status_filter,
            )

            for session in sessions:
                try:
                    # Filter out sessions that shouldn't be displayed
                    if not TaskService._should_display(session):
                        continue
                    task = TaskService._session_to_task(session)
                    if task:
                        tasks.append(task)
                except Exception as e:
                    logger.debug("Failed to convert session: %s", e)
                    continue

            # Sort by started_at descending
            tasks.sort(
                key=lambda t: t.get("started_at") or "",
                reverse=True,
            )

            # Apply offset and limit
            paginated_tasks = tasks[offset:offset + limit]

            return {
                "tasks": paginated_tasks,
                "total": len(tasks),
            }

        except Exception as e:
            logger.error("Failed to get tasks: %s", e)
            return {"tasks": [], "total": 0}

    @staticmethod
    def _session_to_task(session) -> Optional[Dict[str, Any]]:
        """Convert session metadata to task dictionary.

        Args:
            session: Session metadata object.

        Returns:
            Task dictionary or None if session should be filtered.
        """
        # Filter out sessions without meaningful content
        if not session:
            return None

        # Get session name or generate from first message
        name = getattr(session, "name", None)
        if not name:
            name = f"Session {session.session_id[:8]}"

        # Convert status
        status = getattr(session, "status", None)
        status_str = status.value if status else "running"

        # Calculate duration
        started_at = getattr(session, "started_at", None)
        ended_at = getattr(session, "ended_at", None)
        duration_ms = None
        if started_at and ended_at:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        # Get source field if available
        source = getattr(session, "source", None)
        source_str = source.value if source else "unknown"

        return {
            "id": session.session_id,
            "title": name,
            "status": status_str,
            "project_path": getattr(session, "project_path", None),
            "agent_type": "claude",
            "started_at": started_at.isoformat() if started_at else None,
            "completed_at": ended_at.isoformat() if ended_at else None,
            "duration_ms": duration_ms,
            "step_count": getattr(session, "step_count", 0),
            "tool_call_count": getattr(session, "tool_call_count", 0),
            "source": source_str,
        }

    @staticmethod
    def _should_display(session) -> bool:
        """Determine if session should be displayed in task list.

        Display criteria (any of):
        1. Running task
        2. Step count >= 10
        3. Step count >= 5

        Exclusion criteria:
        1. Step count < 5 and completed
        2. No assistant messages and step count < 10

        Args:
            session: Session metadata object.

        Returns:
            Whether session should be displayed.
        """
        import json
        from frago.session.models import SessionStatus
        from frago.session.storage import get_session_dir

        status = getattr(session, "status", None)
        step_count = getattr(session, "step_count", 0)

        # Always display running tasks
        if status == SessionStatus.RUNNING:
            return True

        # Display if step count >= 10
        if step_count >= 10:
            return True

        # Don't display if step count < 5 and completed
        if step_count < 5 and status == SessionStatus.COMPLETED:
            return False

        # Check for assistant messages if step_count < 10
        if step_count < 10:
            session_dir = get_session_dir(session.session_id, session.agent_type)
            steps_file = session_dir / "steps.jsonl"
            if steps_file.exists():
                has_assistant = False
                try:
                    with open(steps_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            step = json.loads(line)
                            if step.get("type") == "assistant_message":
                                has_assistant = True
                                break
                except Exception:
                    pass

                # No assistant messages → system session, don't display
                if not has_assistant:
                    return False

        # Display if step count >= 5
        if step_count >= 5:
            return True

        return False

    @staticmethod
    def get_task(session_id: str) -> Optional[Dict[str, Any]]:
        """Get task details by session ID.

        Args:
            session_id: Session identifier.

        Returns:
            Task detail dictionary or None if not found.
        """
        try:
            from frago.session.models import AgentType
            from frago.session.storage import (
                read_metadata,
                read_steps_paginated,
                read_summary,
            )

            if not session_id:
                return None

            # Read session metadata
            session = read_metadata(session_id, AgentType.CLAUDE)
            if not session:
                return None

            # Read steps (from end, newest first)
            steps_result = read_steps_paginated(
                session_id, AgentType.CLAUDE, limit=100, offset=0, from_end=True
            )
            steps = steps_result.get("steps", [])

            # Read summary
            summary = read_summary(session_id, AgentType.CLAUDE)

            # Build task detail
            return TaskService._build_task_detail(
                session, steps, summary, steps_result
            )

        except Exception as e:
            logger.error("Failed to get task %s: %s", session_id, e)
            return None

    @staticmethod
    def _build_task_detail(
        session,
        steps: List[Any],
        summary: Optional[Any],
        steps_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build task detail dictionary from session data.

        Args:
            session: Session metadata.
            steps: List of step records.
            summary: Session summary or None.
            steps_result: Pagination info for steps.

        Returns:
            Task detail dictionary.
        """
        # Get basic info
        name = getattr(session, "name", None) or f"Session {session.session_id[:8]}"
        status = getattr(session, "status", None)
        status_str = status.value if status else "running"

        started_at = getattr(session, "started_at", None)
        ended_at = getattr(session, "ended_at", None)
        duration_ms = None
        if started_at and ended_at:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        # Convert steps
        gui_steps = []
        for step in steps:
            gui_steps.append(TaskService._step_to_dict(step))

        # Build summary if available
        summary_dict = None
        if summary:
            summary_dict = {
                "total_duration_ms": getattr(summary, "total_duration_ms", duration_ms or 0),
                "user_message_count": getattr(summary, "user_message_count", 0),
                "assistant_message_count": getattr(summary, "assistant_message_count", 0),
                "tool_call_count": getattr(summary, "tool_call_count", 0),
                "tool_success_count": getattr(summary, "tool_success_count", 0),
                "tool_error_count": getattr(summary, "tool_error_count", 0),
                "most_used_tools": getattr(summary, "most_used_tools", []),
            }

        return {
            "id": session.session_id,
            "title": name,
            "status": status_str,
            "project_path": getattr(session, "project_path", None),
            "started_at": started_at.isoformat() if started_at else None,
            "completed_at": ended_at.isoformat() if ended_at else None,
            "duration_ms": duration_ms,
            "step_count": getattr(session, "step_count", 0),
            "tool_call_count": getattr(session, "tool_call_count", 0),
            "steps": gui_steps,
            "steps_total": steps_result.get("total", len(gui_steps)),
            "steps_offset": steps_result.get("offset", 0),
            "has_more_steps": steps_result.get("has_more", False),
            "summary": summary_dict,
        }

    @staticmethod
    def _step_to_dict(step) -> Dict[str, Any]:
        """Convert session step to dictionary.

        Args:
            step: Session step object.

        Returns:
            Step dictionary.
        """
        timestamp = getattr(step, "timestamp", None)
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()

        step_type = getattr(step, "type", "assistant")
        if hasattr(step_type, "value"):
            step_type = step_type.value

        return {
            "step_id": getattr(step, "step_id", 0),
            "timestamp": timestamp,
            "type": step_type,
            "content": getattr(step, "content_summary", ""),
            "tool_name": getattr(step, "tool_name", None),
            "tool_call_id": getattr(step, "tool_call_id", None),
            "tool_result": getattr(step, "tool_result", None),
        }

    @staticmethod
    def get_task_steps(
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        from_end: bool = True,
    ) -> Dict[str, Any]:
        """Get task steps with pagination.

        Args:
            session_id: Session identifier.
            limit: Maximum steps to return (1-100).
            offset: Number of steps to skip.
            from_end: If True, read from end (newest first).

        Returns:
            Dictionary with 'steps', 'total', and 'has_more'.
        """
        try:
            from frago.session.models import AgentType
            from frago.session.storage import read_steps_paginated

            if not session_id:
                return {"steps": [], "total": 0, "has_more": False}

            limit = max(1, min(100, limit))
            offset = max(0, offset)

            result = read_steps_paginated(
                session_id, AgentType.CLAUDE, limit, offset, from_end=from_end
            )

            # Convert steps
            gui_steps = [TaskService._step_to_dict(s) for s in result.get("steps", [])]

            return {
                "steps": gui_steps,
                "total": result.get("total", len(gui_steps)),
                "has_more": result.get("has_more", False),
            }

        except Exception as e:
            logger.error("Failed to get steps for task %s: %s", session_id, e)
            return {"steps": [], "total": 0, "has_more": False}
