"""
CDP type definitions

Defines type hints related to Chrome DevTools Protocol.
"""

from dataclasses import dataclass, field
from typing import Any, TypedDict

# CDP command related types
CommandParams = dict[str, Any]
CommandResult = dict[str, Any]


class CDPResponse(TypedDict, total=False):
    """CDP response data structure"""
    id: int
    result: CommandResult | None
    error: dict[str, Any] | None
    method: str | None
    params: dict[str, Any] | None


class CDPRequest(TypedDict):
    """CDP request data structure"""
    id: int
    method: str
    params: CommandParams | None


# Connection related types
WebSocketMessage = str | bytes


# Retry related types
RetryCallback = Any  # Retry callback function type


# Configuration related types
ConfigDict = dict[str, Any]


# Event related types
EventHandler = Any  # Event handler function type


class SessionInfo(TypedDict):
    """Session information"""
    id: str
    title: str
    url: str
    type: str
    webSocketDebuggerUrl: str


@dataclass
class ProxyConfig:
    """Proxy configuration data class"""

    enabled: bool = False
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    no_proxy_hosts: list[str] = field(default_factory=list)

    def get_websocket_proxy_config(self) -> dict[str, Any]:
        """Get WebSocket proxy configuration"""
        if not self.enabled or self.no_proxy:
            return {}

        config = {}
        if self.host and self.port:
            config["http_proxy_host"] = self.host
            config["http_proxy_port"] = self.port

        if self.username and self.password:
            config["http_proxy_auth"] = (self.username, self.password)

        return config

    @property
    def no_proxy(self) -> bool:
        """Whether to bypass proxy"""
        return not self.enabled or len(self.no_proxy_hosts) > 0
