"""
CDP模块 - Chrome DevTools Protocol封装

提供浏览器自动化控制的Python接口。
"""

from .client import CDPClient
from .session import CDPSession
from .config import CDPConfig
from .exceptions import CDPError, ConnectionError, TimeoutError

__all__ = [
    "CDPClient",
    "CDPSession", 
    "CDPConfig",
    "CDPError",
    "ConnectionError",
    "TimeoutError",
]