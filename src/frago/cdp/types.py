"""
CDP类型定义

定义Chrome DevTools Protocol相关的类型提示。
"""

from typing import Dict, Any, Optional, Union, List, TypedDict


# CDP命令相关类型
CommandParams = Dict[str, Any]
CommandResult = Dict[str, Any]


class CDPResponse(TypedDict, total=False):
    """CDP响应数据结构"""
    id: int
    result: Optional[CommandResult]
    error: Optional[Dict[str, Any]]
    method: Optional[str]
    params: Optional[Dict[str, Any]]


class CDPRequest(TypedDict):
    """CDP请求数据结构"""
    id: int
    method: str
    params: Optional[CommandParams]


# 连接相关类型
WebSocketMessage = Union[str, bytes]


# 重试相关类型
RetryCallback = Any  # 重试回调函数类型


# 配置相关类型
ConfigDict = Dict[str, Any]


# 事件相关类型
EventHandler = Any  # 事件处理函数类型


class SessionInfo(TypedDict):
    """会话信息"""
    id: str
    title: str
    url: str
    type: str
    webSocketDebuggerUrl: str


from dataclasses import dataclass, field


@dataclass
class ProxyConfig:
    """代理配置数据类"""
    
    enabled: bool = False
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    no_proxy_hosts: List[str] = field(default_factory=list)
    
    def get_websocket_proxy_config(self) -> Dict[str, Any]:
        """获取WebSocket代理配置"""
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
        """是否绕过代理"""
        return not self.enabled or len(self.no_proxy_hosts) > 0