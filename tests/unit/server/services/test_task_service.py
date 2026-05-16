"""Tests for frago.server.services.task_service module.

Tests task listing and session-to-task conversion.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from frago.server.services.task_service import TaskService


class TestTaskServiceSessionToTask:
    """Test TaskService._session_to_task() method."""

    def test_returns_none_for_none_session(self):
        """Should return None if session is None."""
        result = TaskService._session_to_task(None)
        assert result is None

    def test_converts_basic_session(self):
        """Should convert session to task dictionary."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session.name = "Test Session"
        mock_session.status.value = "running"
        mock_session.project_path = "/home/test/project"
        mock_session.source.value = "terminal"
        mock_session.started_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_session.ended_at = None
        mock_session.last_activity = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_session.step_count = 5
        mock_session.tool_call_count = 3

        result = TaskService._session_to_task(mock_session)

        assert result is not None
        assert result["id"] == "test-session-123"
        assert result["title"] == "Test Session"
        assert result["status"] == "running"
        assert result["project_path"] == "/home/test/project"
        assert result["step_count"] == 5
        assert result["tool_call_count"] == 3

    def test_uses_title_manager_title(self):
        """Should prefer title from title_manager."""
        mock_session = MagicMock()
        mock_session.session_id = "session-456"
        mock_session.name = "Session Name"
        mock_session.status.value = "completed"
        mock_session.project_path = "/test"
        mock_session.source.value = "terminal"
        mock_session.started_at = datetime.now(timezone.utc)
        mock_session.ended_at = None
        mock_session.last_activity = datetime.now(timezone.utc)
        mock_session.step_count = 0
        mock_session.tool_call_count = 0

        mock_title_manager = MagicMock()
        mock_title_manager.get_title.return_value = "AI Generated Title"

        result = TaskService._session_to_task(mock_session, mock_title_manager)

        assert result["title"] == "AI Generated Title"

    def test_fallback_to_session_name(self):
        """Should use session name if no title from manager."""
        mock_session = MagicMock()
        mock_session.session_id = "session-789"
        mock_session.name = "Original Session Name"
        mock_session.status.value = "running"
        mock_session.project_path = "/test"
        mock_session.source.value = "terminal"
        mock_session.started_at = datetime.now(timezone.utc)
        mock_session.ended_at = None
        mock_session.last_activity = datetime.now(timezone.utc)
        mock_session.step_count = 0
        mock_session.tool_call_count = 0

        mock_title_manager = MagicMock()
        mock_title_manager.get_title.return_value = None

        result = TaskService._session_to_task(mock_session, mock_title_manager)

        assert result["title"] == "Original Session Name"

    def test_fallback_to_session_id(self):
        """Should use session ID prefix as fallback name."""
        mock_session = MagicMock()
        mock_session.session_id = "abcd1234-full-uuid"
        mock_session.name = None
        mock_session.status.value = "running"
        mock_session.project_path = "/test"
        mock_session.source.value = "terminal"
        mock_session.started_at = datetime.now(timezone.utc)
        mock_session.ended_at = None
        mock_session.last_activity = datetime.now(timezone.utc)
        mock_session.step_count = 0
        mock_session.tool_call_count = 0

        result = TaskService._session_to_task(mock_session, title_manager=None)

        assert "abcd1234" in result["title"]


class TestTaskServiceGetTasks:
    """Test TaskService.get_tasks() method."""

    def test_returns_empty_on_error(self):
        """Should return empty result on exception."""
        with patch(
            "frago.session.storage.list_sessions",
            side_effect=Exception("Storage error"),
        ):
            result = TaskService.get_tasks()

        assert result["tasks"] == []
        assert result["total"] == 0

    def test_parameter_validation(self):
        """Should clamp limit and offset to valid ranges."""
        with patch("frago.session.storage.list_sessions", return_value=[]):
            # Test with extreme values - should not raise
            result = TaskService.get_tasks(limit=1000, offset=-10)

        assert result["tasks"] == []

    def test_filters_excluded_sessions(self):
        """Should skip sessions marked as excluded by title manager."""
        mock_session = MagicMock()
        mock_session.session_id = "excluded-session"

        mock_title_manager = MagicMock()
        mock_title_manager.is_excluded_session.return_value = True

        with (
            patch("frago.session.storage.list_sessions", return_value=[mock_session]),
            patch(
                "frago.session.title_manager.get_title_manager",
                return_value=mock_title_manager,
            ),
            patch.object(TaskService, "_should_display", return_value=True),
        ):
            result = TaskService.get_tasks()

        assert result["tasks"] == []

    def test_applies_status_filter(self):
        """Should pass status filter to list_sessions."""
        with (
            patch("frago.session.storage.list_sessions") as mock_list,
            patch(
                "frago.session.title_manager.get_title_manager",
                return_value=MagicMock(),
            ),
        ):
            mock_list.return_value = []
            TaskService.get_tasks(status="completed")

        # Verify status filter was passed
        call_kwargs = mock_list.call_args
        assert call_kwargs is not None


class TestTaskServiceShouldDisplay:
    """Test TaskService._should_display() method."""

    def test_returns_true_for_running_session(self):
        """Should return True for running sessions regardless of step count."""
        from frago.session.models import SessionStatus

        mock_session = MagicMock()
        mock_session.status = SessionStatus.RUNNING
        mock_session.step_count = 0

        result = TaskService._should_display(mock_session)

        assert result is True

    def test_returns_true_when_has_assistant_message(self, tmp_path):
        """Should return True if steps.jsonl contains assistant message."""
        from frago.session.models import SessionStatus

        mock_session = MagicMock()
        mock_session.status = SessionStatus.COMPLETED

        steps_file = tmp_path / "steps.jsonl"
        steps_file.write_text('{"type": "user"}\n{"type": "assistant"}\n')

        with patch(
            "frago.session.storage.get_session_dir",
            return_value=tmp_path,
        ):
            result = TaskService._should_display(mock_session)

        assert result is True

    def test_returns_false_when_no_assistant_message(self, tmp_path):
        """Should return False if steps.jsonl has no assistant message."""
        from frago.session.models import SessionStatus

        mock_session = MagicMock()
        mock_session.status = SessionStatus.COMPLETED

        steps_file = tmp_path / "steps.jsonl"
        steps_file.write_text('{"type": "system"}\n')

        with patch(
            "frago.session.storage.get_session_dir",
            return_value=tmp_path,
        ):
            result = TaskService._should_display(mock_session)

        assert result is False
