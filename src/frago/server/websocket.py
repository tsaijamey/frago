"""WebSocket connection manager for real-time updates.

Provides WebSocket broadcast capability for:
- Task status updates
- Session sync events
- Log streaming
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and message broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
        """
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send a message to all connected clients.

        Args:
            message: Message dict to broadcast
        """
        if not self.active_connections:
            return

        message_json = json.dumps(message, default=str)
        dead_connections: List[WebSocket] = []

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message_json)
                except Exception:
                    dead_connections.append(connection)

        # Clean up dead connections
        for conn in dead_connections:
            await self.disconnect(conn)

    async def send_personal(
        self, websocket: WebSocket, message: Dict[str, Any]
    ) -> None:
        """Send a message to a specific client.

        Args:
            websocket: Target WebSocket connection
            message: Message dict to send
        """
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception:
            await self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self.active_connections)


# Global connection manager instance
manager = ConnectionManager()


# Message type constants
class MessageType:
    """WebSocket message types."""

    # Connection events
    CONNECTED = "connected"
    PING = "ping"
    PONG = "pong"

    # Task events
    TASK_STARTED = "task_started"
    TASK_UPDATED = "task_updated"
    TASK_COMPLETED = "task_completed"
    TASK_ERROR = "task_error"

    # Session events
    SESSION_SYNC = "session_sync"
    SESSION_CREATED = "session_created"
    SESSION_UPDATED = "session_updated"

    # Recipe events
    RECIPE_STARTED = "recipe_started"
    RECIPE_COMPLETED = "recipe_completed"

    # Console events
    CONSOLE_USER_MESSAGE = "console_user_message"
    CONSOLE_ASSISTANT_THINKING = "console_assistant_thinking"
    CONSOLE_TOOL_EXECUTING = "console_tool_executing"
    CONSOLE_TOOL_RESULT = "console_tool_result"
    CONSOLE_SESSION_STATUS = "console_session_status"


def create_message(
    msg_type: str,
    data: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a WebSocket message.

    Args:
        msg_type: Message type from MessageType constants
        data: Optional message payload
        task_id: Optional associated task ID

    Returns:
        Formatted message dict
    """
    message = {
        "type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if task_id:
        message["task_id"] = task_id

    if data:
        message["data"] = data

    return message


async def broadcast_task_update(
    task_id: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """Broadcast a task status update.

    Args:
        task_id: Task identifier
        status: Task status (running, completed, error)
        data: Optional additional data
    """
    msg_type = {
        "running": MessageType.TASK_STARTED,
        "completed": MessageType.TASK_COMPLETED,
        "error": MessageType.TASK_ERROR,
    }.get(status, MessageType.TASK_UPDATED)

    message = create_message(msg_type, data, task_id)
    message["status"] = status
    await manager.broadcast(message)


async def broadcast_session_sync(sessions: List[Dict[str, Any]]) -> None:
    """Broadcast session sync update.

    Args:
        sessions: List of session data
    """
    message = create_message(MessageType.SESSION_SYNC, {"sessions": sessions})
    await manager.broadcast(message)
