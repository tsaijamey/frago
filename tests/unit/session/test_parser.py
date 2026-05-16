"""Tests for frago.session.parser module.

Tests JSONL incremental parsing and record conversion.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from frago.session.models import StepType, ToolCallRecord, ToolCallStatus
from frago.session.parser import (
    IncrementalParser,
    ParsedRecord,
    _summarize_tool_calls,
    _summarize_tool_results,
    record_to_step,
    update_tool_call_status,
)


class TestParsedRecord:
    """Test ParsedRecord dataclass."""

    def test_creation_with_required_fields(self):
        """Should create ParsedRecord with required fields."""
        record = ParsedRecord(
            uuid="test-uuid",
            session_id="session-123",
            timestamp=datetime.now(timezone.utc),
            record_type="user",
        )
        assert record.uuid == "test-uuid"
        assert record.session_id == "session-123"
        assert record.record_type == "user"

    def test_default_values(self):
        """Should have correct default values."""
        record = ParsedRecord(
            uuid="uuid",
            session_id="session",
            timestamp=datetime.now(timezone.utc),
            record_type="assistant",
        )
        assert record.parent_uuid is None
        assert record.role is None
        assert record.content_text is None
        assert record.model is None
        assert record.tool_calls == []
        assert record.tool_results == []
        assert record.is_sidechain is False
        assert record.agent_id is None
        assert record.raw_data == {}


class TestIncrementalParser:
    """Test IncrementalParser class."""

    def test_init_with_path(self, tmp_path):
        """Should initialize with file path."""
        file_path = tmp_path / "session.jsonl"
        parser = IncrementalParser(str(file_path))

        assert parser.file_path == file_path
        assert parser.offset == 0
        assert parser._session_id is None

    def test_session_id_extracted_from_file(self, tmp_path):
        """Should extract session_id from file records."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "user",
                "uuid": "uuid-1",
                "sessionId": "extracted-session-id",
                "timestamp": "2025-01-15T10:00:00Z",
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        assert parser.session_id == "extracted-session-id"

    def test_session_id_none_when_file_missing(self, tmp_path):
        """Should return None when file doesn't exist."""
        file_path = tmp_path / "nonexistent.jsonl"
        parser = IncrementalParser(str(file_path))

        assert parser.session_id is None

    def test_session_id_extracted_from_later_line(self, tmp_path):
        """Should find session_id even if first lines don't have it."""
        file_path = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot", "uuid": "u1"}),
            json.dumps({"type": "user", "uuid": "u2", "sessionId": "found-session"}),
        ]
        file_path.write_text("\n".join(lines) + "\n")

        parser = IncrementalParser(str(file_path))
        assert parser.session_id == "found-session"

    def test_parse_new_records_empty_file(self, tmp_path):
        """Should return empty list for empty file."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text("")

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert records == []

    def test_parse_new_records_nonexistent_file(self, tmp_path):
        """Should return empty list when file doesn't exist."""
        file_path = tmp_path / "nonexistent.jsonl"
        parser = IncrementalParser(str(file_path))

        records = parser.parse_new_records()

        assert records == []

    def test_parse_new_records_user_message(self, tmp_path):
        """Should parse user message records."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "user",
                "uuid": "user-uuid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": "Hello, Claude!",
                },
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].uuid == "user-uuid"
        assert records[0].record_type == "user"
        assert records[0].role == "user"
        assert records[0].content_text == "Hello, Claude!"

    def test_parse_new_records_assistant_message(self, tmp_path):
        """Should parse assistant message records."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "assistant",
                "uuid": "assistant-uuid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-3-opus",
                    "content": [{"type": "text", "text": "Hello! How can I help?"}],
                },
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].uuid == "assistant-uuid"
        assert records[0].role == "assistant"
        assert records[0].model == "claude-3-opus"
        assert records[0].content_text == "Hello! How can I help?"

    def test_parse_new_records_with_tool_calls(self, tmp_path):
        """Should parse assistant messages with tool calls."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "assistant",
                "uuid": "tool-uuid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Let me read that file."},
                        {
                            "type": "tool_use",
                            "id": "tool-call-1",
                            "name": "Read",
                            "input": {"file_path": "/path/to/file"},
                        },
                    ],
                },
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].content_text == "Let me read that file."
        assert len(records[0].tool_calls) == 1
        assert records[0].tool_calls[0]["name"] == "Read"

    def test_parse_new_records_with_tool_results(self, tmp_path):
        """Should parse user messages with tool results."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "user",
                "uuid": "result-uuid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-call-1",
                            "content": "File content here",
                        },
                    ],
                },
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert len(records[0].tool_results) == 1
        assert records[0].tool_results[0]["tool_use_id"] == "tool-call-1"

    def test_incremental_parsing(self, tmp_path):
        """Should only parse new records on subsequent calls."""
        file_path = tmp_path / "session.jsonl"

        # Write first record
        with open(file_path, "w") as f:
            f.write(json.dumps({
                "type": "user",
                "uuid": "first",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
            }) + "\n")

        parser = IncrementalParser(str(file_path))
        records1 = parser.parse_new_records()
        assert len(records1) == 1
        assert records1[0].uuid == "first"

        # Append second record
        with open(file_path, "a") as f:
            f.write(json.dumps({
                "type": "assistant",
                "uuid": "second",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:01:00Z",
            }) + "\n")

        records2 = parser.parse_new_records()
        assert len(records2) == 1
        assert records2[0].uuid == "second"

    def test_skips_metadata_records(self, tmp_path):
        """Should skip file-history-snapshot and other metadata records."""
        file_path = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "file-history-snapshot", "uuid": "skip1"}),
            json.dumps({"type": "queue-operation", "uuid": "skip2"}),
            json.dumps({"type": "summary", "uuid": "skip3"}),
            json.dumps({
                "type": "user",
                "uuid": "keep",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
            }),
        ]
        file_path.write_text("\n".join(lines) + "\n")

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].uuid == "keep"

    def test_handles_invalid_json(self, tmp_path):
        """Should skip invalid JSON lines."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            "invalid json line\n"
            + json.dumps({
                "type": "user",
                "uuid": "valid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].uuid == "valid"

    def test_handles_missing_type(self, tmp_path):
        """Should skip records without type field."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({"uuid": "no-type", "sessionId": "s1"}) + "\n"
            + json.dumps({
                "type": "user",
                "uuid": "has-type",
                "sessionId": "s1",
                "timestamp": "2025-01-15T10:00:00Z",
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].uuid == "has-type"

    def test_sidechain_flag(self, tmp_path):
        """Should extract is_sidechain flag."""
        file_path = tmp_path / "session.jsonl"
        file_path.write_text(
            json.dumps({
                "type": "assistant",
                "uuid": "agent-uuid",
                "sessionId": "session-1",
                "timestamp": "2025-01-15T10:00:00Z",
                "isSidechain": True,
                "agentId": "agent-123",
            }) + "\n"
        )

        parser = IncrementalParser(str(file_path))
        records = parser.parse_new_records()

        assert len(records) == 1
        assert records[0].is_sidechain is True
        assert records[0].agent_id == "agent-123"


class TestRecordToStep:
    """Test record_to_step() function."""

    def test_user_message_conversion(self):
        """Should convert user message to USER_MESSAGE step."""
        record = ParsedRecord(
            uuid="user-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="user",
            content_text="Hello, Claude!",
        )

        step, tool_records = record_to_step(record, step_id=1)

        assert step is not None
        assert step.type == StepType.USER_MESSAGE
        assert step.step_id == 1
        assert "Hello" in step.content_summary
        assert tool_records == []

    def test_assistant_message_conversion(self):
        """Should convert assistant message to ASSISTANT_MESSAGE step."""
        record = ParsedRecord(
            uuid="assistant-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="assistant",
            content_text="I can help with that!",
        )

        step, tool_records = record_to_step(record, step_id=2)

        assert step is not None
        assert step.type == StepType.ASSISTANT_MESSAGE
        assert step.step_id == 2
        assert "help" in step.content_summary
        assert tool_records == []

    def test_tool_call_conversion(self):
        """Should convert assistant with tool calls to TOOL_CALL step."""
        record = ParsedRecord(
            uuid="tool-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="assistant",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "Read",
                    "input": {"file_path": "/path/to/file.txt"},
                }
            ],
        )

        step, tool_records = record_to_step(record, step_id=3)

        assert step is not None
        assert step.type == StepType.TOOL_CALL
        assert step.tool_call_id == "call-1"
        assert step.tool_name == "Read"
        assert len(tool_records) == 1
        assert tool_records[0].tool_name == "Read"
        assert tool_records[0].status == ToolCallStatus.PENDING

    def test_tool_result_conversion(self):
        """Should convert user with tool results to TOOL_RESULT step."""
        record = ParsedRecord(
            uuid="result-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="user",
            tool_results=[
                {
                    "tool_use_id": "call-1",
                    "content": "File content here",
                }
            ],
        )

        step, tool_records = record_to_step(record, step_id=4)

        assert step is not None
        assert step.type == StepType.TOOL_RESULT
        assert step.tool_call_id == "call-1"

    def test_system_event_conversion(self):
        """Should convert system record to SYSTEM_EVENT step."""
        record = ParsedRecord(
            uuid="system-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="system",
            content_text="Session initialized",
        )

        step, tool_records = record_to_step(record, step_id=5)

        assert step is not None
        assert step.type == StepType.SYSTEM_EVENT

    def test_unknown_type_returns_none(self):
        """Should return None for unknown record types."""
        record = ParsedRecord(
            uuid="unknown-uuid",
            session_id="session-1",
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            record_type="file-history-snapshot",
        )

        step, tool_records = record_to_step(record, step_id=6)

        assert step is None
        assert tool_records == []


