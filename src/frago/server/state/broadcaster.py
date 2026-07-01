"""StateBroadcaster — server 全局状态的订阅 + WebSocket 广播层。

从 StateManager 拆出：订阅者清单与 WS 传输细节集中在此。序列化（recipes/skills/
projects → dict）仍由 StateManager 负责（它持有 model 与 _*_to_dict），算好 payload
后交给本类发送。行为与原 StateManager._broadcast / _broadcast_raw / subscribe 完全一致：
- broadcast：发 `data_{data_type}` 消息，不通知本地订阅者（保持原 _broadcast 语义）。
- broadcast_raw：发原始 `msg_type` 消息后，无论发送成败都通知本地订阅者（保持原语义）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


class StateBroadcaster:
    """状态变更的订阅与 WebSocket 广播。"""

    def __init__(self) -> None:
        self._subscribers: List[Callable[[str, Any], None]] = []

    def subscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to state changes.

        Args:
            callback: Function called with (data_type, data) on changes
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str, Any], None]) -> None:
        """Unsubscribe from state changes."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    async def broadcast(self, data_type: str, version: int, payload: Any) -> None:
        """Broadcast a typed state change to WebSocket clients.

        payload 由调用方（StateManager）按 data_type 算好（含 dataclass→dict 序列化）。
        """
        try:
            from frago.server.websocket import create_message, manager

            message = create_message(
                f"data_{data_type}", {"version": version, "data": payload}
            )
            await manager.broadcast(message)
            logger.debug(f"Broadcast {data_type} to {manager.connection_count} clients")
        except Exception as e:
            logger.warning(f"Failed to broadcast {data_type}: {e}")

    async def broadcast_raw(self, msg_type: str, version: int, data: Any) -> None:
        """Broadcast raw data to WebSocket clients, then notify local subscribers."""
        try:
            from frago.server.websocket import create_message, manager

            message = create_message(msg_type, {"version": version, "data": data})
            await manager.broadcast(message)
            logger.debug(f"Broadcast {msg_type} to {manager.connection_count} clients")
        except Exception as e:
            logger.warning(f"Failed to broadcast {msg_type}: {e}")

        # Notify local subscribers
        for callback in self._subscribers:
            try:
                callback(msg_type, data)
            except Exception as e:
                logger.warning(f"Subscriber callback failed: {e}")
