"""Tests for frago.session.models module.

Tests data models: enums, SessionStep, MonitoredSession, etc.
"""
from datetime import datetime, timezone

import pytest

from frago.session.models import (
    AgentType,
    MonitoredSession,
    SessionSource,
    SessionStatus,
    SessionStep,
    StepType,
    ToolCallStatus,
)


class TestAgentType:
    """Test AgentType enum."""

    def test_claude_value(self):
        """CLAUDE should have value 'claude'."""
        assert AgentType.CLAUDE.value == "claude"

    def test_str_enum(self):
        """AgentType should be str enum for JSON serialization."""
        assert isinstance(AgentType.CLAUDE, str)
        assert AgentType.CLAUDE == "claude"


class TestSessionStatus:
    """Test SessionStatus enum."""

    def test_all_statuses(self):
        """All status values should be correct."""
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.ERROR.value == "error"
        assert SessionStatus.CANCELLED.value == "cancelled"

    def test_str_enum(self):
        """SessionStatus should be str enum."""
        assert isinstance(SessionStatus.RUNNING, str)


class TestStepType:
    """Test StepType enum."""

    def test_all_types(self):
        """All step types should match ConsoleMessage types."""
        assert StepType.USER_MESSAGE.value == "user"
        assert StepType.ASSISTANT_MESSAGE.value == "assistant"
        assert StepType.TOOL_CALL.value == "tool_call"
        assert StepType.TOOL_RESULT.value == "tool_result"
        assert StepType.SYSTEM_EVENT.value == "system"


class TestToolCallStatus:
    """Test ToolCallStatus enum."""

    def test_all_statuses(self):
        """All tool call statuses should be correct."""
        assert ToolCallStatus.PENDING.value == "pending"
        assert ToolCallStatus.SUCCESS.value == "success"
        assert ToolCallStatus.ERROR.value == "error"


class TestSessionSource:
    """Test SessionSource enum."""

    def test_all_sources(self):
        """All session sources should be correct."""
        assert SessionSource.TERMINAL.value == "terminal"
        assert SessionSource.WEB.value == "web"
        assert SessionSource.UNKNOWN.value == "unknown"


class TestSessionStep:
    """Test SessionStep model."""

    def test_create_minimal(self):
        """Should create with minimal required fields."""
        step = SessionStep(
            step_id=1,
            session_id="test-session",
            type=StepType.USER_MESSAGE,
            timestamp=datetime.now(timezone.utc),
            content_summary="Test content",
            raw_uuid="uuid-123",
        )

        assert step.step_id == 1
        assert step.session_id == "test-session"
        assert step.type == StepType.USER_MESSAGE

    def test_optional_fields(self):
        """Optional fields should default to None."""
        step = SessionStep(
            step_id=1,
            session_id="test-session",
            type=StepType.USER_MESSAGE,
            timestamp=datetime.now(timezone.utc),
            content_summary="Test",
            raw_uuid="uuid-123",
        )

        assert step.parent_uuid is None
        assert step.tool_call_id is None
        assert step.tool_name is None

    def test_tool_call_step(self):
        """Tool call step should include tool_name."""
        step = SessionStep(
            step_id=2,
            session_id="test-session",
            type=StepType.TOOL_CALL,
            timestamp=datetime.now(timezone.utc),
            content_summary="Reading file...",
            raw_uuid="uuid-456",
            tool_call_id="tc-123",
            tool_name="Read",
        )

        assert step.tool_name == "Read"
        assert step.tool_call_id == "tc-123"

    def test_step_id_must_be_positive(self):
        """step_id must be >= 1."""
        with pytest.raises(ValueError):
            SessionStep(
                step_id=0,
                session_id="test",
                type=StepType.USER_MESSAGE,
                timestamp=datetime.now(timezone.utc),
                content_summary="Test",
                raw_uuid="uuid",
            )

    def test_json_serialization(self):
        """Should serialize datetime to ISO format."""
        now = datetime.now(timezone.utc)
        step = SessionStep(
            step_id=1,
            session_id="test",
            type=StepType.USER_MESSAGE,
            timestamp=now,
            content_summary="Test",
            raw_uuid="uuid",
        )

        data = step.model_dump(mode="json")
        assert isinstance(data["timestamp"], str)
        assert "T" in data["timestamp"]  # ISO format


class TestMonitoredSession:
    """Test MonitoredSession model."""

    def test_create_minimal(self):
        """Should create with minimal required fields."""
        session = MonitoredSession(
            session_id="test-123",
            agent_type=AgentType.CLAUDE,
            project_path="/home/test/project",
            source_file="/home/test/.claude/projects/-home-test-project/session.jsonl",
            started_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
        )

        assert session.session_id == "test-123"
        assert session.agent_type == AgentType.CLAUDE
        assert session.status == SessionStatus.RUNNING  # default

    def test_optional_fields_default(self):
        """Optional fields should have appropriate defaults."""
        session = MonitoredSession(
            session_id="test-123",
            agent_type=AgentType.CLAUDE,
            project_path="/home/test",
            source_file="/home/test/.claude/projects/-home-test/session.jsonl",
            started_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
        )

        assert session.ended_at is None
        assert session.name is None
        assert session.step_count == 0
        assert session.tool_call_count == 0

    def test_json_roundtrip(self):
        """Should survive JSON serialization roundtrip."""
        original = MonitoredSession(
            session_id="roundtrip-test",
            agent_type=AgentType.CLAUDE,
            status=SessionStatus.COMPLETED,
            project_path="/home/test",
            source_file="/home/test/.claude/projects/-home-test/session.jsonl",
            started_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            name="Test Session",
            step_count=10,
        )

        # Serialize then deserialize
        data = original.model_dump(mode="json")
        restored = MonitoredSession.model_validate(data)

        assert restored.session_id == original.session_id
        assert restored.status == original.status
        assert restored.name == original.name
        assert restored.step_count == original.step_count
