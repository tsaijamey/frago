"""
JSONL Incremental Parser

Provides incremental parsing capabilities for Claude Code session files, supporting:
- File offset tracking, parsing only new lines
- Claude Code record type identification and conversion
- Defensive parsing, handling format changes
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from frago.session.models import (
    SessionStep,
    StepType,
    ToolCallRecord,
    ToolCallStatus,
    extract_tool_input_summary,
    truncate_content,
)

logger = logging.getLogger(__name__)


# ============================================================
# Parsed Record Types
# ============================================================


@dataclass
class ParsedRecord:
    """Parsed record

    Key information extracted from JSONL raw records.
    """

    uuid: str
    session_id: str
    timestamp: datetime
    record_type: str  # user, assistant, system, file-history-snapshot
    parent_uuid: Optional[str] = None

    # Message content
    role: Optional[str] = None  # user, assistant
    content_text: Optional[str] = None  # Text content
    model: Optional[str] = None  # Model identifier

    # Tool call information (assistant messages may contain)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Tool result information (user messages may contain)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    # Sidechain identifier (agent subthread)
    is_sidechain: bool = False
    agent_id: Optional[str] = None

    # Raw data
    raw_data: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# Incremental Parser
# ============================================================


class IncrementalParser:
    """JSONL incremental parser

    Tracks file offset, parsing only new lines.
    """

    def __init__(self, file_path: str):
        """Initialize parser

        Args:
            file_path: JSONL file path
        """
        self.file_path = Path(file_path)
        self.offset: int = 0  # Current file offset
        self._session_id: Optional[str] = None  # Cached session ID

    @property
    def session_id(self) -> Optional[str]:
        """Get session ID (extracted from file records)

        Note: The first line of the file may be file-history-snapshot or other records without sessionId,
        need to read subsequent lines until sessionId is found.
        """
        if self._session_id is None and self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    for _ in range(10):  # Read at most 10 lines
                        line = f.readline().strip()
                        if not line:
                            break
                        data = json.loads(line)
                        session_id = data.get("sessionId")
                        if session_id:
                            self._session_id = session_id
                            break
            except Exception as e:
                logger.warning(f"Unable to extract session_id from file: {e}")
        return self._session_id

    def parse_new_records(self) -> List[ParsedRecord]:
        """Parse records added since last time

        Returns:
            List of new records
        """
        if not self.file_path.exists():
            return []

        records = []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                # Seek to last read position
                f.seek(self.offset)

                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        record = self._parse_record(data)
                        if record:
                            records.append(record)
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON parsing error: {e}")
                        continue

                # Update offset
                self.offset = f.tell()

        except Exception as e:
            logger.error(f"Failed to read file: {e}")

        return records

    def _parse_record(self, data: Dict[str, Any]) -> Optional[ParsedRecord]:
        """Parse a single record

        Uses defensive parsing strategy:
        - Unknown fields are ignored, will not cause parsing failure
        - Warnings are logged when key fields are missing, but parsing continues as much as possible
        - Maintains backward compatibility when format changes

        Args:
            data: Raw JSON data

        Returns:
            Parsed record, None if unable to parse
        """
        # Required field checks
        record_type = data.get("type")
        uuid = data.get("uuid")
        session_id = data.get("sessionId")

        if not record_type:
            logger.debug("Record missing type field, skipping")
            return None

        # Skip metadata record types (these are not core conversation data, no need to track)
        METADATA_TYPES = {"file-history-snapshot", "queue-operation", "summary"}
        if record_type in METADATA_TYPES:
            logger.debug(f"Skipping metadata record: {record_type}")
            return None

        if not uuid:
            # When uuid is missing, try to use other identifiers (for unknown new record types)
            uuid = data.get("id") or data.get("messageId") or f"unknown-{id(data)}"
            logger.debug(f"Record missing uuid field, using fallback identifier: {uuid[:20]}")

        # session_id missing warning (but does not block parsing)
        if not session_id and not self._session_id:
            logger.warning("Record missing sessionId field, session association may fail")

        # Parse timestamp (ensure UTC timezone is used)
        timestamp_str = data.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        record = ParsedRecord(
            uuid=uuid,
            session_id=session_id or self._session_id or "",
            timestamp=timestamp,
            record_type=record_type,
            parent_uuid=data.get("parentUuid"),
            is_sidechain=data.get("isSidechain", False),
            agent_id=data.get("agentId"),
            raw_data=data,
        )

        # Cache session_id
        if session_id and not self._session_id:
            self._session_id = session_id

        # Extract additional information based on type
        message = data.get("message", {})
        if message:
            record.role = message.get("role")
            record.model = message.get("model")

            # Extract content
            content = message.get("content")
            if isinstance(content, str):
                record.content_text = content
            elif isinstance(content, list):
                # content is an array of content blocks
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            text_parts.append(block.get("text", ""))
                        elif block_type == "tool_use":
                            tool_calls.append(block)
                        elif block_type == "tool_result":
                            tool_results.append(block)

                record.content_text = "\n".join(text_parts) if text_parts else None
                record.tool_calls = tool_calls
                record.tool_results = tool_results

        return record


# ============================================================
# Record Type Conversion
# ============================================================


def record_to_step(
    record: ParsedRecord, step_id: int
) -> Tuple[Optional[SessionStep], List[ToolCallRecord]]:
    """Convert parsed record to SessionStep and ToolCallRecord

    Args:
        record: Parsed record
        step_id: Step sequence number

    Returns:
        (SessionStep or None, ToolCallRecord list)
    """
    step = None
    tool_records = []

    # Determine step type and extract tool info
    tool_call_id = None
    tool_name = None

    if record.record_type == "user":
        if record.tool_results:
            # Contains tool results
            step_type = StepType.TOOL_RESULT
            content = _summarize_tool_results(record.tool_results)
            # Extract tool_use_id for pairing with tool_call
            if record.tool_results:
                tool_call_id = record.tool_results[0].get("tool_use_id")
        else:
            step_type = StepType.USER_MESSAGE
            content = truncate_content(record.content_text or "(empty message)")

    elif record.record_type == "assistant":
        if record.tool_calls:
            # Contains tool calls
            step_type = StepType.TOOL_CALL
            content = _summarize_tool_calls(record.tool_calls)
            # Extract tool_call_id and tool_name for pairing and display
            first_call = record.tool_calls[0]
            tool_call_id = first_call.get("id")
            tool_name = first_call.get("name")

            # Create tool call records
            for tc in record.tool_calls:
                tool_record = ToolCallRecord(
                    tool_call_id=tc.get("id", ""),
                    session_id=record.session_id,
                    step_id=step_id,
                    tool_name=tc.get("name", "Unknown"),
                    input_summary=extract_tool_input_summary(tc.get("input", {})),
                    called_at=record.timestamp,
                    status=ToolCallStatus.PENDING,
                )
                tool_records.append(tool_record)
        else:
            step_type = StepType.ASSISTANT_MESSAGE
            content = truncate_content(record.content_text or "(empty response)")

    elif record.record_type == "system":
        step_type = StepType.SYSTEM_EVENT
        content = truncate_content(record.content_text or "(system event)")

    else:
        # Ignore other types (such as file-history-snapshot)
        return None, []

    step = SessionStep(
        step_id=step_id,
        session_id=record.session_id,
        type=step_type,
        timestamp=record.timestamp,
        content_summary=content,
        raw_uuid=record.uuid,
        parent_uuid=record.parent_uuid,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )

    return step, tool_records


def _summarize_tool_calls(tool_calls: List[Dict[str, Any]]) -> str:
    """Summarize tool call information

    Args:
        tool_calls: Tool call list

    Returns:
        Tool call summary
    """
    if not tool_calls:
        return "(no tool calls)"

    tool_names = [tc.get("name", "?") for tc in tool_calls]
    if len(tool_names) == 1:
        tc = tool_calls[0]
        input_summary = extract_tool_input_summary(tc.get("input", {}))
        return truncate_content(f"[{tool_names[0]}] {input_summary}")
    else:
        return f"[{', '.join(tool_names)}]"


def _summarize_tool_results(tool_results: List[Dict[str, Any]]) -> str:
    """Summarize tool result information

    Args:
        tool_results: Tool result list

    Returns:
        Tool result summary
    """
    if not tool_results:
        return "(no tool results)"

    # Extract result summaries
    summaries = []
    for tr in tool_results:
        tool_use_id = tr.get("tool_use_id", "?")
        content = tr.get("content", "")
        if isinstance(content, str):
            summaries.append(truncate_content(content, 50))
        else:
            summaries.append("(complex result)")

    if len(summaries) == 1:
        return f"Result: {summaries[0]}"
    else:
        return f"({len(summaries)} results)"


# ============================================================
# Tool Call Status Update
# ============================================================


def update_tool_call_status(
    pending_calls: Dict[str, ToolCallRecord],
    record: ParsedRecord,
) -> List[ToolCallRecord]:
    """Update pending tool call status based on tool results

    Args:
        pending_calls: Pending tool call dictionary (tool_call_id -> ToolCallRecord)
        record: Record containing tool results

    Returns:
        List of completed tool call records
    """
    completed = []

    for result in record.tool_results:
        tool_use_id = result.get("tool_use_id")
        if tool_use_id and tool_use_id in pending_calls:
            call = pending_calls.pop(tool_use_id)

            # Update status
            call.completed_at = record.timestamp
            call.status = ToolCallStatus.SUCCESS  # Assume success for now

            # Calculate duration
            if call.called_at:
                delta = record.timestamp - call.called_at
                call.duration_ms = int(delta.total_seconds() * 1000)

            # Extract result summary
            content = result.get("content", "")
            if isinstance(content, str):
                call.result_summary = truncate_content(content, 100)
            elif isinstance(content, list):
                # May be a result containing multiple blocks
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                call.result_summary = truncate_content(" ".join(text_parts), 100)

            # Check for error flag
            is_error = result.get("is_error", False)
            if is_error:
                call.status = ToolCallStatus.ERROR

            completed.append(call)

    return completed
