"""Stream-JSON parser for Frago GUI.

Handles parsing of line-delimited JSON streams from frago agent output.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Generator, Iterator, Optional

from frago.gui.models import MessageType, StreamMessage


@dataclass
class ParseResult:
    """Result of parsing a stream line."""

    success: bool
    message: Optional[StreamMessage] = None
    error: Optional[str] = None
    raw_line: str = ""


class StreamJsonParser:
    """Parser for line-delimited JSON streams."""

    def __init__(self) -> None:
        """Initialize the parser."""
        self._buffer = ""

    def parse_line(self, line: str) -> ParseResult:
        """Parse a single line of stream output.

        Args:
            line: A line from the stream.

        Returns:
            ParseResult with success status and parsed message.
        """
        line = line.strip()
        if not line:
            return ParseResult(success=True, raw_line=line)

        try:
            data = json.loads(line)
            message = self._data_to_message(data)
            return ParseResult(success=True, message=message, raw_line=line)
        except json.JSONDecodeError as e:
            message = StreamMessage(
                type=MessageType.ASSISTANT,
                content=line,
                timestamp=datetime.now(),
            )
            return ParseResult(success=True, message=message, raw_line=line)

    def _data_to_message(self, data: Dict[str, Any]) -> StreamMessage:
        """Convert parsed JSON data to StreamMessage.

        Args:
            data: Parsed JSON dictionary.

        Returns:
            StreamMessage instance.
        """
        msg_type_str = data.get("type", "assistant")
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            msg_type = MessageType.ASSISTANT

        content = data.get("content", "")
        if not content and "text" in data:
            content = data["text"]
        if not content and "message" in data:
            content = data["message"]

        progress = data.get("progress")
        if progress is not None:
            try:
                progress = float(progress)
            except (ValueError, TypeError):
                progress = None

        return StreamMessage(
            type=msg_type,
            content=str(content),
            timestamp=datetime.now(),
            metadata=data.get("metadata", {}),
            progress=progress,
            step=data.get("step"),
        )

    def parse_stream(self, lines: Iterator[str]) -> Generator[StreamMessage, None, None]:
        """Parse a stream of lines.

        Args:
            lines: Iterator of lines from the stream.

        Yields:
            StreamMessage instances for each parsed line.
        """
        for line in lines:
            result = self.parse_line(line)
            if result.success and result.message:
                yield result.message

    def reset(self) -> None:
        """Reset the parser state."""
        self._buffer = ""


def parse_stream_line(line: str) -> Optional[StreamMessage]:
    """Convenience function to parse a single stream line.

    Args:
        line: A line from the stream.

    Returns:
        StreamMessage if parsing successful, None otherwise.
    """
    parser = StreamJsonParser()
    result = parser.parse_line(line)
    return result.message if result.success else None


def stream_to_messages(
    lines: Iterator[str],
    on_message: Optional[Callable[[StreamMessage], None]] = None,
) -> list[StreamMessage]:
    """Parse stream lines and optionally call callback for each message.

    Args:
        lines: Iterator of lines from the stream.
        on_message: Optional callback for each message.

    Returns:
        List of all parsed messages.
    """
    parser = StreamJsonParser()
    messages = []

    for line in lines:
        result = parser.parse_line(line)
        if result.success and result.message:
            messages.append(result.message)
            if on_message:
                on_message(result.message)

    return messages
