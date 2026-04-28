"""
CDP type definitions

Defines type hints related to Chrome DevTools Protocol.
"""

from typing import Dict, Any, Optional, Union, List, TypedDict


# CDP command related types
CommandParams = Dict[str, Any]
CommandResult = Dict[str, Any]


class CDPResponse(TypedDict, total=False):
    """CDP response data structure"""
    id: int
    result: Optional[CommandResult]
    error: Optional[Dict[str, Any]]
    method: Optional[str]
    params: Optional[Dict[str, Any]]


class CDPRequest(TypedDict):
    """CDP request data structure"""
    id: int
    method: str
    params: Optional[CommandParams]


# Connection related types
WebSocketMessage = Union[str, bytes]


# Retry related types
RetryCallback = Any  # Retry callback function type


# Configuration related types
ConfigDict = Dict[str, Any]


# Event related types
EventHandler = Any  # Event handler function type


class SessionInfo(TypedDict):
    """Session information"""
    id: str
    title: str
    url: str
    type: str
    webSocketDebuggerUrl: str


from dataclasses import dataclass, field


@dataclass
class ProxyConfig:
    """Proxy configuration data class"""

    enabled: bool = False
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    no_proxy_hosts: List[str] = field(default_factory=list)

    def get_websocket_proxy_config(self) -> Dict[str, Any]:
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