class TestSummarizeToolCalls:
    """Test _summarize_tool_calls() function."""

    def test_empty_tool_calls(self):
        """Should return placeholder for empty list."""
        result = _summarize_tool_calls([])
        assert "no tool calls" in result

    def test_single_tool_call(self):
        """Should format single tool call with input."""
        tool_calls = [
            {
                "name": "Read",
                "input": {"file_path": "/path/to/file.txt"},
            }
        ]
        result = _summarize_tool_calls(tool_calls)

        assert "[Read]" in result
        assert "file" in result.lower()

    def test_multiple_tool_calls(self):
        """Should list all tool names for multiple calls."""
        tool_calls = [
            {"name": "Read", "input": {}},
            {"name": "Write", "input": {}},
            {"name": "Bash", "input": {}},
        ]
        result = _summarize_tool_calls(tool_calls)

        assert "Read" in result
        assert "Write" in result
        assert "Bash" in result


class TestSummarizeToolResults:
    """Test _summarize_tool_results() function."""

    def test_empty_tool_results(self):
        """Should return placeholder for empty list."""
        result = _summarize_tool_results([])
        assert "no tool results" in result

    def test_single_result_with_string_content(self):
        """Should summarize single string result."""
        tool_results = [
            {
                "tool_use_id": "call-1",
                "content": "File content here",
            }
        ]
        result = _summarize_tool_results(tool_results)

        assert "Result:" in result

    def test_multiple_results(self):
        """Should indicate count for multiple results."""
        tool_results = [
            {"tool_use_id": "call-1", "content": "result1"},
            {"tool_use_id": "call-2", "content": "result2"},
        ]
        result = _summarize_tool_results(tool_results)

        assert "2 results" in result


