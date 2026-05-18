"""Tests for frago.session.storage module.

Tests session data persistence: directory management, metadata, steps, summary.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionStatus,
    SessionStep,
    StepType,
)
from frago.session.storage import (
    append_step,
    create_session_dir,
    get_session_base_dir,
    get_session_dir,
    read_metadata,
    read_steps,
    write_metadata,
)


class TestGetSessionBaseDir:
    """Test get_session_base_dir() function."""

    def test_default_directory(self, monkeypatch):
        """Without env var, should return ~/.frago/sessions."""
        monkeypatch.delenv("FRAGO_SESSION_DIR", raising=False)
        result = get_session_base_dir()
        assert result == Path.home() / ".frago" / "sessions"

    def test_custom_directory_from_env(self, monkeypatch):
        """With FRAGO_SESSION_DIR set, should return custom path."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", "/custom/path/sessions")
        result = get_session_base_dir()
        assert result == Path("/custom/path/sessions")

    def test_expanduser_in_env(self, monkeypatch):
        """Should expand ~ in env var path."""
        monkeypatch.setenv("FRAGO_SESSION_DIR", "~/my-sessions")
        result = get_session_base_dir()
        assert result == Path.home() / "my-sessions"


class TestGetSessionDir:
    """Test get_session_dir() function."""

    def test_default_agent_type(self, mock_home):
        """Default agent type should be CLAUDE."""
        result = get_session_dir("test-session-123")
        assert result.name == "test-session-123"
        assert result.parent.name == "claude"

    def test_explicit_agent_type(self, mock_home):
        """Explicit agent type should be reflected in path."""
        result = get_session_dir("test-session-123", AgentType.CLAUDE)
        assert "claude" in str(result)


class TestCreateSessionDir:
    """Test create_session_dir() function."""

    def test_creates_directory(self, mock_home):
        """Should create session directory."""
        session_id = "new-session-456"
        result = create_session_dir(session_id)

        assert result.exists()
        assert result.is_dir()
        assert result.name == session_id

    def test_idempotent(self, mock_home):
        """Calling multiple times should not fail."""
        session_id = "idempotent-session"
        result1 = create_session_dir(session_id)
        result2 = create_session_dir(session_id)

        assert result1 == result2
        assert result1.exists()


class TestWriteAndReadMetadata:
    """Test write_metadata() and read_metadata() functions."""

    @pytest.fixture
    def sample_session(self) -> MonitoredSession:
        """Create sample MonitoredSession."""
        return MonitoredSession(
            session_id="meta-test-session",
            agent_type=AgentType.CLAUDE,
            status=SessionStatus.RUNNING,
            project_path="/home/test/project",
            source_file="/home/test/.claude/projects/-home-test-project/session.jsonl",
            started_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
        )

    def test_write_creates_file(self, mock_home, sample_session):
        """write_metadata should create metadata.json file."""
        result_path = write_metadata(sample_session)

        assert result_path.exists()
        assert result_path.name == "metadata.json"

    def test_read_returns_session(self, mock_home, sample_session):
        """read_metadata should return MonitoredSession object."""
        write_metadata(sample_session)
        result = read_metadata(sample_session.session_id)

        assert result is not None
        assert result.session_id == sample_session.session_id
        assert result.project_path == sample_session.project_path

    def test_read_nonexistent_returns_none(self, mock_home):
        """read_metadata for non-existent session should return None."""
        result = read_metadata("nonexistent-session-id")
        assert result is None

    def test_roundtrip_preserves_data(self, mock_home, sample_session):
        """Write then read should preserve all data."""
        write_metadata(sample_session)
        result = read_metadata(sample_session.session_id)

        assert result.session_id == sample_session.session_id
        assert result.agent_type == sample_session.agent_type
        assert result.status == sample_session.status
        assert result.project_path == sample_session.project_path


class TestAppendAndReadSteps:
    """Test append_step() and read_steps() functions."""

    @pytest.fixture
    def sample_step(self) -> SessionStep:
        """Create sample SessionStep."""
        return SessionStep(
            step_id=1,
            session_id="steps-test-session",
            type=StepType.USER_MESSAGE,
            timestamp=datetime.now(timezone.utc),
            content_summary="Test user message",
            raw_uuid="uuid-123-456",
        )

    def test_append_creates_file(self, mock_home, sample_step):
        """append_step should create steps.jsonl file."""
        result_path = append_step(sample_step)

        assert result_path.exists()
        assert result_path.name == "steps.jsonl"

    def test_append_multiple_steps(self, mock_home, sample_step):
        """Multiple appends should add lines to file."""
        append_step(sample_step)

        step2 = SessionStep(
            step_id=2,
            session_id=sample_step.session_id,
            type=StepType.ASSISTANT_MESSAGE,
            timestamp=datetime.now(timezone.utc),
            content_summary="Test assistant response",
            raw_uuid="uuid-789-abc",
        )
        result_path = append_step(step2)

        # Read file and count lines
        lines = result_path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_read_returns_steps(self, mock_home, sample_step):
        """read_steps should return list of SessionStep objects."""
        append_step(sample_step)
        result = read_steps(sample_step.session_id)

        assert len(result) == 1
        assert result[0].step_id == sample_step.step_id
        assert result[0].content_summary == sample_step.content_summary

    def test_read_nonexistent_returns_empty(self, mock_home):
        """read_steps for non-existent session should return empty list."""
        result = read_steps("nonexistent-session-id")
        assert result == []

    def test_read_preserves_order(self, mock_home):
        """Steps should be returned in order of appending."""
        session_id = "order-test-session"

        for i in range(5):
            step = SessionStep(
                step_id=i + 1,
                session_id=session_id,
                type=StepType.USER_MESSAGE,
                timestamp=datetime.now(timezone.utc),
                content_summary=f"Message {i + 1}",
                raw_uuid=f"uuid-{i}",
            )
            append_step(step)

        result = read_steps(session_id)

        assert len(result) == 5
        for i, step in enumerate(result):
            assert step.step_id == i + 1
            assert step.content_summary == f"Message {i + 1}"