class TestUpdateToolCallStatus:
    """Test update_tool_call_status() function."""

    def test_updates_pending_call(self):
        """Should update pending call when result arrives."""
        call_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        result_time = datetime(2025, 1, 15, 10, 0, 5, tzinfo=timezone.utc)

        pending_call = ToolCallRecord(
            tool_call_id="call-1",
            session_id="session-1",
            step_id=1,
            tool_name="Read",
            input_summary="file.txt",
            called_at=call_time,
            status=ToolCallStatus.PENDING,
        )
        pending_calls = {"call-1": pending_call}

        record = ParsedRecord(
            uuid="result-uuid",
            session_id="session-1",
            timestamp=result_time,
            record_type="user",
            tool_results=[
                {
                    "tool_use_id": "call-1",
                    "content": "File content here",
                }
            ],
        )

        completed = update_tool_call_status(pending_calls, record)

        assert len(completed) == 1
        assert completed[0].status == ToolCallStatus.SUCCESS
        assert completed[0].completed_at == result_time
        assert completed[0].duration_ms == 5000  # 5 seconds
        assert "call-1" not in pending_calls

    def test_handles_error_result(self):
        """Should mark as ERROR when is_error flag is set."""
        pending_call = ToolCallRecord(
            tool_call_id="call-1",
            session_id="session-1",
            step_id=1,
            tool_name="Bash",
            input_summary="command",
            called_at=datetime.now(timezone.utc),
            status=ToolCallStatus.PENDING,
        )
        pending_calls = {"call-1": pending_call}

        record = ParsedRecord(
            uuid="error-uuid",
            session_id="session-1",
            timestamp=datetime.now(timezone.utc),
            record_type="user",
            tool_results=[
                {
                    "tool_use_id": "call-1",
                    "content": "Command failed",
                    "is_error": True,
                }
            ],
        )

        completed = update_tool_call_status(pending_calls, record)

        assert len(completed) == 1
        assert completed[0].status == ToolCallStatus.ERROR

    def test_ignores_unknown_tool_use_id(self):
        """Should ignore results for unknown tool calls."""
        pending_calls = {}

        record = ParsedRecord(
            uuid="orphan-uuid",
            session_id="session-1",
            timestamp=datetime.now(timezone.utc),
            record_type="user",
            tool_results=[
                {
                    "tool_use_id": "unknown-call",
                    "content": "Result",
                }
            ],
        )

        completed = update_tool_call_status(pending_calls, record)

        assert completed == []

    def test_handles_list_content(self):
        """Should extract text from list content."""
        pending_call = ToolCallRecord(
            tool_call_id="call-1",
            session_id="session-1",
            step_id=1,
            tool_name="Read",
            input_summary="file",
            called_at=datetime.now(timezone.utc),
            status=ToolCallStatus.PENDING,
        )
        pending_calls = {"call-1": pending_call}

        record = ParsedRecord(
            uuid="list-result-uuid",
            session_id="session-1",
            timestamp=datetime.now(timezone.utc),
            record_type="user",
            tool_results=[
                {
                    "tool_use_id": "call-1",
                    "content": [
                        {"type": "text", "text": "Part 1"},
                        {"type": "text", "text": "Part 2"},
                    ],
                }
            ],
        )

        completed = update_tool_call_status(pending_calls, record)

        assert len(completed) == 1
        assert "Part 1" in completed[0].result_summary
        assert "Part 2" in completed[0].result_summary
